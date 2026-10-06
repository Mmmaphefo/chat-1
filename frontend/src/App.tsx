import { Link, Route, Routes, useParams } from "react-router-dom";
import { ReposPage } from "./pages/ReposPage";
import { RepoPage } from "./pages/RepoPage";

function RepoRoute() {
  const { id } = useParams();
  return <RepoPage key={id} id={id ?? ""} />;
}

export default function App() {
  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-40 border-b border-ink-700 bg-ink-950/85 backdrop-blur">
        <div className="mx-auto flex max-w-[1440px] items-center gap-3 px-4 py-2.5">
          <Link to="/" className="flex items-center gap-2">
            <span className="grid h-7 w-7 place-items-center rounded-lg border border-accent/50 bg-accent/15 text-[11px] font-bold text-accent">
              RAT
            </span>
            <span className="text-sm font-semibold text-slate-100">Repo Analysis Tool</span>
          </Link>
          <span className="ml-auto hidden text-[11px] text-slate-500 md:block">
            git metrics · authors · files · directories · commit sets
          </span>
        </div>
      </header>
      <Routes>
        <Route path="/" element={<ReposPage />} />
        <Route path="/repos/:id" element={<RepoRoute />} />
        <Route
          path="*"
          element={
            <main className="mx-auto max-w-2xl px-4 py-20 text-center text-sm text-slate-400">
              Page not found — <Link className="link" to="/">back to repositories</Link>
            </main>
          }
        />
      </Routes>
    </div>
  );
}
