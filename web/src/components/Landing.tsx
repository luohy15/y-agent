import { useEffect, useState } from "react";
import { useTheme } from "../hooks/useTheme";
import { prefersDark, resolveTheme } from "../utils/theme";

const GITHUB_URL = "https://github.com/luohy15/y-agent";
const CHANGELOG_URL = "https://github.com/luohy15/y-agent/blob/main/CHANGELOG.md";

const LEDGER: { record: string; y1: string; y3: string; y5: string }[] = [
  { record: "Todos", y1: "a list", y3: "what you actually finish", y5: "how you estimate and commit" },
  { record: "Notes", y1: "daily logs", y3: "themes you can search", y5: "your thinking, in your words" },
  { record: "Links", y1: "saves", y3: "a reading trail", y5: "what you keep returning to" },
  { record: "Mail", y1: "an inbox", y3: "threads tied to decisions", y5: "correspondence per person" },
  { record: "Calendar", y1: "events", y3: "the shape of your weeks", y5: "how you spend years" },
  { record: "Accounts", y1: "balances", y3: "a balance sheet", y5: "progress you can compare" },
  { record: "Voice", y1: "transcripts", y3: "how you speak about work", y5: "drafts in your own voice" },
];

const LAYERS = [
  { cls: "fill-sol-blue", d: "M60 300 L60 290.5 L170 278.2 L280 261.7 L390 239.8 L500 216.9 L500 300 Z" },
  { cls: "fill-sol-cyan", d: "M60 290.5 L170 278.2 L280 261.7 L390 239.8 L500 216.9 L500 157.9 L390 198.4 L280 236.2 L170 264.1 L60 284.3 Z" },
  { cls: "fill-sol-violet", d: "M60 284.3 L170 264.1 L280 236.2 L390 198.4 L500 157.9 L500 112.3 L390 166.4 L280 216.5 L170 253.9 L60 279.8 Z" },
  { cls: "fill-sol-magenta", d: "M60 279.8 L170 253.9 L280 216.5 L390 166.4 L500 112.3 L500 77.5 L390 142.0 L280 202.6 L170 246.2 L60 276.5 Z" },
  { cls: "fill-sol-orange", d: "M60 276.5 L170 246.2 L280 202.6 L390 142.0 L500 77.5 L500 50.7 L390 123.2 L280 191.0 L170 239.8 L60 273.7 Z" },
  { cls: "fill-sol-green", d: "M60 273.7 L170 239.8 L280 191.0 L390 123.2 L500 50.7 L500 32.0 L390 112.0 L280 184.0 L170 236.0 L60 272.0 Z" },
];

const LEGEND = [
  { cls: "bg-sol-blue", label: "notes" },
  { cls: "bg-sol-cyan", label: "links" },
  { cls: "bg-sol-violet", label: "mail" },
  { cls: "bg-sol-magenta", label: "calendar" },
  { cls: "bg-sol-orange", label: "accounts" },
  { cls: "bg-sol-green", label: "voice" },
];

function Mark({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 20 20" aria-hidden="true">
      <rect className="fill-sol-base00" x="2" y="13" width="6" height="5" rx="1" />
      <rect className="fill-sol-blue" x="2" y="8" width="11" height="5" rx="1" />
      <rect className="fill-sol-base2" x="2" y="3" width="16" height="5" rx="1" />
    </svg>
  );
}

function useOsPrefersDark(): boolean {
  const [osDark, setOsDark] = useState(prefersDark);
  useEffect(() => {
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setOsDark(mql.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);
  return osDark;
}

export default function Landing() {
  const { prefs, setMode } = useTheme(false);
  const osDark = useOsPrefersDark();
  const dark = resolveTheme(prefs, osDark) === "solarized-dark";

  return (
    <div className="fixed inset-0 overflow-y-auto bg-sol-base03 text-sol-base0 font-mono scroll-smooth motion-reduce:scroll-auto">
      <div className="max-w-[1120px] mx-auto px-6">
        <header className="flex flex-wrap items-center gap-2.5 pt-7 pb-2">
          <Mark className="w-5 h-5 shrink-0" />
          <span className="text-[17px] font-semibold tracking-tight text-sol-base2">Yovy</span>
          <nav className="ml-auto flex flex-wrap items-center gap-3 min-[640px]:gap-[18px] text-xs text-sol-base1">
            <a href="#accumulates" className="hover:text-sol-blue">What accumulates</a>
            <a href="#surfaces" className="hover:text-sol-blue">Surfaces</a>
            <a href={CHANGELOG_URL} target="_blank" rel="noopener noreferrer" className="hover:text-sol-blue">CHANGELOG</a>
            <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className="hover:text-sol-blue">GitHub</a>
            <button
              type="button"
              className="rounded border border-dashed border-sol-base01 bg-transparent px-[9px] py-1 text-[11px] text-sol-base00 cursor-pointer hover:text-sol-base1"
              onClick={() => setMode(dark ? "light" : "dark")}
              aria-pressed={dark}
            >
              {dark ? "Light" : "Dark"}
            </button>
          </nav>
        </header>

        <section className="grid items-center gap-9 py-10 min-[920px]:grid-cols-[1.02fr_0.98fr] min-[920px]:gap-14 min-[920px]:py-16 min-[920px]:pb-[72px]">
          <div>
            <h1 className="m-0 text-[clamp(38px,5vw,56px)] font-semibold leading-[1.06] tracking-[-0.02em] text-sol-base2">
              <span className="block">Keep.</span>
              <span className="block">Link.</span>
              <span className="block text-sol-blue">Ask.</span>
            </h1>
            <p className="mt-6 max-w-[50ch] text-base leading-relaxed text-sol-base1">
              Your todos, notes, links, mail, calendar, accounts and voice stay in one linked record, and an agent works across all of it.
            </p>
            <div className="mt-[26px] flex flex-wrap items-center gap-3">
              <a
                href="#accumulates"
                className="yovy-btn-primary rounded bg-sol-blue px-4 py-[9px] text-[13px] font-semibold text-sol-base03"
              >
                See what accumulates
              </a>
              <a
                href={GITHUB_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded border border-sol-base01 bg-sol-base02 px-4 py-[9px] text-[13px] font-semibold text-sol-base1 hover:border-sol-blue hover:text-sol-blue"
              >
                GitHub
              </a>
            </div>
            <p className="mt-3.5 text-[11px] text-sol-base00">Private deployment. No public sign-up yet.</p>
          </div>

          <figure className="m-0 rounded border border-sol-base02 bg-sol-base02 px-[18px] pb-3.5 pt-[18px]">
            <div className="mb-1 flex items-baseline justify-between gap-3">
              <span className="text-xs text-sol-base1">One record, 2022 → 2026</span>
              <span className="text-[11px] text-sol-base00">records kept, by kind</span>
            </div>
            <svg viewBox="0 0 580 380" role="img" aria-labelledby="chartTitle chartDesc" className="block h-auto w-full">
              <title id="chartTitle">Stacked record, 2022 to 2026</title>
              <desc id="chartDesc">Six kinds of kept records stack up across five years. Each year builds on the previous one; nothing is discarded.</desc>
              <g className="stroke-sol-base01/45" strokeWidth="1" strokeDasharray="2 5">
                <line x1="60" y1="300" x2="500" y2="300" />
                <line x1="60" y1="240" x2="500" y2="240" />
                <line x1="60" y1="180" x2="500" y2="180" />
                <line x1="60" y1="120" x2="500" y2="120" />
                <line x1="60" y1="60" x2="500" y2="60" />
              </g>
              <g className="opacity-[0.82]">
                {LAYERS.map((layer) => (
                  <path key={layer.cls} className={layer.cls} d={layer.d} />
                ))}
              </g>
              <line className="stroke-sol-base01" x1="500" y1="32" x2="500" y2="300" strokeWidth="1" strokeDasharray="3 4" />
              <circle className="fill-sol-blue" cx="500" cy="32" r="3.5" />
              <text className="fill-sol-base00 text-[11px]" x="512" y="36">now</text>
              <g className="fill-sol-base00 text-[11px]">
                <text x="60" y="322" textAnchor="middle">2022</text>
                <text x="170" y="322" textAnchor="middle">2023</text>
                <text x="280" y="322" textAnchor="middle">2024</text>
                <text x="390" y="322" textAnchor="middle">2025</text>
                <text x="500" y="322" textAnchor="middle">2026</text>
              </g>
              <text className="fill-sol-base00 text-[10px]" x="60" y="344">Each year adds a layer. Nothing leaves the record.</text>
            </svg>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1.5 text-[11px] text-sol-base00">
              {LEGEND.map((item) => (
                <span key={item.label} className="inline-flex items-center gap-1.5">
                  <i className={`inline-block h-[9px] w-[9px] rounded-full ${item.cls}`} />
                  {item.label}
                </span>
              ))}
            </div>
            <p className="mt-2.5 border-t border-sol-base01/40 pt-2.5 text-[12.5px] leading-snug text-sol-base0">
              This year's question can see every year before it. That is the whole product.
            </p>
          </figure>
        </section>

        <section className="border-t border-sol-base02 py-[52px]">
          <div className="grid gap-[22px] min-[820px]:grid-cols-3 min-[820px]:gap-7">
            <div className="border-t border-sol-base01 pt-3.5">
              <div className="text-[11px] text-sol-base00">01</div>
              <h3 className="mb-1.5 mt-1.5 text-base font-semibold text-sol-base2">Keep</h3>
              <p className="m-0 text-[13.5px] leading-snug text-sol-base0">
                Everything you save lands in one store: todos, notes, links, mail, calendar events, balances, voice takes.
              </p>
            </div>
            <div className="border-t border-sol-base01 pt-3.5">
              <div className="text-[11px] text-sol-base00">02</div>
              <h3 className="mb-1.5 mt-1.5 text-base font-semibold text-sol-base2">Link</h3>
              <p className="m-0 text-[13.5px] leading-snug text-sol-base0">
                Records reference each other. A task carries its note, its source link, its event and its reminder.
              </p>
            </div>
            <div className="border-t border-sol-base01 pt-3.5">
              <div className="text-[11px] text-sol-base00">03</div>
              <h3 className="mb-1.5 mt-1.5 text-base font-semibold text-sol-base2">Ask</h3>
              <p className="m-0 text-[13.5px] leading-snug text-sol-base0">
                An agent runs across the linked record and writes the result back into it, where the next question can read it.
              </p>
            </div>
          </div>
        </section>

        <section id="accumulates" className="border-t border-sol-base02 py-[52px]">
          <div className="mb-[30px] flex flex-wrap items-baseline gap-x-4 gap-y-2">
            <h2 className="m-0 text-xl font-semibold tracking-[-0.015em] text-sol-base2">What the record becomes</h2>
            <p className="m-0 text-xs text-sol-base00">same record, later</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-[13px]">
              <thead>
                <tr>
                  {["Record", "Year 1", "Year 3", "Year 5"].map((heading) => (
                    <th
                      key={heading}
                      className="border-b border-sol-base01 pb-2.5 pr-3.5 text-left text-[11px] font-medium uppercase tracking-[0.06em] text-sol-base00"
                    >
                      {heading}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {LEDGER.map((row) => (
                  <tr key={row.record}>
                    <td className="whitespace-nowrap border-b border-sol-base02 py-[13px] pr-3.5 align-top font-semibold text-sol-base2">{row.record}</td>
                    <td className="border-b border-sol-base02 py-[13px] pr-3.5 align-top text-xs leading-snug text-sol-base0">{row.y1}</td>
                    <td className="border-b border-sol-base02 py-[13px] pr-3.5 align-top text-xs leading-snug text-sol-base0">{row.y3}</td>
                    <td className="border-b border-sol-base02 py-[13px] pr-3.5 align-top text-xs leading-snug text-sol-base2 before:mr-2 before:inline-block before:h-[5px] before:w-[5px] before:rounded-full before:bg-sol-blue before:align-[2px] before:content-['']">
                      {row.y5}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-4 max-w-[70ch] text-[12.5px] text-sol-base00">
            These are uses of the record, not automatic reports. You ask; the agent works from what is actually there.
          </p>
        </section>

        <section id="surfaces" className="border-t border-sol-base02 py-[52px]">
          <div className="mb-[30px] flex flex-wrap items-baseline gap-x-4 gap-y-2">
            <h2 className="m-0 text-xl font-semibold tracking-[-0.015em] text-sol-base2">One record, every surface</h2>
            <p className="m-0 text-xs text-sol-base00">where work starts</p>
          </div>
          <p className="m-0 max-w-[62ch] text-[15px] leading-relaxed text-sol-base1">
            Send work from any device. The result lands in the same record, so a question asked later still has this year's answer.
          </p>
          <div className="my-[22px] mb-[26px] flex flex-wrap gap-2.5">
            <span className="inline-flex items-center gap-2 rounded border border-sol-base02 bg-sol-base02 px-3 py-2 text-xs text-sol-base1">
              <svg viewBox="0 0 16 16" aria-hidden="true" className="h-[15px] w-[15px] fill-none stroke-sol-base00" strokeWidth="1.4">
                <rect x="4" y="1.5" width="8" height="13" rx="1.5" />
                <line x1="7" y1="12.5" x2="9" y2="12.5" />
              </svg>
              phone
            </span>
            <span className="inline-flex items-center gap-2 rounded border border-sol-base02 bg-sol-base02 px-3 py-2 text-xs text-sol-base1">
              <svg viewBox="0 0 16 16" aria-hidden="true" className="h-[15px] w-[15px] fill-none stroke-sol-base00" strokeWidth="1.4">
                <rect x="2.5" y="2" width="11" height="12" rx="1.5" />
                <line x1="8" y1="11.5" x2="8" y2="11.5" />
              </svg>
              tablet
            </span>
            <span className="inline-flex items-center gap-2 rounded border border-sol-base02 bg-sol-base02 px-3 py-2 text-xs text-sol-base1">
              <svg viewBox="0 0 16 16" aria-hidden="true" className="h-[15px] w-[15px] fill-none stroke-sol-base00" strokeWidth="1.4">
                <rect x="3" y="3" width="10" height="7" rx="1" />
                <line x1="1.5" y1="12.5" x2="14.5" y2="12.5" />
              </svg>
              desktop
            </span>
            <span className="inline-flex items-center gap-2 rounded border border-sol-base02 bg-sol-base02 px-3 py-2 text-xs text-sol-base1">
              <svg viewBox="0 0 16 16" aria-hidden="true" className="h-[15px] w-[15px] fill-none stroke-sol-base00" strokeWidth="1.4">
                <path d="M2 3.5 L14 1.5 L11 14 L8 9.5 Z" />
              </svg>
              telegram
            </span>
            <span className="inline-flex items-center gap-2 rounded border border-sol-base02 bg-sol-base02 px-3 py-2 text-xs text-sol-base1">
              <svg viewBox="0 0 16 16" aria-hidden="true" className="h-[15px] w-[15px] fill-none stroke-sol-base00" strokeWidth="1.4">
                <path d="M2.5 4 L6 7 L2.5 10" />
                <line x1="7.5" y1="11" x2="13" y2="11" />
              </svg>
              cli
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-2.5 border-t border-sol-base02 pt-[18px] text-xs text-sol-base1">
            <b className="rounded border border-sol-base02 bg-sol-base02 px-2.5 py-1.5 font-medium">any device</b>
            <span className="text-sol-base00">→</span>
            <b className="rounded border border-sol-base02 bg-sol-base02 px-2.5 py-1.5 font-medium">cloud session</b>
            <span className="text-sol-base00">→</span>
            <b className="rounded border border-sol-base02 bg-sol-base02 px-2.5 py-1.5 font-medium">linked record</b>
            <span className="ml-1 text-sol-base00">the result stays</span>
          </div>
        </section>

        <footer className="flex flex-wrap items-center justify-between gap-3.5 border-t border-sol-base02 py-[26px] pb-10 text-xs text-sol-base00">
          <div>Yovy</div>
          <div className="flex gap-5">
            <a href={CHANGELOG_URL} target="_blank" rel="noopener noreferrer" className="hover:text-sol-blue">CHANGELOG</a>
            <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className="hover:text-sol-blue">GitHub</a>
            <a href="https://luohy15.com" target="_blank" rel="noopener noreferrer" className="hover:text-sol-blue">Built by luohy15</a>
          </div>
        </footer>
      </div>
    </div>
  );
}
