import { useAuth } from "../hooks/useAuth";
import GoogleSignInButton from "./GoogleSignInButton";
import LandingTour from "./LandingTour";

const GITHUB_URL = "https://github.com/luohy15/y-agent";
const CHANGELOG_URL = "https://github.com/luohy15/y-agent/blob/main/CHANGELOG.md";

export default function Landing() {
  const { gsiReady } = useAuth();

  return (
    <div className="min-h-screen bg-sol-base03 text-sol-base0">
      <header className="max-w-[1200px] mx-auto px-6 pt-8 pb-4 flex items-center justify-between">
        <div className="text-sol-base1 font-semibold tracking-tight">y-agent</div>
        <nav className="flex items-center gap-5 text-sm">
          <a href={CHANGELOG_URL} target="_blank" rel="noopener noreferrer" className="text-sol-base1 hover:text-sol-cyan">CHANGELOG</a>
          <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className="text-sol-base1 hover:text-sol-cyan">GitHub</a>
        </nav>
      </header>

      <section className="max-w-[1200px] mx-auto px-6 pt-8 pb-12">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl sm:text-4xl font-semibold text-sol-base2 tracking-tight">
            Dispatch anywhere. Connect everything.
          </h1>
          <span className="border border-dashed border-sol-base01 rounded px-2 text-xs text-sol-base1">Concept demo, not a live run</span>
        </div>
        <p className="mt-4 text-base sm:text-lg text-sol-base1 max-w-3xl leading-relaxed">
          Hand off a task from any device. Your todos, notes, links, email, calendar and finances live in one place, and they all link together.
        </p>

        <div className="mt-6 flex flex-wrap items-center gap-3">
          <GoogleSignInButton
            gsiReady={gsiReady}
            className="px-5 py-2.5 bg-sol-cyan text-sol-base03 rounded text-sm font-semibold cursor-pointer hover:bg-sol-base1 hover:text-sol-base03"
          />
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="px-5 py-2.5 bg-sol-base02 border border-sol-base01 text-sol-base1 rounded text-sm font-semibold hover:bg-sol-base01 hover:text-sol-base2"
          >
            GitHub
          </a>
        </div>

        <div className="mt-10">
          <LandingTour />
        </div>
      </section>

      <footer className="max-w-[1200px] mx-auto px-6 pb-10 pt-6 border-t border-sol-base02 text-sm text-sol-base01 flex flex-wrap items-center justify-between gap-4">
        <div>Built by <a href="https://luohy15.com" target="_blank" rel="noopener noreferrer" className="text-sol-base1 hover:text-sol-cyan">luohy15</a>.</div>
        <div className="flex items-center gap-5">
          <a href={CHANGELOG_URL} target="_blank" rel="noopener noreferrer" className="hover:text-sol-cyan">CHANGELOG</a>
          <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className="hover:text-sol-cyan">GitHub</a>
        </div>
      </footer>
    </div>
  );
}
