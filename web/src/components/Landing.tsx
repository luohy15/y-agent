import { Link } from "react-router";
import { useAuth } from "../hooks/useAuth";
import GoogleSignInButton from "./GoogleSignInButton";

const CDN = "https://cdn.luohy15.com/y-agent";

const FEATURES = [
  {
    title: "Chat & dispatch",
    image: `${CDN}/y-agent-home.png`,
    body: "One root chat dispatches sub-tasks to specialized skills (plan, impl, review, dev). Every call is a row in a tree, with steer / interrupt / share built in. The waterfall TraceView shows where time and tokens went.",
  },
  {
    title: "Notes & knowledge graph",
    image: `${CDN}/y-agent-note.png`,
    body: "Plans, requirements, decisions, journals — captured as notes pinned to todos. Promote a note to an entity and link it to people, projects, or RSS feeds. The agent reads the same files you do.",
  },
  {
    title: "Routine & always-on",
    image: `${CDN}/y-agent-routine.png`,
    body: "Coding agents live on EC2 inside tmux. Lambda + Telegram cover the always-on surface; reminders, RSS, and routines fire on schedule. Costs round to zero when idle, and a daily journal still shows up at 9 a.m.",
  },
];

const GITHUB_URL = "https://github.com/luohy15/y-agent";
const CHANGELOG_URL = "https://github.com/luohy15/y-agent/blob/main/CHANGELOG.md";

export default function Landing() {
  const { gsiReady } = useAuth();

  return (
    <div className="min-h-screen bg-sol-base03 text-sol-base0">
      <header className="max-w-5xl mx-auto px-6 pt-8 pb-4 flex items-center justify-between">
        <div className="text-sol-base1 font-semibold tracking-tight">y-agent</div>
        <nav className="flex items-center gap-5 text-sm">
          <Link to="/docs" className="text-sol-base1 hover:text-sol-cyan">Docs</Link>
          <a href={CHANGELOG_URL} target="_blank" rel="noopener noreferrer" className="text-sol-base1 hover:text-sol-cyan">CHANGELOG</a>
          <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className="text-sol-base1 hover:text-sol-cyan">GitHub</a>
        </nav>
      </header>

      <section className="max-w-5xl mx-auto px-6 pt-10 pb-16">
        <h1 className="text-4xl sm:text-5xl font-semibold text-sol-base2 tracking-tight">
          A personal AI agent built on coding agents.
        </h1>
        <p className="mt-5 text-base sm:text-lg text-sol-base1 max-w-3xl leading-relaxed">
          Coding agents like Claude Code and Codex are great for code, but code is only part of daily life.
          y-agent extends them into ledgers, calendars, todos, notes, links, RSS, and email — same files for you and the agent, same CLI surface, always-on via Lambda and Telegram.
        </p>

        <div className="mt-8 flex flex-wrap items-center gap-3">
          <GoogleSignInButton
            gsiReady={gsiReady}
            className="px-5 py-2.5 bg-sol-cyan text-sol-base03 rounded-md text-sm font-semibold cursor-pointer hover:bg-sol-base1 hover:text-sol-base03"
          />
          <Link
            to="/docs"
            className="px-5 py-2.5 bg-sol-base02 border border-sol-base01 text-sol-base1 rounded-md text-sm font-semibold hover:bg-sol-base01 hover:text-sol-base2"
          >
            Docs
          </Link>
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="px-5 py-2.5 bg-sol-base02 border border-sol-base01 text-sol-base1 rounded-md text-sm font-semibold hover:bg-sol-base01 hover:text-sol-base2"
          >
            GitHub
          </a>
          <a
            href="/t/6fc5c4"
            className="px-5 py-2.5 text-sm font-semibold text-sol-base1 hover:text-sol-cyan"
          >
            See a demo trace →
          </a>
        </div>

        <div className="mt-12 rounded-lg overflow-hidden border border-sol-base02 bg-sol-base02">
          <img
            src="https://cdn.luohy15.com/y-agent-demo-4.png"
            alt="y-agent TraceView: waterfall of a real cross-skill task"
            className="w-full block"
            loading="eager"
          />
        </div>
      </section>

      <section className="max-w-5xl mx-auto px-6 pb-16">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {FEATURES.map((f) => (
            <article key={f.title} className="bg-sol-base02 border border-sol-base02 rounded-lg overflow-hidden flex flex-col">
              <div className="bg-sol-base03 border-b border-sol-base02">
                <img
                  src={f.image}
                  alt={f.title}
                  className="w-full block"
                  loading="lazy"
                />
              </div>
              <div className="p-5 flex-1">
                <h3 className="text-sol-base2 font-semibold text-base">{f.title}</h3>
                <p className="mt-2 text-sm text-sol-base1 leading-relaxed">{f.body}</p>
              </div>
            </article>
          ))}
        </div>
      </section>

      <footer className="max-w-5xl mx-auto px-6 pb-10 pt-6 border-t border-sol-base02 text-sm text-sol-base01 flex flex-wrap items-center justify-between gap-4">
        <div>Built by <a href="https://luohy15.com" target="_blank" rel="noopener noreferrer" className="text-sol-base1 hover:text-sol-cyan">luohy15</a>.</div>
        <div className="flex items-center gap-5">
          <Link to="/docs" className="hover:text-sol-cyan">Docs</Link>
          <a href={CHANGELOG_URL} target="_blank" rel="noopener noreferrer" className="hover:text-sol-cyan">CHANGELOG</a>
          <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className="hover:text-sol-cyan">GitHub</a>
        </div>
      </footer>
    </div>
  );
}
