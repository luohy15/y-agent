// Seeded mock fixtures + a `window.fetch` override for the /showcase route.
//
// The point: drive the REAL panel components (TraceView, NoteList,
// LinkList) through their REAL `authFetch` / `jsonFetcher` code
// path so the rendered output is byte-for-byte production styling. We do NOT
// reimplement any panel. We only swap the data source by overriding the global
// `fetch` (which `authFetch` in `../api` ultimately calls) with URL-keyed
// fixtures. Everything below is fake/sample data; nothing here ships to a real
// backend and the route carries no auth.

// Timestamps are computed relative to "now" so the panels always look recent.
const NOW = Date.now();
const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

function isoDaysAgo(days: number, extraMs = 0): string {
  return new Date(NOW - days * DAY + extraMs).toISOString();
}

function ymdDaysAgo(days: number): string {
  return new Date(NOW - days * DAY).toISOString().slice(0, 10);
}

// --- /api/todo/list -> Todo[] -------------------------------------------------

export const TODOS_FIXTURE = [
  {
    todo_id: "2541",
    name: "Refresh y-agent docs: capability audit + auto-generated screenshots",
    status: "active",
    priority: "medium",
    tags: ["y-agent", "docs"],
    pinned: true,
    has_running: true,
    has_unread: true,
    updated_at: isoDaysAgo(0, -2 * HOUR),
    created_at: isoDaysAgo(1),
  },
  {
    todo_id: "2529",
    name: "Add Claude status RSS monitor with Telegram notifications",
    status: "completed",
    priority: "high",
    tags: ["worker", "monitor"],
    updated_at: isoDaysAgo(0, -5 * HOUR),
    created_at: isoDaysAgo(2),
  },
  {
    todo_id: "2510",
    name: "Multi-account Gmail sync: per-account IMAP app passwords",
    status: "completed",
    priority: "medium",
    tags: ["email"],
    updated_at: isoDaysAgo(1),
    created_at: isoDaysAgo(4),
  },
  {
    todo_id: "2498",
    name: "Finance: FIRE progress projection + savings-rate panel",
    status: "active",
    priority: "high",
    tags: ["finance", "web"],
    has_unread: true,
    updated_at: isoDaysAgo(1, -3 * HOUR),
    created_at: isoDaysAgo(5),
  },
  {
    todo_id: "2487",
    name: "Knowledge graph: entity ↔ note ↔ rss relations + sidebar panel",
    status: "completed",
    priority: "medium",
    tags: ["entity", "web"],
    updated_at: isoDaysAgo(2),
    created_at: isoDaysAgo(6),
  },
  {
    todo_id: "2470",
    name: "Trace share: publicly viewable waterfall with optional password",
    status: "pending",
    priority: "low",
    tags: ["trace"],
    updated_at: isoDaysAgo(2),
    created_at: isoDaysAgo(7),
  },
  {
    todo_id: "2455",
    name: "Claude Code TUI backend via tmux bracketed paste",
    status: "active",
    priority: "high",
    tags: ["agent", "worker"],
    updated_at: isoDaysAgo(3),
    created_at: isoDaysAgo(8),
  },
  {
    todo_id: "2440",
    name: "Link archive: EC2 as single source of truth, SSH-cat reads",
    status: "completed",
    priority: "medium",
    tags: ["link"],
    updated_at: isoDaysAgo(3),
    created_at: isoDaysAgo(9),
  },
  {
    todo_id: "2421",
    name: "Reminder EventBridge schedule + Telegram push",
    status: "pending",
    priority: "medium",
    tags: ["reminder"],
    updated_at: isoDaysAgo(4),
    created_at: isoDaysAgo(10),
  },
  {
    todo_id: "2404",
    name: "Command palette (⌘K) for fast panel + action navigation",
    status: "completed",
    priority: "low",
    tags: ["web"],
    updated_at: isoDaysAgo(5),
    created_at: isoDaysAgo(11),
  },
];

// --- /api/trace/chats -> TraceChatsResponse -----------------------------------

const traceSeg = (startMinAgo: number, durMin: number) => ({
  start_unix: NOW - startMinAgo * MIN,
  end_unix: NOW - startMinAgo * MIN + durMin * MIN,
});

export const TRACE_CHATS_FIXTURE = {
  todo_name: "Refresh y-agent docs: capability audit + auto-generated screenshots",
  todo_status: "active",
  chats: [
    {
      chat_id: "mgr-5ac0c3",
      title: "Coordinate docs refresh",
      topic: "manager",
      skill: "manager",
      backend: "claude_code",
      bot_name: "claude",
      segments: [traceSeg(240, 6), traceSeg(40, 4)],
    },
    {
      chat_id: "plan-9f2a11",
      title: "Audit capabilities + write plan note",
      topic: "plan",
      skill: "plan",
      backend: "claude_code",
      bot_name: "claude",
      segments: [traceSeg(228, 22)],
    },
    {
      chat_id: "impl-7f2bdd",
      title: "Screenshot tooling: fixtures + /showcase + playwright",
      topic: "dev",
      skill: "impl",
      backend: "claude_code",
      bot_name: "claude",
      segments: [traceSeg(196, 34), traceSeg(150, 18)],
    },
    {
      chat_id: "impl-docs-3c8e0a",
      title: "Docs refresh: capabilities / cli / getting-started",
      topic: "dev",
      skill: "impl",
      backend: "claude_code",
      bot_name: "sonnet",
      segments: [traceSeg(120, 28)],
    },
    {
      chat_id: "rev-1b77d4",
      title: "Review diff against plan",
      topic: "review",
      skill: "review",
      backend: "claude_code",
      bot_name: "claude",
      segments: [traceSeg(60, 12)],
    },
  ],
  todo: {
    todo_id: "2541",
    name: "Refresh y-agent docs: capability audit + auto-generated screenshots",
    status: "active",
    priority: "medium",
    tags: ["y-agent", "docs"],
    desc:
      "Refresh y-agent documentation: (1) audit and document all current capabilities, " +
      "(2) auto-generate panel screenshots (todo & trace, note, link, finance) reusing the " +
      "real components with mock data. Keep the client (CLI + GUI) vs server-deploy split.",
    progress: "Claim sub-tasks 1-3 (screenshot tooling): fixtures + /showcase route + playwright capture.",
    created_at: isoDaysAgo(1),
    updated_at: isoDaysAgo(0, -2 * HOUR),
    history: [
      { timestamp: isoDaysAgo(1), action: "created" },
      { timestamp: isoDaysAgo(1, 1 * MIN), action: "activated" },
      { timestamp: isoDaysAgo(0, -3 * HOUR), action: "updated", note: "Plan written: 4 showcased capabilities + 5 auto-screenshots" },
    ],
  },
  links: [
    {
      link_id: "lnk-001",
      base_url: "https://docs.anthropic.com/en/docs/claude-code",
      title: "Claude Code documentation",
      download_status: "done",
      activity_id: "act-001",
    },
    {
      link_id: "lnk-002",
      base_url: "https://playwright.dev/docs/screenshots",
      title: "Playwright: taking screenshots",
      download_status: "done",
      activity_id: "act-002",
    },
  ],
  notes: [
    {
      note_id: "b4f9cf",
      content_key: "pages/plan-2541-docs-refresh.md",
      front_matter: { tags: ["y-agent", "docs", "plan"] },
      created_at: isoDaysAgo(1),
    },
  ],
  calendar_events: [],
};

// --- /api/note/list?todo_id=... -> Note[] -------------------------------------

export const NOTES_FIXTURE = [
  {
    note_id: "b4f9cf",
    content_key: "pages/plan-2541-docs-refresh.md",
    front_matter: { tags: ["y-agent", "docs", "plan"] },
    created_at: isoDaysAgo(1),
    updated_at: isoDaysAgo(0, -3 * HOUR),
  },
  {
    note_id: "a17e92",
    content_key: "pages/decision-2541-screenshot-pipeline.md",
    front_matter: { tags: ["decision"] },
    created_at: isoDaysAgo(1),
    updated_at: isoDaysAgo(1),
  },
  {
    note_id: "c8810d",
    content_key: "pages/capabilities-audit-2541.md",
    front_matter: { tags: ["audit"] },
    created_at: isoDaysAgo(1),
    updated_at: isoDaysAgo(1),
  },
  {
    note_id: "f3d401",
    content_key: "pages/research-modern-screenshot-vs-playwright.md",
    front_matter: { tags: ["research"] },
    created_at: isoDaysAgo(2),
    updated_at: isoDaysAgo(2),
  },
  {
    note_id: "5b2c77",
    content_key: "pages/requirement-client-vs-server-split.md",
    front_matter: { tags: ["requirement"] },
    created_at: isoDaysAgo(2),
    updated_at: isoDaysAgo(2),
  },
];

// --- /api/link/list -> Link[] -------------------------------------------------

export const LINKS_FIXTURE = [
  {
    activity_id: "act-101",
    link_id: "lnk-101",
    url: "https://playwright.dev/docs/screenshots",
    base_url: "https://playwright.dev",
    title: "Playwright: taking screenshots",
    timestamp: NOW - 1 * HOUR,
    download_status: "done",
    source: "fetch",
    summary_content_key: "links/act-101/summary.md",
  },
  {
    activity_id: "act-102",
    link_id: "lnk-102",
    url: "https://recharts.org/en-US/api/PieChart",
    base_url: "https://recharts.org",
    title: "Recharts PieChart API reference",
    timestamp: NOW - 3 * HOUR,
    download_status: "done",
    source: "fetch",
  },
  {
    activity_id: "act-103",
    link_id: "lnk-103",
    url: "https://news.ycombinator.com/item?id=43210000",
    base_url: "https://news.ycombinator.com",
    title: "Show HN: a personal AI agent built on coding agents",
    timestamp: NOW - 6 * HOUR,
    source: "rss",
    source_feed_id: "hn-frontpage",
  },
  {
    activity_id: "act-104",
    link_id: "lnk-104",
    url: "https://docs.anthropic.com/en/docs/claude-code",
    base_url: "https://docs.anthropic.com",
    title: "Claude Code documentation",
    timestamp: NOW - 9 * HOUR,
    download_status: "done",
  },
  {
    activity_id: "act-105",
    link_id: "lnk-105",
    url: "https://tailwindcss.com/docs/theme",
    base_url: "https://tailwindcss.com",
    title: "Tailwind CSS theme configuration",
    timestamp: NOW - 1 * DAY - 2 * HOUR,
    download_status: "done",
    source: "fetch",
    summary_content_key: "links/act-105/summary.md",
  },
  {
    activity_id: "act-106",
    link_id: "lnk-106",
    url: "https://blog.bytebytego.com/p/event-driven-architectures",
    base_url: "https://blog.bytebytego.com",
    title: "Event-driven architectures explained",
    published_at: NOW - 1 * DAY - 5 * HOUR,
    source: "rss",
    source_feed_id: "bytebytego",
  },
  {
    activity_id: "act-107",
    link_id: "lnk-107",
    url: "https://aws.amazon.com/blogs/compute/lambda-response-streaming",
    base_url: "https://aws.amazon.com",
    title: "Introducing AWS Lambda response streaming",
    timestamp: NOW - 1 * DAY - 8 * HOUR,
    download_status: "failed",
  },
  {
    activity_id: "act-108",
    link_id: "lnk-108",
    url: "https://martinfowler.com/articles/patterns-of-distributed-systems",
    base_url: "https://martinfowler.com",
    title: "Patterns of Distributed Systems",
    timestamp: NOW - 2 * DAY - 1 * HOUR,
    source: "rss",
    source_feed_id: "martinfowler",
  },
];

// --- /api/usage/model-daily -> ModelUsageRow[] --------------------------------
// Per-(model, date) usage rows over the last ~11 weeks, driving the bot usage Live
// view (donut + per-day contribution heatmap). A deterministic pseudo-random pattern
// gives weekday-heavy, weekend-light days and the occasional zero day so the heatmap
// reads like a real GitHub contribution graph.
const USAGE_MODELS = [
  { model: "claude-opus-4-8", provider: "anthropic", weight: 1.0 },
  { model: "claude-sonnet-4-6", provider: "anthropic", weight: 0.6 },
  { model: "gpt-5-codex", provider: "openai", weight: 0.45 },
  { model: "claude-haiku-4-5", provider: "anthropic", weight: 0.3 },
  { model: "gemini-2.5-pro", provider: "google", weight: 0.2 },
  { model: "sonar", provider: "perplexity", weight: 0.12 },
  { model: "deepseek-v3", provider: "deepseek", weight: 0.06 },
];

export const MODEL_DAILY_FIXTURE = (() => {
  const rows: Record<string, unknown>[] = [];
  for (let d = 75; d >= 0; d--) {
    const date = ymdDaysAgo(d);
    const dow = new Date(NOW - d * DAY).getDay(); // 0=Sun..6=Sat
    // Deterministic 0..1 intensity for the day; weekends and a few scattered days dip to 0.
    const wave = (Math.sin(d * 1.7) + 1) / 2; // 0..1
    const weekend = dow === 0 || dow === 6 ? 0.25 : 1;
    const idle = d % 9 === 4 ? 0 : 1; // occasional zero day
    const dayScale = wave * weekend * idle;
    if (dayScale <= 0.02) continue; // no usage that day
    for (const m of USAGE_MODELS) {
      const reqs = Math.round(dayScale * m.weight * 40);
      if (reqs <= 0) continue;
      const input = reqs * 1800;
      const output = reqs * 900;
      const cacheCreate = reqs * 600;
      const cacheRead = reqs * 5200;
      const all = input + output + cacheCreate + cacheRead;
      rows.push({
        usage_date: date,
        source: "crs",
        provider: m.provider,
        model: m.model,
        scope: "user",
        scope_id: "u-demo",
        scope_name: "demo",
        input_tokens: input,
        output_tokens: output,
        cache_create_tokens: cacheCreate,
        cache_read_tokens: cacheRead,
        all_tokens: all,
        requests: reqs,
        cost: Number((all / 1e6 * 4.2).toFixed(2)),
        cost_basis: "list",
        synced_at: isoDaysAgo(0, -10 * MIN),
      });
    }
  }
  return rows;
})();

// --- /api/usage/daily-totals -> per-day totals --------------------------------
// Per-day tokens/cost/requests summed across all models, driving the contribution
// heatmap independently of the Live time filter. Derived from MODEL_DAILY_FIXTURE
// (the same seeded days) so the donut/table and heatmap stay visually consistent.
export const DAILY_TOTALS_FIXTURE = (() => {
  const byDay = new Map<string, { usage_date: string; all_tokens: number; cost: number; requests: number }>();
  for (const r of MODEL_DAILY_FIXTURE) {
    const date = r.usage_date as string;
    const agg = byDay.get(date) || { usage_date: date, all_tokens: 0, cost: 0, requests: 0 };
    agg.all_tokens += (r.all_tokens as number) || 0;
    agg.cost += (r.cost as number) || 0;
    agg.requests += (r.requests as number) || 0;
    byDay.set(date, agg);
  }
  return [...byDay.values()].sort((a, b) => a.usage_date.localeCompare(b.usage_date));
})();

// --- /api/usage/limits -> live account-wide subscription windows --------------
export const USAGE_LIMITS_FIXTURE = {
  timezone: "Asia/Shanghai",
  providers: [
    { backend: "claude_code", provider: "anthropic", account_id: "claude-demo", account_name: "Claude subscription", observed_at: isoDaysAgo(0, -34 * MIN), source: "anthropic_oauth_usage", availability: "available", freshness: "fresh", error: null, windows: { five_hour: { used_percent: 42, remaining_percent: 58, reset_at: isoDaysAgo(0, 2 * HOUR + 12 * MIN) }, one_week: { used_percent: 18, remaining_percent: 82, reset_at: isoDaysAgo(-2, 17 * HOUR) } }, extra_windows: {} },
    { backend: "codex", provider: "openai", account_id: "codex-demo", account_name: "OpenAI subscription", observed_at: isoDaysAgo(0, -7 * MIN), source: "codex_rate_limit_headers", availability: "available", freshness: "stale", error: null, windows: { five_hour: { used_percent: 67, remaining_percent: 33, reset_at: isoDaysAgo(0, 46 * MIN) }, one_week: { used_percent: 84, remaining_percent: 16, reset_at: null } }, extra_windows: {} },
    { backend: "grok", provider: "xai", account_id: "grok-demo", account_name: "Grok subscription", observed_at: isoDaysAgo(0, -12 * MIN), source: "xai_billing_credits", availability: "available", freshness: "fresh", error: null, windows: { billing_period: { used_percent: 54, remaining_percent: 46, reset_at: isoDaysAgo(-9, 0), extra: { monthlyLimit: 40 } } }, extra_windows: {} },
  ],
  errors: [{ origin: "https://relay-backup.example", error: "timeout" }],
};

export const USAGE_LIMITS_UNAVAILABLE_FIXTURE = {
  timezone: "Asia/Shanghai",
  providers: [
    { backend: "claude_code", provider: "anthropic", account_id: "claude-expired", account_name: "Claude subscription", observed_at: null, source: "claude_tui_usage", availability: "reauth_required", freshness: "unavailable", error: "reauth_required", windows: { five_hour: null, one_week: null }, extra_windows: {} },
    { backend: "codex", provider: "openai", account_id: "codex-pool", account_name: "Shared relay pool", observed_at: null, source: "codex_rate_limit_headers", availability: "unavailable", freshness: "unavailable", error: "bad_payload", windows: { five_hour: null, one_week: null }, extra_windows: {} },
    { backend: "grok", provider: "xai", account_id: "grok-demo", account_name: "Grok subscription", observed_at: null, source: "xai_billing_credits", availability: "unavailable", freshness: "unavailable", error: "not_logged_in", windows: { billing_period: null }, extra_windows: {} },
  ],
  errors: [],
};

// --- /api/tag/list -> TagVocabularyEntry[] ------------------------------------

export const TAG_VOCAB_FIXTURE = [
  { tag: "design", count: 6 },
  { tag: "knowledge/technical/web", count: 4 },
  { tag: "life/travel", count: 3 },
  { tag: "lifelog/cli", count: 7 },
  { tag: "meta/decisions", count: 2 },
  { tag: "meta/reviews", count: 1 },
  { tag: "meta/systems", count: 3 },
  { tag: "ui", count: 3 },
  { tag: "work/log", count: 5 },
  { tag: "work/personal/y-agent", count: 37 },
  { tag: "work/personal/y-blog", count: 8 },
];

// --- /api/tag?tag=work/personal/y-agent -> mixed-type drill-down --------------

export const TAG_RESULTS_FIXTURE = {
  todo: [
    { id: "2854", title: "Frontend tag management feature" },
    { id: "2838", title: "Cross-entity tag system" },
  ],
  note: [
    { id: "n-plan-2854", title: "pages/plan-2854-tag-management-ui.md" },
    { id: "n-tag-system", title: "pages/tag-system.md" },
  ],
  entity: [
    { id: "e-y-agent", title: "y-agent" },
  ],
  chat: [
    { id: "b92b8112", title: "design tag panel" },
  ],
  calendar_event: [
    { id: "ev-1", title: "y-agent tag system review" },
  ],
  reminder: [
    { id: "rem-1", title: "Follow up on tag merge UX" },
  ],
  routine: [
    { id: "rt-1", title: "Weekly y-agent changelog" },
  ],
  link: [
    { id: "lk-1", title: "TailwindCSS v4 docs" },
  ],
  email: [
    { id: "em-1", title: "Re: tag system design review" },
  ],
  rss_feed: [
    { id: "rf-1", title: "y-agent releases" },
  ],
};

// --- /showcase chat panel: snapshot raw messages ------------------------------
// Rendered by ChatView in mode="snapshot" (the same read-only path PublicTraceApp
// uses to project mock chat messages). Snapshot mode short-circuits every
// /api/chat/* request and renders these raw messages directly, so the chat panel
// needs NO entry in installFetchMock below. The shape matches a real chat
// snapshot row: a user prompt, an assistant turn with prose + a real tool call,
// then a final assistant message with prose + an inline rendered artifact
// (mermaid) — exercising the chat surface end to end.

const CHAT_VEGA_SPEC = JSON.stringify(
  {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    description: "Mock fixture rows per showcased panel.",
    width: 360,
    height: 200,
    background: "transparent",
    data: {
      values: [
        { panel: "todo", rows: 10 },
        { panel: "trace", rows: 5 },
        { panel: "note", rows: 5 },
        { panel: "link", rows: 8 },
        { panel: "finance", rows: 7 },
        { panel: "chat", rows: 4 },
      ],
    },
    mark: { type: "bar", cornerRadiusEnd: 3 },
    encoding: {
      x: { field: "panel", type: "nominal", sort: null, axis: { labelAngle: 0, title: null } },
      y: { field: "rows", type: "quantitative", title: "fixture rows" },
    },
  },
);

const CHAT_ASSISTANT_FINAL = [
  "Concretely, each showcased panel is backed by a small seeded fixture — here's the row count per panel:",
  "",
  "```vega-lite",
  CHAT_VEGA_SPEC,
  "```",
  "",
  "Every panel runs its **real** `authFetch` path against that seeded JSON, so no component is reimplemented and the screenshots match production exactly.",
].join("\n");

const CHAT_TOOL_RESULT = [
  "export function installFetchMock(): void {",
  "  if (installed) return;",
  "  installed = true;",
  "  const realFetch = window.fetch.bind(window);",
  "  window.fetch = (input, init) => {",
  "    const fixture = matchFixture(urlOf(input));",
  "    if (fixture !== undefined) return Promise.resolve(jsonResponse(fixture));",
  "    return realFetch(input, init);",
  "  };",
  "}",
].join("\n");

export const CHAT_MESSAGES_FIXTURE = [
  {
    role: "user",
    content:
      "How does the /showcase route feed mock data into the real panels without touching the production components?",
    timestamp: isoDaysAgo(0, -30 * MIN),
  },
  {
    role: "assistant",
    content:
      "Good question. Before any panel mounts, the route overrides `window.fetch` with a URL-keyed mock. Every panel's real `authFetch` → `jsonFetcher` path then resolves to seeded fixtures instead of the backend. Let me pull up the fixture module to show the wiring.",
    tool_calls: [
      {
        id: "call_showcase_1",
        function: {
          name: "file_read",
          arguments: JSON.stringify({ path: "web/src/showcase/fixtures.ts", offset: 482, limit: 12 }),
        },
      },
    ],
    timestamp: isoDaysAgo(0, -29 * MIN),
  },
  {
    role: "tool",
    tool_call_id: "call_showcase_1",
    tool: "file_read",
    content: CHAT_TOOL_RESULT,
    timestamp: isoDaysAgo(0, -29 * MIN),
  },
  {
    role: "assistant",
    content: CHAT_ASSISTANT_FINAL,
    timestamp: isoDaysAgo(0, -28 * MIN),
  },
];

// --- fetch mock ---------------------------------------------------------------

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

// Route a request URL to its fixture. Returns `undefined` when no fixture
// matches (the real fetch is used as a fallback, e.g. the warm-up health ping).
function matchFixture(rawUrl: string): unknown | undefined {
  let pathname: string;
  let search: URLSearchParams;
  try {
    const u = new URL(rawUrl, window.location.origin);
    pathname = u.pathname;
    search = u.searchParams;
  } catch {
    return undefined;
  }

  if (pathname === "/api/chat/messages/snapshot" && search.get("chat_id") === "showcase-chat-running") {
    return { messages: CHAT_MESSAGES_FIXTURE, running: true };
  }
  if (pathname === "/api/todo/list") return TODOS_FIXTURE;
  if (pathname === "/api/trace/chats") return TRACE_CHATS_FIXTURE;
  if (pathname === "/api/trace/share/mine") return null; // no existing share
  if (pathname === "/api/note/list") return NOTES_FIXTURE;
  if (pathname === "/api/link/list") return LINKS_FIXTURE;
  if (pathname === "/api/tag/list") return TAG_VOCAB_FIXTURE;
  if (pathname === "/api/tag") return TAG_RESULTS_FIXTURE;
  if (pathname === "/api/file/list") {
    return {
      path: search.get("path") || "/workspace/project",
      entries: [
        { name: "README.md", type: "file" },
        { name: "src", type: "directory" },
      ],
    };
  }
  if (pathname === "/api/file/read") {
    return {
      content: [
        "---",
        "title: Theme Integration QA",
        "status: active",
        "---",
        "",
        "# Theme Integration QA",
        "",
        "The final gate checks every main screen in all four themes.",
        "",
        "## Screenshot matrix",
        "",
        "- Chat, todo, file viewer, finance, trace, settings, and landing",
        "- Light, dark, Solarized Dark, and Solarized Light",
        "- No hardcoded render-path colors or stuck-dark regions",
        "",
        "> Theme changes must apply instantly through the Settings picker.",
        "",
        "```ts",
        "applyTheme(theme);",
        "document.documentElement.dataset.theme = theme;",
        "```",
      ].join("\n"),
    };
  }
  if (pathname === "/api/usage/model-daily") return MODEL_DAILY_FIXTURE;
  if (pathname === "/api/usage/daily-totals") return DAILY_TOTALS_FIXTURE;
  if (pathname === "/api/usage/limits") return new URLSearchParams(window.location.search).get("limits") === "unavailable" ? USAGE_LIMITS_UNAVAILABLE_FIXTURE : USAGE_LIMITS_FIXTURE;
  if (pathname === "/api/chat/bot-options") return []; // usage view ignores the config table

  return undefined;
}

let installed = false;

// Override the global fetch so every self-fetching panel renders against the
// fixtures above through its real authFetch/jsonFetcher path. Idempotent.
export function installFetchMock(): void {
  if (installed) return;
  installed = true;
  const realFetch = window.fetch.bind(window);
  window.fetch = (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url =
      typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const fixture = matchFixture(url);
    if (fixture !== undefined) return Promise.resolve(jsonResponse(fixture));
    return realFetch(input as any, init);
  };
}
