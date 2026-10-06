"""Author identity resolution: mailmap + manual merges.

Every commit carries a *raw* identity (``%an``/``%ae``) and a *mailmapped*
identity (``%aN``/``%aE``, resolved by git itself).  On top of that users can
create manual merge groups of raw identities.

Effective identity for a commit:

1. If its raw identity belongs to a manual merge group -> the group's
   canonical identity (the member with the most commits).
2. Else if mailmap application is enabled -> the mailmapped identity.
3. Else -> the raw identity.

Identities are exposed as ``"Name <email>"`` keys.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .parse import ParsedRepo

IDENTITY_RE = re.compile(r"^(?P<name>.*?)\s*<(?P<email>[^<>]*)>$")


def format_key(name: str, email: str) -> str:
    return f"{name} <{email}>"


def parse_key(key: str) -> tuple[str, str]:
    m = IDENTITY_RE.match(key.strip())
    if not m:
        return key.strip(), ""
    return m.group("name").strip(), m.group("email").strip()


@dataclass
class MergeGroup:
    id: str
    label: str | None
    members: list[dict[str, str]]   # [{"name": ..., "email": ...}]

    def as_json(self) -> dict:
        return {"id": self.id, "label": self.label, "members": self.members}


@dataclass
class IdentityResolver:
    parsed: ParsedRepo
    groups: list[MergeGroup]
    apply_mailmap: bool

    # raw identity -> effective key
    raw_to_key: dict[tuple[str, str], str] = field(default_factory=dict)
    # effective key -> raw identities
    key_to_raws: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    # effective key -> (display name, display email)
    key_display: dict[str, tuple[str, str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._build()

    # ------------------------------------------------------------------ #
    def _mailmap(self, raw: tuple[str, str]) -> tuple[str, str]:
        if not self.apply_mailmap:
            return raw
        return self._mm_cache.get(raw, raw)

    _mm_cache: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)

    def _build(self) -> None:
        # mailmap lookup cache built in one pass over all commits.
        if self.apply_mailmap:
            mm_cache: dict[tuple[str, str], tuple[str, str]] = {}
            for c in self.parsed.commits:
                raw = (c.name, c.email)
                if raw not in mm_cache:
                    mm_cache[raw] = (c.mm_name, c.mm_email)
            self._mm_cache = mm_cache

        group_of: dict[tuple[str, str], tuple[str, str]] = {}
        for group in self.groups:
            members = [
                (m.get("name", ""), m.get("email", "")) for m in group.members
            ]
            members = [m for m in members if m in self.parsed.raw_counts]
            if not members:
                continue
            canonical = max(
                members,
                key=lambda m: (self.parsed.raw_counts.get(m, 0), m[0], m[1]),
            )
            for m in members:
                group_of[m] = canonical

        for raw in self.parsed.raw_counts:
            canonical_raw = group_of.get(raw, raw)
            mapped = self._mailmap(canonical_raw)
            key = format_key(*mapped)
            self.raw_to_key[raw] = key
            self.key_to_raws.setdefault(key, []).append(raw)
            if key not in self.key_display:
                self.key_display[key] = mapped

    # ------------------------------------------------------------------ #
    def key_for_commit(self, name: str, email: str) -> str:
        return self.raw_to_key.get((name, email), format_key(name, email))

    def display(self, key: str) -> tuple[str, str]:
        return self.key_display.get(key, parse_key(key))

    def aliases(self, key: str) -> list[dict]:
        out = []
        for raw in sorted(
            self.key_to_raws.get(key, []),
            key=lambda r: -self.parsed.raw_counts.get(r, 0),
        ):
            out.append({
                "name": raw[0],
                "email": raw[1],
                "commits": self.parsed.raw_counts.get(raw, 0),
            })
        return out

    def is_merged(self, key: str) -> bool:
        return len(self.key_to_raws.get(key, [])) > 1


def suggest_merges(
    parsed: ParsedRepo,
    resolver: IdentityResolver,
    limit: int = 25,
) -> list[dict]:
    """Heuristically suggest raw identities that look like one person.

    Signals: identical names, identical emails, or identical email local
    parts.  Only raw identities that currently resolve to *different*
    effective authors are suggested, and each group is suggested once.
    """
    buckets: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for raw in parsed.raw_counts:
        name, email = raw
        if not email or not name:
            continue
        local = email.lower().partition("@")[0]
        signals = [
            ("name", name.strip().lower()),
            ("email", email.strip().lower()),
            ("local-part", local),
        ]
        for kind, value in signals:
            if value:
                buckets.setdefault((kind, value), set()).add(raw)

    suggestions: list[dict] = []
    seen_groups: set[frozenset] = set()
    for (kind, value), members in sorted(buckets.items()):
        if len(members) < 2:
            continue
        keys = {resolver.raw_to_key.get(m, format_key(*m)) for m in members}
        if len(keys) < 2:
            continue  # already merged (mailmap or manual)
        frozen = frozenset(members)
        if frozen in seen_groups:
            continue
        seen_groups.add(frozen)
        suggestions.append({
            "reason": kind,
            "detail": value,
            "members": sorted(
                ({"name": m[0], "email": m[1],
                  "commits": parsed.raw_counts.get(m, 0)} for m in members),
                key=lambda m: -m["commits"],
            ),
        })
        if len(suggestions) >= limit:
            break
    suggestions.sort(key=lambda s: -len(s["members"]))
    return suggestions
