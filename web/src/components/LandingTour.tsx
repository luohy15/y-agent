import { Fragment, useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { CHAPTERS, MOVERS, PARTS, POS, SATS, STEPS, type Mover, type Pt } from "./landingTour";

// Render `code` spans written with backticks in the tour copy.
function rich(text: string): ReactNode {
  return text.split("`").map((s, i) => (i % 2 ? <code key={i}>{s}</code> : <Fragment key={i}>{s}</Fragment>));
}

const tr = ([x, y]: Pt) => `translate(${x}px, ${y}px)`;

const CLIENT_BOXES: { key: string; y: number; label: string; sub: string; tx: number; glyph: ReactNode }[] = [
  { key: "phone", y: 40, label: "Phone", sub: "browser", tx: 62, glyph: <rect className="lt-glyph" x="32" y="52" width="20" height="36" rx="3" /> },
  { key: "tablet", y: 124, label: "Tablet", sub: "browser", tx: 62, glyph: <rect className="lt-glyph" x="30" y="138" width="26" height="34" rx="3" /> },
  { key: "laptop", y: 208, label: "Laptop", sub: "browser", tx: 66, glyph: <><rect className="lt-glyph" x="31" y="224" width="26" height="18" rx="2" /><path className="lt-glyph" d="M27 248 H61" /></> },
  { key: "tg", y: 292, label: "Telegram", sub: "private chat", tx: 66, glyph: <path className="lt-glyph" d="M31 322 L57 310 L51 338 L44 328 Z" /> },
  { key: "cli", y: 376, label: "Terminal", sub: "y chat", tx: 66, glyph: <path className="lt-glyph" d="M32 398 L40 405 L32 412 M44 414 H56" /> },
];

const EDGES: [string, string, string?][] = [
  ["trace", "M400 250 H650"],
  ["d-note", "M690 228 L630 112"],
  ["d-link", "M690 228 L750 112"],
  ["d-cal", "M650 240 L570 192"],
  ["d-rem", "M650 260 L570 308"],
  ["d-remcal", "M524 204 V296"],
  ["g-note", "M810 172 L667 100"],
  ["g-link", "M840 166 L775 112"],
  ["g-rss", "M856 204 V296"],
  ["r-cal", "M478 192 L400 230", "read"],
  ["r-mail", "M713 412 C560 470 420 380 380 310", "read"],
  ["r-fin", "M575 400 C480 400 420 360 360 310", "read"],
  ["w-note", "M380 190 C420 110 520 80 575 90", "read"],
];

const GHOSTS: [string, number, number][] = [
  ["todo app", 600, 40], ["notes app", 700, 40], ["read-later", 800, 40],
  ["RSS reader", 600, 478], ["reminders", 720, 478], ["budgeting", 820, 478],
];

const MOVER_BOXES: Record<Mover, [string, number, number]> = {
  msg: ["plan next week", 116, 26], res: ["answer ✓", 80, 26], cal: ["events", 60, 22],
  mail: ["inbox", 60, 22], fin: ["holdings", 68, 22], note: ["weekly plan", 90, 22],
};

export default function LandingTour() {
  const [step, setStep] = useState(0);
  const [picked, setPicked] = useState<string | null>(null);
  const animateNext = useRef(false);
  const movers = useRef<Partial<Record<Mover, SVGGElement | null>>>({});
  const s = STEPS[step];
  const last = STEPS.length - 1;

  const go = (i: number) => {
    animateNext.current = true;
    setStep(Math.max(0, Math.min(last, i)));
  };
  const replay = () => {
    animateNext.current = false;
    setStep(0);
  };

  useLayoutEffect(() => {
    const animate = animateNext.current;
    animateNext.current = false;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    for (const name of MOVERS) {
      const g = movers.current[name];
      if (!g) continue;
      g.getAnimations?.().forEach(a => a.cancel());
      const path = s.mv[name];
      g.classList.toggle("on", !!path);
      if (!path) continue;
      const pts = path.map(k => POS[k]);
      g.style.transform = tr(pts[pts.length - 1]);
      if (animate && !reduce && pts.length > 1 && g.animate)
        g.animate(pts.map(p => ({ transform: tr(p) })), { duration: 700 * (pts.length - 1), easing: "ease-in-out" });
    }
  }, [step, s]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as Element | null;
      if (t?.closest?.(".lt-part, input, textarea, [contenteditable]")) return;
      if (e.key === "ArrowRight") go(step + 1);
      else if (e.key === "ArrowLeft") go(step - 1);
      else if (e.key === "r" || e.key === "R") replay();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  });

  const partClass = (k: string) =>
    ["lt-part", s.a.includes(k) && "active", s.dim.includes(k) && "dim", k === picked && "picked"].filter(Boolean).join(" ");
  const partProps = (k: string, label: string) => ({
    className: partClass(k),
    "data-part": k,
    tabIndex: 0,
    role: "button",
    "aria-label": label,
    onClick: () => setPicked(k),
    onKeyDown: (e: ReactKeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setPicked(k); }
    },
  });
  const edgeClass = (k: string, extra?: string) =>
    ["lt-link", extra, s.edges.includes(k) && "on", s.hot?.includes(k) && "hot"].filter(Boolean).join(" ");
  const status = (k: string) => s.st?.[k] ?? "";
  const pickedPart = picked ? PARTS[picked] : null;
  const chapterLabel = s.ch === 0 ? "Intro" : `${CHAPTERS[s.ch - 1].label} · step ${step} / ${last}`;

  return (
    <div className="lt grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_320px] gap-3.5">
      <div className="lt-stage border border-sol-base02 rounded">
        <svg viewBox="0 0 960 500" role="img" aria-labelledby="lt-title" className="block w-full h-auto">
          <title id="lt-title">On the left, several devices send a task to a cloud session; on the right, notes, links, calendar, reminders, entities, RSS, email and finance circle task T and link to each other</title>

          {/* ring of tags (dashed), gap at finance */}
          <path className={edgeClass("ring", "tag")} d="M563 370 A180 170 0 1 1 690 420" />
          {EDGES.map(([k, d, kind]) => <path key={k} className={edgeClass(k, kind)} d={d} />)}
          <text className={`lt-elabel${s.edges.includes("trace") ? " on" : ""}`} x="525" y="243" textAnchor="middle">trace = task ID</text>

          {CLIENT_BOXES.map(c => (
            <g key={c.key} {...partProps(c.key, PARTS[c.key][0])}>
              <rect className="lt-depth" x="24" y={c.y + 4} width="128" height="62" rx="4" />
              <rect className="lt-body" x="20" y={c.y} width="128" height="62" rx="4" />
              {c.glyph}
              <text className="lt-lbl" x={c.tx} y={c.y + 26}>{c.label}</text>
              <text className="lt-sub" x={c.tx} y={c.y + 42}>{c.sub}</text>
              <text className="lt-status" x={c.tx} y={c.y + 56}>{status(c.key)}</text>
            </g>
          ))}

          <g {...partProps("cloud", "Cloud session")}>
            <rect className="lt-depth" x="234" y="174" width="170" height="156" rx="4" />
            <rect className="lt-body" x="230" y="170" width="170" height="156" rx="4" />
            <path className="lt-glyph" d="M252 214 a12 12 0 0 1 22 -6 a10 10 0 0 1 18 6 a8 8 0 0 1 0 14 h-40 a8 8 0 0 1 0 -14 z" />
            <text className="lt-lbl" x="244" y="252">Cloud session</text>
            <text className="lt-sub" x="244" y="268">EC2 · Claude Code</text>
            <text className="lt-status" x="244" y="300">{status("cloud")}</text>
          </g>

          <g {...partProps("todo", "Task T")}>
            <rect className="lt-depth" x="654" y="230" width="80" height="44" rx="4" />
            <rect className="lt-body" x="650" y="226" width="80" height="44" rx="4" />
            <text className="lt-lbl" x="690" y="246" textAnchor="middle">Task T</text>
            <text className="lt-sub" x="690" y="262" textAnchor="middle">todo</text>
          </g>
          {SATS.map(({ key, label, sub, x, y }) => (
            <g key={key} {...partProps(key, label)}>
              <rect className="lt-depth" x={x - 42} y={y - 17} width="92" height="38" rx="4" />
              <rect className="lt-body" x={x - 46} y={y - 21} width="92" height="38" rx="4" />
              <text className="lt-lbl" x={x - 36} y={y - 4}>{label}</text>
              <text className="lt-sub" x={x - 36} y={y + 11}>{sub}</text>
              <text className={`lt-tagmark${s.tags ? " on" : ""}`} x={x + 38} y={y - 4} textAnchor="end">#</text>
            </g>
          ))}

          {/* app categories no longer needed */}
          {GHOSTS.map(([t, x, y]) => <text key={t} className={`lt-ghost${s.ghosts ? " on" : ""}`} x={x} y={y}>{t}</text>)}

          {MOVERS.map(name => {
            const [t, w, h] = MOVER_BOXES[name];
            return (
              <g key={name} ref={el => { movers.current[name] = el; }} className="lt-mover">
                <rect x={-w / 2} y={-h / 2} width={w} height={h} rx="4" />
                <text x="0" y="4" textAnchor="middle">{t}</text>
              </g>
            );
          })}
        </svg>

        <div className="flex items-center gap-2 flex-wrap px-3 py-2.5 border-t border-sol-base02">
          <div className="flex gap-1.5">
            {CHAPTERS.map(c => (
              <button key={c.ch} type="button" className="lt-btn" aria-pressed={s.ch === c.ch} onClick={() => go(c.step)}>{c.label}</button>
            ))}
          </div>
          <div className="flex gap-1 mx-1.5" role="tablist" aria-label="Steps">
            {STEPS.map((x, i) => (
              <button
                key={i}
                type="button"
                role="tab"
                aria-selected={i === step}
                aria-label={`Step ${i}: ${x.t}`}
                className={["lt-dot", i && x.ch !== STEPS[i - 1].ch && "gap", i < step && "done", i === step && "now"].filter(Boolean).join(" ")}
                onClick={() => go(i)}
              />
            ))}
          </div>
          <span className="flex-1" />
          <button type="button" className="lt-btn" aria-label="Previous" disabled={step === 0} onClick={() => go(step - 1)}>←</button>
          <button type="button" className="lt-btn primary" disabled={step === last} onClick={() => go(step + 1)}>Next →</button>
          <button type="button" className="lt-btn" onClick={replay}>Replay</button>
        </div>
      </div>

      <aside className="flex flex-col gap-2.5">
        <div className="lt-card" aria-live="polite">
          <div className="lt-eyebrow">{chapterLabel}</div>
          <div className="lt-step-title" data-testid="step-title">{s.t}</div>
          <div>{s.x}</div>
          <details>
            <summary>How it works</summary>
            <div className="lt-real">In the code: {rich(s.r)}</div>
            {s.e && <div className="lt-edge">Limits: {rich(s.e)}</div>}
          </details>
        </div>
        <div className="lt-card">
          <div className="lt-eyebrow">Lines</div>
          <div className="flex flex-col gap-1 mt-1.5 text-xs">
            <div><svg className="lt-legend" viewBox="0 0 36 8"><path d="M0 4 H36" stroke="currentColor" strokeWidth="1.5" /></svg>Direct link (relation table / field)</div>
            <div><svg className="lt-legend" viewBox="0 0 36 8"><path d="M0 4 H36" stroke="currentColor" strokeWidth="1.5" strokeDasharray="6 5" /></svg>Shared tag</div>
            <div><svg className="lt-legend" viewBox="0 0 36 8"><path d="M2 4 H36" stroke="currentColor" strokeWidth="2" strokeDasharray="1.5 4" strokeLinecap="round" /></svg>Session reads / writes</div>
          </div>
        </div>
        <div className="lt-card">
          <div className="lt-eyebrow">Parts</div>
          <div className="lt-step-title" data-testid="part-title">{pickedPart ? pickedPart[0] : "Click any part"}</div>
          {pickedPart ? (
            <div>{rich(pickedPart[1])}<div className="lt-real">{rich(pickedPart[2])}</div></div>
          ) : (
            <div className="lt-hint">See what it is and which real feature it maps to.</div>
          )}
        </div>
        <div className="lt-hint">Keys: ← → to step, R to replay; Tab to a part, then Enter.</div>
      </aside>
    </div>
  );
}
