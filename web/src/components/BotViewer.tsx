import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell,
} from "recharts";
import { API, authFetch, jsonFetcher as fetcher } from "../api";
import { ListEmpty, ListError, ListLoading } from "./ListStates";
import {
  BotForm,
  type BotConfig,
  type BotFormState,
  apiJson,
  emptyForm,
  fmtPrice,
  formFromBot,
} from "./BotList";

type SortKey = "name" | "backend" | "model" | "type" | "tier" | "route_weight" | "price_input" | "price_output";
type SortDir = "asc" | "desc";

type TypeFilter = "all" | "agent" | "model";

type ViewMode = "config" | "usage";
// Usage sub-view: Live = today's per-model snapshot; Over-time = historical chart + table.
type UsageMode = "live" | "over-time";
type Granularity = "daily" | "weekly" | "monthly";
type UsageMetric = "tokens" | "cost" | "requests";

const SORT_KEY_STORAGE_KEY = "botViewSortKey";
const SORT_DIR_STORAGE_KEY = "botViewSortDir";
const VIEW_STORAGE_KEY = "botView";
const TYPE_FILTER_STORAGE_KEY = "botViewTypeFilter";
const USAGE_MODE_STORAGE_KEY = "botUsageMode";
const USAGE_GRANULARITY_STORAGE_KEY = "botUsageGranularity";
// Free-text time range (mirrors finance Income tab). Live and Over-time each keep their
// own independent value: Live mostly views today, Over-time mostly views week/month.
const USAGE_LIVE_TIME_STORAGE_KEY = "botUsageLiveTime";
const USAGE_OVER_TIME_STORAGE_KEY = "botUsageOverTime";

// One per-model daily usage row from GET /api/usage/model-daily (source=crs).
interface ModelUsageRow {
  usage_date: string;
  source: string;
  provider: string;
  model: string;
  scope: string;
  scope_id: string;
  scope_name: string;
  input_tokens: number;
  output_tokens: number;
  cache_create_tokens: number;
  cache_read_tokens: number;
  all_tokens: number;
  requests: number;
  cost: number;
  cost_basis: string;
  synced_at: string;
}

// One per-day usage total from GET /api/usage/daily-totals: tokens/cost/requests
// summed across all models, over the heatmap window (decoupled from the Live filter).
interface DailyTotal {
  usage_date: string;
  all_tokens: number;
  cost: number;
  requests: number;
}

type LimitFreshness = "fresh" | "stale" | "unavailable";

interface UsageLimitWindow {
  used_percent: number | null;
  remaining_percent: number | null;
  reset_at: string | null;
}

interface UsageLimitProvider {
  backend: string | null;
  provider: string | null;
  account_id: string | null;
  account_name: string | null;
  observed_at: string | null;
  source: string | null;
  availability: string;
  freshness: LimitFreshness;
  error: string | null;
  windows: Record<"five_hour" | "one_week", UsageLimitWindow | null>;
  extra_windows: Record<string, UsageLimitWindow | null>;
}

interface UsageLimitsResponse {
  providers: UsageLimitProvider[];
  errors: Array<{ origin: string; error: string }>;
  timezone?: string;
}

export const USAGE_LIMIT_POLL_INTERVAL = 60_000;

// Aggregate of one model's rows across the selected window.
interface ModelUsageAgg {
  model: string;
  provider: string;
  input_tokens: number;
  output_tokens: number;
  cache_create_tokens: number;
  cache_read_tokens: number;
  all_tokens: number;
  requests: number;
  cost: number;
  from_date: string;
  to_date: string;
}

function fmtNum(n: number): string {
  return (n || 0).toLocaleString();
}

function fmtCost(c: number): string {
  return `$${(c || 0).toFixed(2)}`;
}

function formatRelativeTime(timestamp: string | null): string {
  if (!timestamp) return "unavailable";
  const milliseconds = new Date(timestamp).getTime() - Date.now();
  if (!Number.isFinite(milliseconds)) return "unavailable";
  const absoluteSeconds = Math.abs(Math.round(milliseconds / 1000));
  const prefix = milliseconds < 0 ? "" : "in ";
  const suffix = milliseconds < 0 ? " ago" : "";
  if (absoluteSeconds < 60) return `${prefix}${absoluteSeconds}s${suffix}`;
  const minutes = Math.round(absoluteSeconds / 60);
  if (minutes < 60) return `${prefix}${minutes}m${suffix}`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  if (hours < 24) return `${prefix}${hours}h${remainingMinutes ? ` ${remainingMinutes}m` : ""}${suffix}`;
  const days = Math.floor(hours / 24);
  const remainingHours = hours % 24;
  return `${prefix}${days}d${remainingHours ? ` ${remainingHours}h` : ""}${suffix}`;
}

export function formatResetTime(timestamp: string | null, timezone?: string): string {
  if (!timestamp || !Number.isFinite(new Date(timestamp).getTime())) return "reset unavailable";
  try {
    return new Intl.DateTimeFormat(undefined, {
      weekday: "short",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: timezone,
    }).format(new Date(timestamp));
  } catch {
    return new Intl.DateTimeFormat(undefined, {
      weekday: "short",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(timestamp));
  }
}

function providerLabel(provider: UsageLimitProvider): string {
  return provider.backend === "codex" || provider.provider === "openai" ? "GPT / Codex" : "Claude";
}

function providerSource(source: string | null): string {
  if (source === "anthropic_oauth_usage") return "Anthropic OAuth";
  if (source === "codex_rate_limit_headers") return "Codex headers";
  return source ? source.replace(/_/g, " ") : "relay status";
}

// OpenAI's usage schema has no cache-write metric (cache writes are billed/reported as
// plain input_tokens; only cache hits are reported). cache_create is structurally always
// 0 for provider=openai rows, so render "(n/a)" instead of a misleading 0; parenthesized
// so it doesn't run into the "/<cache_read>" value that follows (e.g. "(n/a)/2.5M").
function fmtCacheCreate(n: number, provider: string, fmt: (n: number) => string): string {
  return provider === "openai" ? "(n/a)" : fmt(n);
}

// Compact token-count formatting by magnitude with 1 decimal: 1.2B / 100.1M / 101.2K.
// Keeps small counts as plain integers so big numbers don't overflow chart/table cells.
function fmtCompact(n: number): string {
  const v = n || 0;
  const abs = Math.abs(v);
  if (abs >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return fmtNum(v);
}

function localDateStr(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

// --- Over-time helpers (local copies; FinanceViewer keeps the originals private) ---

// Solarized dark palette (local copy of FinanceViewer's SOL).
const SOL = {
  base03: "#002b36",
  base02: "#073642",
  base01: "#586e75",
  base0: "#839496",
  base1: "#93a1a1",
  blue: "#268bd2",
  red: "#dc322f",
  green: "#859900",
  yellow: "#b58900",
  cyan: "#2aa198",
  magenta: "#d33682",
  violet: "#6c71c4",
  orange: "#cb4b16",
};

// One color per stacked model series (+ Other).
const MODEL_COLORS = [SOL.blue, SOL.green, SOL.cyan, SOL.magenta, SOL.violet, SOL.orange, SOL.yellow, SOL.red];

// Local copy of FinanceViewer.formatPeriodLabel: YYYY-MM-DD -> "Mon D, YYYY", YYYY-MM -> "Mon YYYY".
function formatPeriodLabel(period: string, fullYear = true): string {
  const [year, month, day] = period.split("-");
  if (!month) return year;
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const monthLabel = months[parseInt(month, 10) - 1];
  if (day) return fullYear ? `${monthLabel} ${parseInt(day, 10)}, ${year}` : `${monthLabel} ${parseInt(day, 10)} '${year.slice(2)}`;
  return `${monthLabel} ${fullYear ? year : year.slice(2)}`;
}

// Monday (ISO week start) of the week containing dateStr, as YYYY-MM-DD.
function mondayOf(dateStr: string): string {
  const d = new Date(`${dateStr}T00:00:00`);
  const day = d.getDay(); // 0=Sun..6=Sat
  d.setDate(d.getDate() + (day === 0 ? -6 : 1 - day));
  return localDateStr(d);
}

// Bucket a daily row's usage_date into a period key for the granularity.
function periodKeyFor(usageDate: string, granularity: Granularity): string {
  if (granularity === "weekly") return mondayOf(usageDate);
  if (granularity === "monthly") return usageDate.slice(0, 7);
  return usageDate; // daily
}

// Selected metric's value for a single row (per-model daily row or per-day total —
// both carry all_tokens/cost/requests, so this reads the structural subset).
function metricValue(row: { all_tokens: number; cost: number; requests: number }, metric: UsageMetric): number {
  if (metric === "cost") return row.cost || 0;
  if (metric === "requests") return row.requests || 0;
  return row.all_tokens || 0; // tokens
}

function formatMetric(v: number, metric: UsageMetric): string {
  if (metric === "cost") return fmtCost(v);
  if (metric === "tokens") return fmtCompact(v); // big token counts -> compact
  return fmtNum(v); // requests are small ints
}

// Selected metric's value for an aggregated (multi-day summed) model row.
function aggMetricValue(a: ModelUsageAgg, metric: UsageMetric): number {
  if (metric === "cost") return a.cost || 0;
  if (metric === "requests") return a.requests || 0;
  return a.all_tokens || 0; // tokens
}

// Sum per-model rows (multi-day windows return one row per (model, date)).
function aggregateByModel(rows: ModelUsageRow[]): ModelUsageAgg[] {
  const map = new Map<string, ModelUsageAgg>();
  for (const r of rows) {
    const existing = map.get(r.model);
    if (existing) {
      existing.input_tokens += r.input_tokens;
      existing.output_tokens += r.output_tokens;
      existing.cache_create_tokens += r.cache_create_tokens;
      existing.cache_read_tokens += r.cache_read_tokens;
      existing.all_tokens += r.all_tokens;
      existing.requests += r.requests;
      existing.cost += r.cost;
      if (r.usage_date < existing.from_date) existing.from_date = r.usage_date;
      if (r.usage_date > existing.to_date) existing.to_date = r.usage_date;
    } else {
      map.set(r.model, {
        model: r.model,
        provider: r.provider,
        input_tokens: r.input_tokens,
        output_tokens: r.output_tokens,
        cache_create_tokens: r.cache_create_tokens,
        cache_read_tokens: r.cache_read_tokens,
        all_tokens: r.all_tokens,
        requests: r.requests,
        cost: r.cost,
        from_date: r.usage_date,
        to_date: r.usage_date,
      });
    }
  }
  return [...map.values()].sort((a, b) => b.all_tokens - a.all_tokens);
}

// --- Daily contribution heatmap (GitHub-style) ---

const MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// Cell geometry (px). Columns are weeks; each column is Sun(top)->Sat(bottom).
const HEATMAP_CELL = 11;
const HEATMAP_GAP = 3;
const HEATMAP_WEEKDAY_W = 24; // left gutter for the Mon/Wed/Fri labels
// Upscale cap when filling a wide panel: cells/gaps are solid divs so they stay crisp
// when scaled up, but cap the factor so an ultra-wide panel doesn't blow them up
// grotesquely (2.4x -> ~26px cells, still a tidy contribution graph).
const HEATMAP_MAX_SCALE = 2.4;

// Sequential green buckets (Solarized green), GitHub contribution style: index 0 = no
// usage that day, 1..4 = increasing intensity. Rendered over the dark base03 background.
const HEATMAP_COLORS = [
  SOL.base02,
  "rgba(133, 153, 0, 0.30)",
  "rgba(133, 153, 0, 0.55)",
  "rgba(133, 153, 0, 0.78)",
  "rgba(133, 153, 0, 1)",
];

// Bucket a day's value into 0..4 by its share of the window's busiest day (0 -> empty).
function heatmapLevel(value: number, max: number): number {
  if (value <= 0 || max <= 0) return 0;
  const r = value / max;
  if (r > 0.75) return 4;
  if (r > 0.5) return 3;
  if (r > 0.25) return 2;
  return 1;
}

interface HeatCell { date: string; value: number; }

// Build a GitHub-style week grid (Sun(top)->Sat(bottom) columns) whose span is fixed by
// the active time filter, not by which days have data: a bare 4-digit year (e.g. "2024")
// spans that whole calendar year (Jan 1 -> Dec 31), anything else spans the month-aligned
// past 12 months. `dailyTotals` only supplies values, so every day in the window renders
// and days with no usage fall to value 0 (empty bucket).
function buildHeatmapWeeks(dailyTotals: Map<string, number>, time: string): { weeks: HeatCell[][]; max: number } {
  const year = /^\d{4}$/.test(time.trim()) ? parseInt(time.trim(), 10) : null;
  let start: Date;
  let end: Date;
  if (year !== null) {
    start = new Date(year, 0, 1); // Jan 1
    end = new Date(year, 11, 31); // Dec 31
  } else {
    // Month-aligned past-12-month window: start at the 1st of the month 11 months back
    // (12 whole months incl. the current one) so the leftmost month is a full month, not
    // a few-day sliver. The grid then pads out to whole Sun..Sat weeks below.
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    end = today;
    start = new Date(today.getFullYear(), today.getMonth() - 11, 1);
  }
  start.setDate(start.getDate() - start.getDay()); // back to Sunday of its week
  end.setDate(end.getDate() + (6 - end.getDay())); // forward to Saturday of its week
  const weeks: HeatCell[][] = [];
  let max = 0;
  let col: HeatCell[] = [];
  for (const d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
    const ds = localDateStr(d);
    const value = dailyTotals.get(ds) || 0;
    if (value > max) max = value;
    col.push({ date: ds, value });
    if (d.getDay() === 6) { weeks.push(col); col = []; }
  }
  if (col.length) weeks.push(col);
  return { weeks, max };
}

function botValue(bot: BotConfig, key: SortKey): string | number | null {
  switch (key) {
    case "name": return bot.name;
    case "backend": return bot.backend || "";
    case "model": return bot.model || "";
    case "type": return bot.type || "agent";
    case "tier": return bot.tier || "";
    case "route_weight": return bot.route_weight ?? null;
    case "price_input": return bot.price_input ?? null;
    case "price_output": return bot.price_output ?? null;
  }
}

const COLUMNS: { key: SortKey; label: string; align?: "right" }[] = [
  { key: "name", label: "Name" },
  { key: "backend", label: "Backend" },
  { key: "model", label: "Model" },
  { key: "type", label: "Type" },
  { key: "tier", label: "Tier" },
  { key: "route_weight", label: "Weight", align: "right" },
  { key: "price_input", label: "In/1M", align: "right" },
  { key: "price_output", label: "Out/1M", align: "right" },
];

function loadSortKey(): SortKey {
  const saved = localStorage.getItem(SORT_KEY_STORAGE_KEY);
  return COLUMNS.some((col) => col.key === saved) ? (saved as SortKey) : "name";
}

function loadSortDir(): SortDir {
  const saved = localStorage.getItem(SORT_DIR_STORAGE_KEY);
  return saved === "desc" ? "desc" : "asc";
}

function loadTypeFilter(): TypeFilter {
  const saved = localStorage.getItem(TYPE_FILTER_STORAGE_KEY);
  return saved === "agent" || saved === "model" ? saved : "all";
}

const COL_COUNT = COLUMNS.length + 1; // +1 for "On" column

const inputClass = "w-full bg-sol-base03 text-sol-base1 border border-sol-base01/30 rounded px-2 py-1 text-xs outline-none focus:border-sol-blue";

// Inline detail/edit panel shown below an expanded table row.
function BotDetail({ bot, onClose, onSaved }: { bot: BotConfig; onClose: () => void; onSaved: () => void }) {
  const { data: detail } = useSWR<BotConfig>(
    `${API}/api/bot/config?name=${encodeURIComponent(bot.name)}`,
    fetcher,
  );
  const full = detail || bot;

  // Today's per-model usage; SWR dedupes this key across all expanded rows.
  const { data: usageRows } = useSWR<ModelUsageRow[]>(
    full.model ? `${API}/api/usage/model-daily` : null,
    fetcher,
  );
  const modelUsage = useMemo(
    () => (usageRows || []).filter((r) => r.model === full.model),
    [usageRows, full.model],
  );

  const [name] = useState(full.name);
  const [description, setDescription] = useState(full.description || "");
  const [backend, setBackend] = useState(full.backend || "");
  const [model, setModel] = useState(full.model || "");
  const [type, setType] = useState(full.type || "agent");
  const [tier, setTier] = useState(full.tier || "");
  const [baseUrl, setBaseUrl] = useState(full.base_url || "");
  const [apiKey, setApiKey] = useState("");
  const [maxTokens, setMaxTokens] = useState(full.max_tokens ? String(full.max_tokens) : "");
  const [customApiPath, setCustomApiPath] = useState(full.custom_api_path || "");
  const [routeWeight, setRouteWeight] = useState(full.route_weight ? String(full.route_weight) : "");
  const [refBotName, setRefBotName] = useState(full.ref_bot_name || "");
  const [saving, setSaving] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const dirty =
    description !== (full.description || "") ||
    backend !== (full.backend || "") ||
    model !== (full.model || "") ||
    type !== (full.type || "agent") ||
    tier !== (full.tier || "") ||
    baseUrl !== (full.base_url || "") ||
    apiKey !== "" ||
    maxTokens !== (full.max_tokens ? String(full.max_tokens) : "") ||
    customApiPath !== (full.custom_api_path || "") ||
    routeWeight !== (full.route_weight ? String(full.route_weight) : "") ||
    refBotName !== (full.ref_bot_name || "");

  const handleSave = async () => {
    const body: Record<string, unknown> = { name };
    if (description !== (full.description || "")) body.description = description || null;
    if (backend !== (full.backend || "")) body.backend = backend || null;
    if (model !== (full.model || "")) body.model = model || null;
    if (type !== (full.type || "agent")) body.type = type || null;
    if (tier !== (full.tier || "")) body.tier = tier || null;
    if (baseUrl !== (full.base_url || "")) body.base_url = baseUrl || null;
    if (apiKey) body.api_key = apiKey;
    if (maxTokens !== (full.max_tokens ? String(full.max_tokens) : "")) body.max_tokens = maxTokens ? Number(maxTokens) : null;
    if (customApiPath !== (full.custom_api_path || "")) body.custom_api_path = customApiPath || null;
    if (routeWeight !== (full.route_weight ? String(full.route_weight) : "")) body.route_weight = routeWeight ? Number(routeWeight) : null;
    if (refBotName !== (full.ref_bot_name || "")) body.ref_bot_name = refBotName || null;

    if (Object.keys(body).length <= 1) return; // only name
    setSaving(true);
    try {
      await apiJson("/api/bot/update", body);
      onSaved();
    } catch {
      // error handled by parent SWR
    } finally {
      setSaving(false);
    }
  };

  const toggleEnabled = async () => {
    const action = full.enabled !== false ? "disable" : "enable";
    setToggling(true);
    try { await apiJson(`/api/bot/${action}`, { name }); onSaved(); } catch { /* ignore */ }
    setToggling(false);
  };

  const handleDelete = async () => {
    if (!window.confirm(`Delete bot '${name}'?`)) return;
    setDeleting(true);
    try { await apiJson("/api/bot/delete", { name }); onSaved(); onClose(); } catch { /* ignore */ }
    setDeleting(false);
  };

  return (
    <div className="bg-sol-base02 rounded p-3 border border-sol-base01/20" data-bot-card>
      <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 items-start text-xs">
        <label className="text-sol-base01 pt-1">Name</label>
        <input value={name} disabled className={`${inputClass} opacity-60`} />

        <label className="text-sol-base01 pt-1">Description</label>
        <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} className={`${inputClass} resize-none`} style={{ fieldSizing: "content" } as React.CSSProperties} />

        <label className="text-sol-base01 pt-1">Backend</label>
        <select value={backend} onChange={(e) => setBackend(e.target.value)} className={inputClass}>
          <option value="">(default)</option>
          <option value="codex">codex</option>
          <option value="claude_code">claude_code</option>
          <option value="gemini">gemini</option>
          <option value="grok_build">grok_build</option>
          <option value="pi_cli">pi_cli</option>
          <option value="openai">openai</option>
        </select>

        <label className="text-sol-base01 pt-1">Model</label>
        <input type="text" value={model} onChange={(e) => setModel(e.target.value)} className={inputClass} />

        <label className="text-sol-base01 pt-1">Type</label>
        <select value={type} onChange={(e) => setType(e.target.value)} className={inputClass}>
          <option value="agent">agent</option>
          <option value="model">model</option>
        </select>

        <label className="text-sol-base01 pt-1">Tier</label>
        <input type="text" value={tier} onChange={(e) => setTier(e.target.value)} className={inputClass} />

        <label className="text-sol-base01 pt-1">Base URL</label>
        <input type="text" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} className={inputClass} />

        <label className="text-sol-base01 pt-1">API Key</label>
        <div className="flex flex-col gap-1">
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            autoComplete="new-password"
            placeholder={full.has_api_key ? "Stored. Leave blank to keep." : "Not set"}
            className={inputClass}
          />
          {full.api_key_masked && !apiKey && (
            <span className="text-[0.65rem] text-sol-base01/70 font-mono">Current: {full.api_key_masked}</span>
          )}
        </div>

        <label className="text-sol-base01 pt-1">Max Tokens</label>
        <input type="number" min="1" value={maxTokens} onChange={(e) => setMaxTokens(e.target.value)} className={inputClass} />

        <label className="text-sol-base01 pt-1">API Path</label>
        <input type="text" value={customApiPath} onChange={(e) => setCustomApiPath(e.target.value)} placeholder="/chat/completions" className={inputClass} />

        <label className="text-sol-base01 pt-1">Weight</label>
        <input type="number" step="any" value={routeWeight} onChange={(e) => setRouteWeight(e.target.value)} className={inputClass} />

        <label className="text-sol-base01 pt-1">Ref Bot Name</label>
        <input type="text" value={refBotName} onChange={(e) => setRefBotName(e.target.value)} placeholder="codex" className={inputClass} />

        <label className="text-sol-base01 pt-1">Enabled</label>
        <div className="flex items-center gap-2">
          <button
            onClick={toggleEnabled}
            disabled={toggling || name === "default"}
            className={`px-2 py-0.5 rounded text-xs cursor-pointer border ${full.enabled !== false ? "bg-sol-green/20 text-sol-green border-sol-green/30" : "bg-sol-red/20 text-sol-red border-sol-red/30"} ${name === "default" ? "opacity-50 cursor-not-allowed" : "hover:opacity-80"}`}
          >
            {toggling ? "..." : full.enabled !== false ? "Enabled" : "Disabled"}
          </button>
          {name !== "default" && (
            <button
              onClick={handleDelete}
              disabled={deleting}
              className="px-2 py-0.5 rounded text-xs cursor-pointer bg-sol-red/15 text-sol-red border border-sol-red/30 hover:bg-sol-red/25 disabled:opacity-50"
            >
              {deleting ? "..." : "Delete"}
            </button>
          )}
        </div>
      </div>

      {full.model && (
        <div className="mt-3 pt-2 border-t border-sol-base01/20">
          <div className="text-[0.65rem] text-sol-base01 uppercase tracking-wide mb-1">
            Model usage (today) · <span className="font-mono normal-case">{full.model}</span>
          </div>
          {modelUsage.length === 0 ? (
            <div className="text-xs text-sol-base01/70 italic">No usage recorded for this model today</div>
          ) : (
            modelUsage.map((u) => (
              <div key={`${u.model}-${u.usage_date}`} className="text-xs text-sol-base0 flex flex-wrap gap-x-4 gap-y-1 tabular-nums">
                <span>Requests: {fmtNum(u.requests)}</span>
                <span>Total: {fmtNum(u.all_tokens)} tok</span>
                <span>In: {fmtNum(u.input_tokens)}</span>
                <span>Out: {fmtNum(u.output_tokens)}</span>
                <span>Cache: {fmtCacheCreate(u.cache_create_tokens, u.provider, fmtNum)}/{fmtNum(u.cache_read_tokens)}</span>
                <span>Cost: {fmtCost(u.cost)}</span>
              </div>
            ))
          )}
        </div>
      )}

      {dirty && (
        <div className="mt-2 flex justify-end">
          <button onClick={handleSave} disabled={saving} className="px-3 py-1 rounded text-xs bg-sol-blue text-sol-base03 hover:opacity-90 cursor-pointer disabled:opacity-50">
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      )}
    </div>
  );
}

// Top-7 models by total metric across the range + "Other" (max-significance ordering,
// mirroring FinanceViewer.buildPositionSeries).
function buildModelSeries(rows: ModelUsageRow[], metric: UsageMetric): string[] {
  const totals = new Map<string, number>();
  for (const r of rows) totals.set(r.model, (totals.get(r.model) || 0) + metricValue(r, metric));
  const ordered = [...totals.entries()].filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  const top = ordered.slice(0, 7).map(([model]) => model);
  const rest = ordered.slice(7);
  return rest.length ? [...top, "Other"] : top;
}

// Sorted unique period keys present in the rows for the granularity.
function buildPeriods(rows: ModelUsageRow[], granularity: Granularity): string[] {
  const set = new Set<string>();
  for (const r of rows) set.add(periodKeyFor(r.usage_date, granularity));
  return [...set].sort();
}

// period -> model -> summed metric value.
function bucketByPeriodModel(rows: ModelUsageRow[], granularity: Granularity, metric: UsageMetric): Map<string, Map<string, number>> {
  const byPeriod = new Map<string, Map<string, number>>();
  for (const r of rows) {
    const pk = periodKeyFor(r.usage_date, granularity);
    let models = byPeriod.get(pk);
    if (!models) { models = new Map(); byPeriod.set(pk, models); }
    models.set(r.model, (models.get(r.model) || 0) + metricValue(r, metric));
  }
  return byPeriod;
}

// One chart object per period: { period, rawPeriod, <model>: value, …, Other, Total }.
function usageChartRows(byPeriod: Map<string, Map<string, number>>, models: string[], periods: string[]) {
  const named = new Set(models.filter((m) => m !== "Other"));
  return periods.map((pk) => {
    const modelMap = byPeriod.get(pk) || new Map<string, number>();
    const row: Record<string, string | number> = { period: formatPeriodLabel(pk), rawPeriod: pk };
    let total = 0;
    for (const v of modelMap.values()) total += v;
    for (const model of models) {
      if (model === "Other") continue;
      row[model] = modelMap.get(model) || 0;
    }
    if (models.includes("Other")) {
      let other = 0;
      for (const [model, v] of modelMap) if (!named.has(model)) other += v;
      row.Other = other;
    }
    row.Total = total;
    return row;
  });
}

// One table row per model (top-7 + Other): per-period values + range-sum total.
function usageTableRows(byPeriod: Map<string, Map<string, number>>, models: string[], periods: string[]) {
  const named = new Set(models.filter((m) => m !== "Other"));
  return models.map((model) => {
    const values: Record<string, number> = {};
    let sum = 0;
    for (const pk of periods) {
      const modelMap = byPeriod.get(pk) || new Map<string, number>();
      let v = 0;
      if (model === "Other") {
        for (const [mm, mv] of modelMap) if (!named.has(mm)) v += mv;
      } else {
        v = modelMap.get(model) || 0;
      }
      values[pk] = v;
      sum += v;
    }
    return { model, values, sum };
  });
}

// Stacked-bar tooltip (local minimal copy of FinanceViewer's ExpensesOverTimeTooltip).
function UsageChartTooltip({ active, payload, label, metric }: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string; payload?: any }>;
  label?: string;
  metric: UsageMetric;
}) {
  if (!active || !payload?.length) return null;
  const rawPeriod = payload[0]?.payload?.rawPeriod;
  const totalValue = Number(payload[0]?.payload?.Total || 0);
  const rows = payload.filter((p) => Number(p.value || 0) > 0).sort((a, b) => Number(b.value || 0) - Number(a.value || 0));
  return (
    <div className="rounded px-2 py-1.5 text-xs" style={{ background: SOL.base02, border: `1px solid ${SOL.base01}` }}>
      <div style={{ color: SOL.base1 }} className="mb-1">{rawPeriod ? formatPeriodLabel(rawPeriod) : label}</div>
      <div className="mb-1 flex items-center gap-2">
        <span className="inline-block w-2 h-2 rounded-full" style={{ background: SOL.base1 }} />
        <span style={{ color: SOL.base1, fontWeight: 500 }}>Total: {formatMetric(totalValue, metric)}</span>
      </div>
      {rows.map((p, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="inline-block w-2 h-2 rounded-full" style={{ background: p.color }} />
          <span style={{ color: SOL.base0 }}>{p.name}: {formatMetric(p.value, metric)}</span>
        </div>
      ))}
    </div>
  );
}

// Over-time view: stacked chart of one metric per period + per-model x period table.
function UsageOverTimeView({ granularity, metric, time, onMetricChange }: { granularity: Granularity; metric: UsageMetric; time: string; onMetricChange: (m: UsageMetric) => void }) {
  // The usage endpoint parses `time` server-side with finance's shared Fava
  // grammar; send it raw so specific dates / quarters / ranges all work.
  const qs = time.trim() ? `time=${encodeURIComponent(time.trim())}` : "";
  const { data, error, isLoading } = useSWR<ModelUsageRow[]>(
    `${API}/api/usage/model-daily${qs ? `?${qs}` : ""}`,
    fetcher,
  );

  const rows = useMemo(() => data || [], [data]);
  const models = useMemo(() => buildModelSeries(rows, metric), [rows, metric]);
  const periods = useMemo(() => buildPeriods(rows, granularity), [rows, granularity]);
  const byPeriod = useMemo(() => bucketByPeriodModel(rows, granularity, metric), [rows, granularity, metric]);
  const chartRows = useMemo(() => usageChartRows(byPeriod, models, periods), [byPeriod, models, periods]);
  const tableRows = useMemo(() => usageTableRows(byPeriod, models, periods), [byPeriod, models, periods]);
  // Per-column totals: each period's usage across all models (top-7 + Other) + grand total.
  const columnTotals = useMemo(() => {
    const totals: Record<string, number> = {};
    let grand = 0;
    for (const pk of periods) {
      let t = 0;
      for (const row of tableRows) t += row.values[pk] || 0;
      totals[pk] = t;
      grand += t;
    }
    return { totals, grand };
  }, [tableRows, periods]);

  // Clickable column sort: Model (by name), each period column (by that period's value),
  // and Range Σ (row.sum), defaulting to Range Σ descending. Special keys "__model" /
  // "__sum" can't collide with the YYYY-MM(-DD) period keys. Total row stays unsorted.
  const [sortKey, setSortKey] = useState<string>("__sum");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const onSort = (key: string) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "__model" ? "asc" : "desc");
    }
  };
  const arrow = (key: string) => (sortKey === key ? (sortDir === "asc" ? " ↑" : " ↓") : "");
  const sortedTableRows = useMemo(() => {
    const dirMul = sortDir === "asc" ? 1 : -1;
    return [...tableRows].sort((a, b) => {
      if (sortKey === "__model") return a.model.localeCompare(b.model) * dirMul;
      if (sortKey === "__sum") return (a.sum - b.sum) * dirMul;
      return ((a.values[sortKey] || 0) - (b.values[sortKey] || 0)) * dirMul;
    });
  }, [tableRows, sortKey, sortDir]);

  // When period columns overflow horizontally, land on the rightmost (most recent)
  // columns + sticky "Range Σ" on initial render and whenever the periods change.
  // Re-run on `metric` too: switching cost<->requests<->tokens changes cell widths
  // (so scrollWidth changes), and without this the Range Σ column gets clipped.
  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollLeft = el.scrollWidth;
  }, [periods, metric]);

  if (isLoading) return <ListLoading />;
  if (error && !data) return <ListError error={error} />;
  if (rows.length === 0) return <ListEmpty label="usage" />;

  return (
    <div className="h-full min-h-0 flex flex-col gap-3 px-3 pt-2 pb-2">
      <DailyUsageHeatmap time={time} metric={metric} />
      <div className="shrink-0 rounded border border-sol-base02 bg-sol-base03 p-3">
        <div className="mb-2">
          <div className="text-sol-base1 text-xs font-medium uppercase tracking-wide">
            {metric === "cost" ? "Cost" : metric === "requests" ? "Requests" : "Tokens"} over time
          </div>
          <div className="text-sol-base01 text-[10px]">Stacked by model (top 7 + Other), source=crs</div>
        </div>
        <ResponsiveContainer width="100%" height={210}>
          <BarChart data={chartRows} margin={{ top: 16, right: 20, left: 20, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={SOL.base02} />
            <XAxis dataKey="period" tick={{ fill: SOL.base0, fontSize: 11 }} stroke={SOL.base02} minTickGap={20} />
            <YAxis tick={{ fill: SOL.base0, fontSize: 11 }} stroke={SOL.base02} width={56} tickFormatter={(v) => formatMetric(v, metric)} />
            <Tooltip content={<UsageChartTooltip metric={metric} />} cursor={{ fill: "rgba(147, 161, 161, 0.15)" }} />
            {models.map((model, index) => (
              <Bar key={model} dataKey={model} stackId="usage" fill={MODEL_COLORS[index % MODEL_COLORS.length]} isAnimationActive={false} />
            ))}
          </BarChart>
        </ResponsiveContainer>
        <MetricToggle metric={metric} onChange={onMetricChange} />
      </div>

      <div className="flex-1 min-h-0 flex flex-col rounded border border-sol-base02 bg-sol-base03 overflow-hidden">
        <div className="shrink-0 border-b border-sol-base02 px-3 py-2">
          <div className="text-sol-base1 text-xs font-medium uppercase tracking-wide">
            {metric === "cost" ? "Cost" : metric === "requests" ? "Requests" : "Tokens"} history
          </div>
          <div className="text-sol-base01 text-[10px]">Rows are models; columns are periods</div>
        </div>
        <div ref={scrollRef} className="flex-1 min-h-0 overflow-auto">
          <table className="min-w-full text-xs">
            <thead>
              <tr className="text-sol-base01 border-b border-sol-base02">
                <th onClick={() => onSort("__model")} className="sticky left-0 top-0 z-20 bg-sol-base02 text-left font-normal py-1 px-3 whitespace-nowrap cursor-pointer select-none hover:text-sol-base0">Model{arrow("__model")}</th>
                {periods.map((pk) => (
                  <th key={pk} onClick={() => onSort(pk)} className="sticky top-0 z-10 bg-sol-base02 text-right font-normal py-1 px-3 whitespace-nowrap cursor-pointer select-none hover:text-sol-base0">{formatPeriodLabel(pk, granularity === "monthly")}{arrow(pk)}</th>
                ))}
                <th onClick={() => onSort("__sum")} className="sticky top-0 z-10 bg-sol-base02 text-right font-normal py-1 px-3 whitespace-nowrap border-l border-sol-base02 text-sol-base0 cursor-pointer select-none hover:text-sol-base1">Range Σ{arrow("__sum")}</th>
              </tr>
            </thead>
            <tbody>
              {sortedTableRows.map((row) => (
                <tr key={row.model} className="hover:bg-sol-base02/50">
                  <td className="sticky left-0 z-10 bg-sol-base03 py-0.5 px-3 font-mono text-sol-base0 whitespace-nowrap">{row.model}</td>
                  {periods.map((pk) => (
                    <td key={pk} className="py-0.5 px-3 text-right tabular-nums text-sol-base1 whitespace-nowrap">{formatMetric(row.values[pk] || 0, metric)}</td>
                  ))}
                  <td className="py-0.5 px-3 text-right tabular-nums text-sol-base1 whitespace-nowrap border-l border-sol-base02">{formatMetric(row.sum, metric)}</td>
                </tr>
              ))}
              <tr className="font-medium">
                <td className="sticky left-0 bottom-0 z-20 bg-sol-base02 py-1 px-3 text-sol-base1 whitespace-nowrap border-t border-sol-base02">Total</td>
                {periods.map((pk) => (
                  <td key={pk} className="sticky bottom-0 z-10 bg-sol-base02 py-1 px-3 text-right tabular-nums text-sol-base1 whitespace-nowrap border-t border-sol-base02">{formatMetric(columnTotals.totals[pk] || 0, metric)}</td>
                ))}
                <td className="sticky bottom-0 z-10 bg-sol-base02 py-1 px-3 text-right tabular-nums text-sol-base1 whitespace-nowrap border-l border-t border-sol-base02">{formatMetric(columnTotals.grand, metric)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function DailyUsageHeatmap({ time, metric }: { time: string; metric: UsageMetric }) {
  const heatYear = /^\d{4}$/.test(time.trim()) ? time.trim() : null;
  const { data: heatData } = useSWR<DailyTotal[]>(
    `${API}/api/usage/daily-totals${heatYear ? `?year=${heatYear}` : ""}`,
    fetcher,
  );
  const heatmap = useMemo(() => {
    const dailyTotals = new Map<string, number>();
    for (const row of heatData || []) dailyTotals.set(row.usage_date, metricValue(row, metric));
    return buildHeatmapWeeks(dailyTotals, time);
  }, [heatData, metric, time]);

  if (heatmap.weeks.length === 0) return null;

  return (
    <div className="shrink-0 rounded border border-sol-base02 bg-sol-base03 p-3">
      <div className="mb-2">
        <div className="text-sol-base1 text-xs font-medium uppercase tracking-wide">
          Daily {metric === "cost" ? "cost" : metric === "requests" ? "requests" : "tokens"}
        </div>
        <div className="text-sol-base01 text-[10px]">One cell per day, darker = more usage, source=crs</div>
      </div>
      <UsageHeatmap weeks={heatmap.weeks} max={heatmap.max} metric={metric} />
    </div>
  );
}

// Pie slices for Live mode: each model's share of the selected metric, top-7 by
// value + "Other" (mirrors buildModelSeries ordering). Zero-value models are dropped.
interface PieSlice { model: string; value: number; }
function buildModelPie(rows: ModelUsageAgg[], metric: UsageMetric): PieSlice[] {
  const ordered = rows
    .map((r) => ({ model: r.model, value: aggMetricValue(r, metric) }))
    .filter((s) => s.value > 0)
    .sort((a, b) => b.value - a.value);
  const top = ordered.slice(0, 7);
  const rest = ordered.slice(7);
  if (rest.length) return [...top, { model: "Other", value: rest.reduce((s, x) => s + x.value, 0) }];
  return top;
}

// Pie-slice tooltip: model name + formatted metric value + % share of the total.
function UsagePieTooltip({ active, payload, metric, total }: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color?: string }>;
  metric: UsageMetric;
  total: number;
}) {
  if (!active || !payload?.length) return null;
  const slice = payload[0];
  const value = Number(slice.value || 0);
  const pct = total > 0 ? (value / total) * 100 : 0;
  return (
    <div className="rounded px-2 py-1.5 text-xs" style={{ background: SOL.base02, border: `1px solid ${SOL.base01}` }}>
      <div className="flex items-center gap-2">
        <span className="inline-block w-2 h-2 rounded-full" style={{ background: slice.color }} />
        <span style={{ color: SOL.base1, fontWeight: 500 }}>{slice.name}</span>
      </div>
      <div style={{ color: SOL.base0 }} className="mt-0.5 tabular-nums">{formatMetric(value, metric)} · {pct.toFixed(1)}%</div>
    </div>
  );
}

// Range totals (tokens / cost / requests) stacked in the donut's center hole. This
// replaces the former header stat strip — the three headline numbers now live inside
// the ring. An absolutely-centered HTML overlay (pointer-events-none) is used instead
// of a recharts <Label>: with a bottom <Legend> reserving vertical space the chart's
// polar viewBox center drifts off the visible ring center, so an HTML block centered
// over the donut hole (matching the Pie's cy="50%") stays dead-center regardless of
// legend height.
// Fixed donut center Y (px) within the chart box (DONUT_HEIGHT). The Pie's cy is pinned
// here and the HTML totals overlay is positioned at the same pixel so the two always
// align. With outerRadius 80 the ring spans y=20..180, so the box is sized just past the
// ring bottom (no dead space before the legend below).
const DONUT_CY = 100;
// Chart box height: just past the ring bottom (DONUT_CY + outerRadius 80 + ~10px) so the
// legend in flow below sits snugly under the donut instead of after a tall empty gap.
const DONUT_HEIGHT = 190;

function DonutCenterLabel({ totals }: {
  totals: { all_tokens: number; cost: number; requests: number };
}) {
  const stats: [string, string][] = [
    ["TOKENS", fmtCompact(totals.all_tokens)],
    ["COST", fmtCost(totals.cost)],
    ["REQUESTS", fmtNum(totals.requests)],
  ];
  return (
    <div className="flex flex-col items-center gap-0.5 tabular-nums leading-none">
      {stats.map(([label, value]) => (
        <Fragment key={label}>
          <span style={{ color: SOL.base01, fontSize: 8 }} className="uppercase tracking-wide">{label}</span>
          <span style={{ color: SOL.cyan, fontSize: 14, fontWeight: 600 }}>{value}</span>
        </Fragment>
      ))}
    </div>
  );
}

// Custom pie legend: the recharts built-in <Legend> renders all items in one row,
// which is too wide/cramped with up to 8 entries (top-7 + Other). Chunk the slices
// into rows of at most 3 and center each row (partial last row included). Items are
// built from pieData in its existing share-descending order, and each dot's color is
// keyed on the same global index as the matching <Cell>, so legend and slices align.
function UsagePieLegend({ pieData }: { pieData: PieSlice[] }) {
  const items = pieData.map((d, i) => ({ model: d.model, color: MODEL_COLORS[i % MODEL_COLORS.length] }));
  const rows: (typeof items)[] = [];
  for (let i = 0; i < items.length; i += 3) rows.push(items.slice(i, i + 3));
  return (
    <div className="flex flex-col items-center gap-2.5 mt-1 py-2">
      {rows.map((row, ri) => (
        <div key={ri} className="flex justify-center gap-4">
          {row.map((it) => (
            <span key={it.model} className="inline-flex items-center gap-1" style={{ fontSize: 10 }}>
              <span className="inline-block rounded-full" style={{ width: 8, height: 8, background: it.color }} />
              <span style={{ color: SOL.base0 }}>{it.model}</span>
            </span>
          ))}
        </div>
      ))}
    </div>
  );
}

// Shared Requests/Tokens/Cost toggle row (finance income-statement chartTab style),
// rendered between a chart and its table in both Live and Over-time views. Both views
// drive the same parent-held usageMetric, so switching in one reflects in the other.
function MetricToggle({ metric, onChange }: { metric: UsageMetric; onChange: (m: UsageMetric) => void }) {
  return (
    <div className="flex justify-center gap-1 mt-1">
      {([["tokens", "Tokens"], ["cost", "Cost"], ["requests", "Requests"]] as const).map(([m, label]) => (
        <button
          key={m}
          onClick={() => onChange(m)}
          className={`px-2 py-0.5 rounded text-xs cursor-pointer ${
            metric === m
              ? "bg-sol-blue text-sol-base03"
              : "bg-sol-base02 text-sol-base0 hover:text-sol-base1"
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

// GitHub-style daily contribution heatmap, driven by the same selected metric as the
// donut/table. Columns are weeks (left=oldest), each column Sun(top)->Sat(bottom); cell
// color intensity scales with that day's metric value. Hover shows the date + exact value.
function UsageHeatmap({ weeks, max, metric }: { weeks: HeatCell[][]; max: number; metric: UsageMetric }) {
  const [hover, setHover] = useState<{ date: string; value: number; x: number; y: number } | null>(null);
  const fitRef = useRef<HTMLDivElement>(null);
  const innerRef = useRef<HTMLDivElement>(null);

  // Fit-to-width: the grid has a fixed natural size (weeks x 7 days), so scale the whole
  // thing with transform: scale() to consume the panel width — down on narrow panels,
  // and UP (capped at HEATMAP_MAX_SCALE) on wide ones so it fills the card instead of
  // sitting small in the top-left. scale() doesn't change the layout box, so the wrapper
  // height is set explicitly (overflow:hidden hides the reserved space); ceil + 2px keeps
  // the bottom (Sat) row from being clipped by sub-pixel rounding. Re-measure on panel
  // resize via ResizeObserver.
  useEffect(() => {
    const fit = fitRef.current;
    const inner = innerRef.current;
    if (!fit || !inner) return;
    const apply = () => {
      inner.style.transform = "none";
      const natW = inner.scrollWidth;
      const natH = inner.scrollHeight;
      const avail = fit.clientWidth;
      if (!natW || !avail) return; // skip pre-layout measurements
      const scale = Math.min(HEATMAP_MAX_SCALE, avail / natW);
      inner.style.transform = `scale(${scale})`;
      fit.style.height = `${Math.ceil(natH * scale) + 2}px`;
    };
    apply();
    const ro = new ResizeObserver(apply);
    ro.observe(fit);
    return () => ro.disconnect();
  }, [weeks]);

  if (weeks.length === 0) return null;

  // One month label per month, placed on the column that contains that month's 1st, so
  // each month is labelled exactly where it begins (no slivers, no crammed-together pair).
  const monthLabels = weeks.map((col) => {
    const firstOfMonth = col.find((cell) => cell.date.slice(8, 10) === "01");
    return firstOfMonth ? MONTHS_SHORT[parseInt(firstOfMonth.date.slice(5, 7), 10) - 1] : "";
  });
  const weekdayLabels = ["", "Mon", "", "Wed", "", "Fri", ""]; // index 0=Sun..6=Sat

  return (
    <div className="relative">
      {/* line-height/font-size 0 so baseline leading doesn't push the inline-flex grid past
          the JS-computed height and clip the bottom Sat row. */}
      <div ref={fitRef} className="overflow-hidden" style={{ lineHeight: 0, fontSize: 0 }}>
        <div ref={innerRef} className="inline-flex flex-col align-top" style={{ gap: HEATMAP_GAP, transformOrigin: "top left" }}>
          {/* Month labels row, offset past the weekday gutter */}
          <div className="flex" style={{ marginLeft: HEATMAP_WEEKDAY_W, gap: HEATMAP_GAP }}>
            {monthLabels.map((m, i) => (
              <div key={i} className="text-sol-base01 leading-none" style={{ width: HEATMAP_CELL, fontSize: 9 }}>{m}</div>
            ))}
          </div>
          <div className="flex" style={{ gap: HEATMAP_GAP }}>
            {/* Weekday gutter (Mon/Wed/Fri) */}
            <div className="flex flex-col" style={{ gap: HEATMAP_GAP, width: HEATMAP_WEEKDAY_W }}>
              {weekdayLabels.map((w, i) => (
                <div key={i} className="text-sol-base01 leading-none flex items-center" style={{ height: HEATMAP_CELL, fontSize: 9 }}>{w}</div>
              ))}
            </div>
            {/* Week columns */}
            <div className="flex" style={{ gap: HEATMAP_GAP }}>
              {weeks.map((col, ci) => (
                <div key={ci} className="flex flex-col" style={{ gap: HEATMAP_GAP }}>
                  {col.map((cell) => (
                    <div
                      key={cell.date}
                      className="rounded-xs hover:outline hover:outline-1 hover:outline-sol-base1"
                      style={{
                        width: HEATMAP_CELL,
                        height: HEATMAP_CELL,
                        background: HEATMAP_COLORS[heatmapLevel(cell.value, max)],
                      }}
                      onMouseEnter={(e) => setHover({ date: cell.date, value: cell.value, x: e.clientX, y: e.clientY })}
                      onMouseLeave={() => setHover(null)}
                    />
                  ))}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
      {/* Less -> More legend (GitHub style) */}
      <div className="flex items-center justify-end gap-1 mt-1.5 text-sol-base01 text-[9px]">
        <span>Less</span>
        {HEATMAP_COLORS.map((c, i) => (
          <span key={i} className="rounded-xs inline-block" style={{ width: HEATMAP_CELL, height: HEATMAP_CELL, background: c }} />
        ))}
        <span>More</span>
      </div>
      {hover && (
        <div
          className="fixed z-30 pointer-events-none rounded px-2 py-1 text-xs whitespace-nowrap"
          style={{ left: hover.x + 12, top: hover.y + 12, background: SOL.base02, border: `1px solid ${SOL.base01}` }}
        >
          <span style={{ color: SOL.base1 }}>{formatPeriodLabel(hover.date)}</span>
          <span style={{ color: SOL.base0 }} className="ml-2 tabular-nums">{formatMetric(hover.value, metric)}</span>
        </div>
      )}
    </div>
  );
}

// Live per-model table columns (sort-independent of the pie's metric toggle). Numeric
// columns default to descending on first click, string columns ascending — matching the
// config table's clickable-header behavior. Cache is one column sorted by cache_create.
type LiveSortKey = "model" | "all_tokens" | "cost" | "requests" | "input_tokens" | "output_tokens" | "cache_create_tokens";

// "pct" is a display-only column (not sortable); it shows each row's share of the
// active sort column's total, so it has no LiveSortKey of its own. `reveal` gates a column
// behind the table card's width (container queries): "io" (Input/Output) appears >=560px,
// "cache" appears >=700px; the rest always show.
const LIVE_COLUMNS: { key: LiveSortKey | "pct"; label: string; numeric: boolean; reveal?: "io" | "cache" }[] = [
  { key: "model", label: "Model", numeric: false },
  { key: "pct", label: "%", numeric: true },
  { key: "all_tokens", label: "Tokens", numeric: true },
  { key: "cost", label: "Cost", numeric: true },
  { key: "requests", label: "Requests", numeric: true },
  { key: "input_tokens", label: "Input", numeric: true, reveal: "io" },
  { key: "output_tokens", label: "Output", numeric: true, reveal: "io" },
  { key: "cache_create_tokens", label: "Cache (cr/rd)", numeric: true, reveal: "cache" },
];

// Tailwind container-query classes for a column's reveal gate (table card is the @container).
const revealClass = (reveal?: "io" | "cache"): string =>
  reveal === "io" ? "hidden @min-[560px]:table-cell" : reveal === "cache" ? "hidden @min-[700px]:table-cell" : "";

function liveSortValue(a: ModelUsageAgg, key: LiveSortKey): string | number {
  if (key === "model") return a.model;
  return a[key];
}

// Per-model usage snapshot for Live mode: aggregates daily rows over the selected
// time range (source=crs only). Defaults to today when no range is given. A single
// donut pie driven by the shared metric sits above the metric toggle and per-model table.
function UsageTable({ time, metric, onMetricChange }: { time: string; metric: UsageMetric; onMetricChange: (m: UsageMetric) => void }) {
  // The usage endpoint parses `time` server-side with finance's shared Fava
  // grammar; send it raw so specific dates / quarters / ranges all work.
  const qs = time.trim() ? `time=${encodeURIComponent(time.trim())}` : "";
  const { data, error, isLoading } = useSWR<ModelUsageRow[]>(
    `${API}/api/usage/model-daily${qs ? `?${qs}` : ""}`,
    fetcher,
  );

  const rows = useMemo(() => aggregateByModel(data || []), [data]);

  // Table sort is independent of the pie's metric toggle: every column header is
  // clickable, defaulting to Tokens descending. Numeric columns flip to desc on first
  // click, string columns to asc; clicking the active column toggles direction.
  const [sortKey, setSortKey] = useState<LiveSortKey>("all_tokens");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const onSort = (key: LiveSortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      const col = LIVE_COLUMNS.find((c) => c.key === key);
      setSortDir(col && !col.numeric ? "asc" : "desc");
    }
  };
  const sortedRows = useMemo(() => {
    const dirMul = sortDir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const av = liveSortValue(a, sortKey);
      const bv = liveSortValue(b, sortKey);
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * dirMul;
      return String(av).localeCompare(String(bv)) * dirMul;
    });
  }, [rows, sortKey, sortDir]);

  // Single donut: each model's share of the selected metric (top-7 + Other).
  const pieData = useMemo(() => buildModelPie(rows, metric), [rows, metric]);
  const pieTotal = useMemo(() => pieData.reduce((s, d) => s + d.value, 0), [pieData]);

  // Per-column totals: sum each numeric column across all model rows.
  const totals = useMemo(() => rows.reduce(
    (t, r) => {
      t.all_tokens += r.all_tokens;
      t.cost += r.cost;
      t.requests += r.requests;
      t.input_tokens += r.input_tokens;
      t.output_tokens += r.output_tokens;
      t.cache_create_tokens += r.cache_create_tokens;
      t.cache_read_tokens += r.cache_read_tokens;
      return t;
    },
    { all_tokens: 0, cost: 0, requests: 0, input_tokens: 0, output_tokens: 0, cache_create_tokens: 0, cache_read_tokens: 0 },
  ), [rows]);

  // The "%" column = each row's value in the active numeric sort column / that column's
  // total across all rows. Model (non-numeric) has no sensible total, so fall back to
  // Tokens. Recomputes whenever sortKey changes.
  const pctKey = sortKey === "model" ? "all_tokens" : sortKey;
  const pctTotal = totals[pctKey];

  // Cap the table card to header + 5 data rows + Total, then scroll the rest under the
  // sticky header/Total. Measure real rendered heights (they vary with font metrics) and
  // set the scroll wrapper's max-height; recompute when the row count changes.
  const tblWrapRef = useRef<HTMLDivElement>(null);
  const theadRef = useRef<HTMLTableSectionElement>(null);
  const firstRowRef = useRef<HTMLTableRowElement>(null);
  const totalRowRef = useRef<HTMLTableRowElement>(null);
  useEffect(() => {
    const wrap = tblWrapRef.current;
    const thead = theadRef.current;
    const firstRow = firstRowRef.current;
    const totalRow = totalRowRef.current;
    if (!wrap || !thead || !firstRow || !totalRow) return;
    const headH = thead.getBoundingClientRect().height;
    const rowH = firstRow.getBoundingClientRect().height;
    const totalH = totalRow.getBoundingClientRect().height;
    wrap.style.maxHeight = `${headH + 5 * rowH + totalH}px`;
  }, [sortedRows.length]);

  if (isLoading) return <ListLoading />;
  if (error && !data) return <ListError error={error} />;
  if (rows.length === 0) return <ListEmpty label="usage" />;

  return (
    <div className="h-full min-h-0 flex flex-col gap-3">
      <div className="shrink-0 rounded border border-sol-base02 bg-sol-base03 p-3">
        {pieData.length === 0 ? (
          <div className="text-xs text-sol-base01/70 italic text-center py-12">No {metric} in this range</div>
        ) : (
          // The donut center is pinned to a fixed pixel (DONUT_CY) so the HTML totals
          // overlay can sit dead-center in the ring hole regardless of the bottom
          // legend's measured height (which otherwise shifts the polar viewBox center).
          <div className="relative" style={{ height: DONUT_HEIGHT }}>
            <ResponsiveContainer width="100%" height={DONUT_HEIGHT}>
              <PieChart margin={{ top: 4, right: 8, left: 8, bottom: 4 }}>
                <Pie data={pieData} dataKey="value" nameKey="model" cx="50%" cy={DONUT_CY} outerRadius={80} innerRadius={52} stroke={SOL.base03} isAnimationActive={false}>
                  {pieData.map((d, i) => (
                    <Cell key={d.model} fill={MODEL_COLORS[i % MODEL_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip content={<UsagePieTooltip metric={metric} total={pieTotal} />} wrapperStyle={{ zIndex: 20 }} isAnimationActive={false} />
              </PieChart>
            </ResponsiveContainer>
            <div
              className="absolute left-1/2 -translate-x-1/2 -translate-y-1/2 pointer-events-none"
              style={{ top: DONUT_CY, zIndex: 10 }}
            >
              <DonutCenterLabel totals={totals} />
            </div>
          </div>
        )}
        {/* Legend rendered as a normal HTML block in document flow below the fixed-height
            chart (not via recharts <Legend>, which is absolutely positioned inside the
            fixed-height ResponsiveContainer and would overlap the donut when it wraps to 3 rows).
            Built from pieData so dots index into MODEL_COLORS the same way as the slices. */}
        {pieData.length > 0 && <UsagePieLegend pieData={pieData} />}
        <MetricToggle metric={metric} onChange={onMetricChange} />
      </div>
      {/* Per-model table card. The card is a query container so columns reveal by the PANEL
          width (not the viewport): narrow shows through Requests, >=560px adds Input/Output,
          >=700px adds Cache. Capped to 5 data rows then scrolls under a sticky header + Total. */}
      <div className="shrink-0 rounded border border-sol-base02 bg-sol-base03 p-3 @container">
        <div ref={tblWrapRef} className="overflow-auto">
          {/* border-separate so the sticky header/Total cells fully cover the scrolling rows
              (with border-collapse the shared 1px borders paint at table level and bleed through). */}
          <table className="w-full text-xs border-separate border-spacing-0">
            <thead ref={theadRef}>
              <tr className="text-sol-base01 text-left text-xs">
                {LIVE_COLUMNS.map((col) => {
                  const reveal = revealClass(col.reveal);
                  if (col.key === "pct") {
                    return (
                      <th
                        key={col.key}
                        className={`sticky top-0 z-20 py-1 px-1.5 bg-sol-base03 border-b border-sol-base02 select-none text-right whitespace-nowrap ${reveal}`}
                        title="Share of the active sort column's total"
                      >
                        {col.label}
                      </th>
                    );
                  }
                  const key = col.key; // narrowed to LiveSortKey after the pct early-return
                  const active = sortKey === key;
                  return (
                    <th
                      key={key}
                      onClick={() => onSort(key)}
                      className={`sticky top-0 z-20 py-1 px-1.5 bg-sol-base03 border-b border-sol-base02 cursor-pointer select-none hover:text-sol-base1 whitespace-nowrap ${col.numeric ? "text-right" : ""} ${reveal}`}
                    >
                      {col.label}{active ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {sortedRows.map((r, i) => (
                <tr key={r.model} ref={i === 0 ? firstRowRef : undefined} className="hover:bg-sol-base02/50">
                  <td className="px-1.5 py-1 font-mono text-sol-base1 border-b border-sol-base02/40 whitespace-nowrap">{r.model}</td>
                  <td className="px-1.5 py-1 text-right text-sol-base0 tabular-nums border-b border-sol-base02/40">{pctTotal > 0 ? `${((r[pctKey] / pctTotal) * 100).toFixed(1)}%` : "-"}</td>
                  <td className="px-1.5 py-1 text-right text-sol-base1 tabular-nums border-b border-sol-base02/40">{fmtCompact(r.all_tokens)}</td>
                  <td className="px-1.5 py-1 text-right text-sol-base0 tabular-nums border-b border-sol-base02/40">{fmtCost(r.cost)}</td>
                  <td className="px-1.5 py-1 text-right text-sol-base0 tabular-nums border-b border-sol-base02/40">{fmtNum(r.requests)}</td>
                  <td className="px-1.5 py-1 text-right text-sol-base0 tabular-nums border-b border-sol-base02/40 hidden @min-[560px]:table-cell">{fmtCompact(r.input_tokens)}</td>
                  <td className="px-1.5 py-1 text-right text-sol-base0 tabular-nums border-b border-sol-base02/40 hidden @min-[560px]:table-cell">{fmtCompact(r.output_tokens)}</td>
                  <td className="px-1.5 py-1 text-right text-sol-base0 tabular-nums border-b border-sol-base02/40 hidden @min-[700px]:table-cell">{fmtCacheCreate(r.cache_create_tokens, r.provider, fmtCompact)}/{fmtCompact(r.cache_read_tokens)}</td>
                </tr>
              ))}
              <tr ref={totalRowRef} className="font-medium">
                <td className="sticky bottom-0 z-20 px-1.5 py-1 text-sol-base1 bg-sol-base02 border-t border-sol-base02">Total</td>
                <td className="sticky bottom-0 z-20 px-1.5 py-1 text-right text-sol-base0 tabular-nums bg-sol-base02 border-t border-sol-base02">{pctTotal > 0 ? "100.0%" : "-"}</td>
                <td className="sticky bottom-0 z-20 px-1.5 py-1 text-right text-sol-base1 tabular-nums bg-sol-base02 border-t border-sol-base02">{fmtCompact(totals.all_tokens)}</td>
                <td className="sticky bottom-0 z-20 px-1.5 py-1 text-right text-sol-base1 tabular-nums bg-sol-base02 border-t border-sol-base02">{fmtCost(totals.cost)}</td>
                <td className="sticky bottom-0 z-20 px-1.5 py-1 text-right text-sol-base1 tabular-nums bg-sol-base02 border-t border-sol-base02">{fmtNum(totals.requests)}</td>
                <td className="sticky bottom-0 z-20 px-1.5 py-1 text-right text-sol-base1 tabular-nums bg-sol-base02 border-t border-sol-base02 hidden @min-[560px]:table-cell">{fmtCompact(totals.input_tokens)}</td>
                <td className="sticky bottom-0 z-20 px-1.5 py-1 text-right text-sol-base1 tabular-nums bg-sol-base02 border-t border-sol-base02 hidden @min-[560px]:table-cell">{fmtCompact(totals.output_tokens)}</td>
                <td className="sticky bottom-0 z-20 px-1.5 py-1 text-right text-sol-base1 tabular-nums bg-sol-base02 border-t border-sol-base02 hidden @min-[700px]:table-cell">{fmtCompact(totals.cache_create_tokens)}/{fmtCompact(totals.cache_read_tokens)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function LimitWindowRow({ label, window, timezone }: { label: string; window: UsageLimitWindow | null; timezone?: string }) {
  const used = window?.used_percent;
  const remaining = window?.remaining_percent;
  const hasUsage = typeof used === "number" && typeof remaining === "number";
  return (
    <div className="grid grid-cols-[48px_minmax(72px,1fr)_auto] gap-x-2 gap-y-1 text-[10px] min-w-0">
      <span className="pt-0.5 text-sol-base0">{label}</span>
      <div className="mt-1.5 h-1.5 min-w-0 overflow-hidden rounded-full bg-sol-base02">
        {hasUsage && <div className={`h-full rounded-full ${used >= 80 ? "bg-sol-orange" : used >= 60 ? "bg-sol-yellow" : "bg-sol-green"}`} style={{ width: `${Math.max(0, Math.min(100, used))}%` }} />}
      </div>
      <span className="font-medium tabular-nums text-sol-base1">{hasUsage ? `${used.toFixed(0)}%` : "—"}</span>
      <div className="col-start-2 col-end-4 flex min-w-0 justify-between gap-2 text-sol-base01">
        <span className="text-sol-base0 whitespace-nowrap">{hasUsage ? `${remaining.toFixed(0)}% remaining` : "usage unavailable"}</span>
        <span className="min-w-0 truncate text-right" title={window?.reset_at || undefined}>{formatResetTime(window?.reset_at || null, timezone)}{window?.reset_at ? ` · ${formatRelativeTime(window.reset_at)}` : ""}</span>
      </div>
    </div>
  );
}

function UsageLimitCard({ provider, lastReadFailed, timezone }: { provider: UsageLimitProvider; lastReadFailed: boolean; timezone?: string }) {
  const unavailable = provider.freshness === "unavailable" || provider.availability === "unavailable";
  const freshness: LimitFreshness = lastReadFailed && !unavailable ? "stale" : provider.freshness;
  const badgeClasses = freshness === "fresh" ? "border-sol-green/40 bg-sol-green/10 text-sol-green" : freshness === "stale" ? "border-sol-yellow/40 bg-sol-yellow/10 text-sol-yellow" : "border-sol-red/40 bg-sol-red/10 text-sol-red";
  const errorMessage = provider.error || (provider.availability === "unavailable" ? "This account does not expose authoritative subscription percentages." : "Required usage windows are not available yet.");
  const mark = providerLabel(provider) === "Claude" ? "C" : "G";
  return (
    <article className="min-w-0 border-b border-sol-base02 p-3 last:border-b-0 @min-[620px]:border-b-0 @min-[620px]:border-r @min-[620px]:last:border-r-0">
      <div className="mb-3 flex min-w-0 items-center gap-2">
        <span className={`grid size-6 shrink-0 place-items-center rounded text-xs font-semibold ${mark === "C" ? "bg-sol-orange/15 text-sol-orange" : "bg-sol-blue/15 text-sol-blue"}`}>{mark}</span>
        <div className="min-w-0 flex-1"><div className="truncate text-xs font-semibold text-sol-base1">{providerLabel(provider)}</div><div className="truncate text-[10px] text-sol-base01">{provider.account_name || "Subscription account"}</div></div>
        <span className={`rounded border px-1.5 py-0.5 text-[9px] uppercase tracking-wide ${badgeClasses}`}>{freshness}</span>
      </div>
      {unavailable ? <div className="rounded border border-dashed border-sol-base01 px-2.5 py-3 text-[10px] text-sol-base01"><strong className="mb-1 block text-sol-base0">Usage windows unavailable</strong>{errorMessage}</div> : <>
        <div className="space-y-2.5"><LimitWindowRow label="5 hours" window={provider.windows.five_hour} timezone={timezone} /><LimitWindowRow label="1 week" window={provider.windows.one_week} timezone={timezone} /></div>
        <div className="mt-2 border-t border-sol-base02 pt-2 text-[10px] text-sol-base01">Observed <strong className="font-medium text-sol-base0">{formatRelativeTime(provider.observed_at)}</strong> via {providerSource(provider.source)}{lastReadFailed ? " · last read failed" : ""}</div>
      </>}
    </article>
  );
}

export function UsageLimits() {
  const [visible, setVisible] = useState(() => typeof document === "undefined" || document.visibilityState === "visible");
  useEffect(() => {
    const onVisibilityChange = () => setVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => document.removeEventListener("visibilitychange", onVisibilityChange);
  }, []);
  const { data, error, isLoading, mutate } = useSWR<UsageLimitsResponse>(visible ? `${API}/api/usage/limits` : null, fetcher, { refreshInterval: USAGE_LIMIT_POLL_INTERVAL, revalidateOnFocus: true });
  const providers = data?.providers || [];
  const hasPartialError = Boolean(error || (data?.errors.length));
  return (
    <section className="@container shrink-0 overflow-hidden rounded border border-sol-base02 bg-sol-base03">
      <div className="flex items-center gap-2 border-b border-sol-base02 px-3 py-2"><span className="text-[11px] font-semibold uppercase tracking-wide text-sol-base1">Subscription limits</span><span className="hidden text-[10px] text-sol-base01 @min-[460px]:inline">account-wide · updates every 60s</span>{hasPartialError && <span className="min-w-0 truncate text-[10px] text-sol-yellow" title="Some providers could not be refreshed">partial read</span>}<button onClick={() => void mutate()} disabled={isLoading} className={`ml-auto rounded px-1.5 py-0.5 text-xs text-sol-base0 hover:bg-sol-base02 hover:text-sol-base1 ${isLoading ? "animate-spin cursor-wait opacity-50" : "cursor-pointer"}`} title="Retry subscription status">↻</button></div>
      {isLoading && !data ? <div className="p-3 text-xs italic text-sol-base01">Loading subscription limits...</div> : providers.length > 0 ? <div className="grid grid-cols-[repeat(auto-fit,minmax(260px,1fr))]">{providers.map((provider, index) => <UsageLimitCard key={`${provider.backend}:${provider.account_id || index}`} provider={provider} lastReadFailed={Boolean(error)} timezone={data?.timezone} />)}</div> : <div className="p-3 text-xs text-sol-base01">{error ? "Subscription limits could not be loaded. Retry to try again." : "No subscription accounts are configured."}</div>}
    </section>
  );
}

export default function BotViewer() {
  const { mutate: globalMutate } = useSWRConfig();
  const [query, setQuery] = useState("");
  const [view, setView] = useState<ViewMode>(
    () => (localStorage.getItem(VIEW_STORAGE_KEY) === "usage" ? "usage" : "config"),
  );
  const [usageMode, setUsageMode] = useState<UsageMode>(
    () => (localStorage.getItem(USAGE_MODE_STORAGE_KEY) === "over-time" ? "over-time" : "live"),
  );
  // Independent free-text time ranges (committed on Enter/blur — mirrors FinanceViewer's
  // Income Statement time input). Live and Over-time each persist their own value; the single
  // input below edits/reads whichever mode is active. `usageTimeInput` is the editing buffer;
  // `usageTime` (the active mode's committed value) drives the query.
  const [liveTime, setLiveTime] = useState(() => localStorage.getItem(USAGE_LIVE_TIME_STORAGE_KEY) || "today");
  const [overTime, setOverTime] = useState(() => localStorage.getItem(USAGE_OVER_TIME_STORAGE_KEY) || "month");
  const usageTime = usageMode === "over-time" ? overTime : liveTime;
  const [usageTimeInput, setUsageTimeInput] = useState(usageTime);
  // Recall the active mode's stored value into the input buffer when the mode switches.
  useEffect(() => {
    setUsageTimeInput(usageMode === "over-time" ? overTime : liveTime);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [usageMode]);
  const commitUsageTime = () => {
    const v = usageTimeInput.trim();
    if (usageMode === "over-time") {
      setOverTime(v);
      localStorage.setItem(USAGE_OVER_TIME_STORAGE_KEY, v);
    } else {
      setLiveTime(v);
      localStorage.setItem(USAGE_LIVE_TIME_STORAGE_KEY, v);
    }
  };
  const [granularity, setGranularity] = useState<Granularity>(() => {
    const saved = localStorage.getItem(USAGE_GRANULARITY_STORAGE_KEY);
    return saved === "weekly" || saved === "monthly" ? saved : "daily";
  });
  const [usageMetric, setUsageMetric] = useState<UsageMetric>("tokens");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>(loadTypeFilter());
  const [sortKey, setSortKey] = useState<SortKey>(loadSortKey());
  const [sortDir, setSortDir] = useState<SortDir>(loadSortDir());
  const [expandedName, setExpandedName] = useState<string | null>(null);
  const [form, setForm] = useState<BotFormState | null>(null);
  const [editing, setEditing] = useState<BotConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshingUsage, setRefreshingUsage] = useState(false);

  // Trigger the CRS model-usage sync, then revalidate the usage SWR caches (the
  // donut/table model-daily URL and the heatmap's daily-totals URL both live under
  // /api/usage/, so match the whole prefix).
  const refreshUsage = async () => {
    setRefreshingUsage(true);
    try {
      const res = await authFetch(`${API}/api/usage/sync`, { method: "POST" });
      if (!res.ok) throw new Error("Failed to sync model usage");
      await globalMutate(
        (key) => typeof key === "string" && key.startsWith(`${API}/api/usage/`),
        undefined,
        { revalidate: true },
      );
    } finally {
      setRefreshingUsage(false);
    }
  };

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setExpandedName(null); if (!form) setExpandedName(null); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [form]);

  const { data, error: loadError, isLoading, mutate } = useSWR<BotConfig[]>(
    `${API}/api/bot/list`,
    fetcher,
  );

  const bots = useMemo(() => data || [], [data]);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return bots.filter((b) => {
      if (typeFilter !== "all" && (b.type || "agent") !== typeFilter) return false;
      if (!q) return true;
      return (
        b.name.toLowerCase().includes(q) ||
        (b.model || "").toLowerCase().includes(q) ||
        (b.backend || "").toLowerCase().includes(q)
      );
    });
  }, [bots, query, typeFilter]);

  const sorted = useMemo(() => {
    const dirMul = sortDir === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      const av = botValue(a, sortKey);
      const bv = botValue(b, sortKey);
      const aMissing = av === null || av === "";
      const bMissing = bv === null || bv === "";
      if (aMissing && bMissing) return 0;
      if (aMissing) return 1;
      if (bMissing) return -1;
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * dirMul;
      return String(av).localeCompare(String(bv)) * dirMul;
    });
  }, [filtered, sortKey, sortDir]);

  const onSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  useEffect(() => {
    localStorage.setItem(SORT_KEY_STORAGE_KEY, sortKey);
  }, [sortKey]);

  useEffect(() => {
    localStorage.setItem(SORT_DIR_STORAGE_KEY, sortDir);
  }, [sortDir]);

  useEffect(() => {
    localStorage.setItem(VIEW_STORAGE_KEY, view);
  }, [view]);

  useEffect(() => {
    localStorage.setItem(TYPE_FILTER_STORAGE_KEY, typeFilter);
  }, [typeFilter]);

  useEffect(() => {
    localStorage.setItem(USAGE_MODE_STORAGE_KEY, usageMode);
  }, [usageMode]);

  useEffect(() => {
    localStorage.setItem(USAGE_GRANULARITY_STORAGE_KEY, granularity);
  }, [granularity]);

  useEffect(() => {
    if (!form) { setBusy(false); setError(null); }
  }, [form]);

  const revalidate = () => { mutate(); };

  // -- New bot modal (reuses BotForm from BotList) --
  const openNew = () => { setEditing(null); setForm(emptyForm()); };

  const saveNew = async () => {
    if (!form || busy) return;
    if (!form.name.trim()) { setError("Name is required"); return; }
    setBusy(true);
    setError(null);
    const body = {
      name: form.name.trim(),
      base_url: form.base_url.trim() || null,
      backend: form.backend || null,
      model: form.model.trim() || null,
      description: form.description || null,
      max_tokens: form.max_tokens ? Number(form.max_tokens) : null,
      custom_api_path: form.custom_api_path || null,
      type: form.type || null,
      tier: form.tier || null,
      route_weight: form.route_weight ? Number(form.route_weight) : null,
      ref_bot_name: form.ref_bot_name.trim() || null,
      ...(form.api_key ? { api_key: form.api_key } : {}),
    };
    try {
      await apiJson("/api/bot", body);
      setForm(null);
      setEditing(null);
      revalidate();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="h-full flex flex-col bg-sol-base03">
      <div className="p-2 border-b border-sol-base02 shrink-0 space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
        <div className="flex items-center gap-1">
          {(["config", "usage"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`px-2.5 py-1 rounded text-xs cursor-pointer ${
                view === v
                  ? "bg-sol-blue text-sol-base03"
                  : "bg-sol-base02 text-sol-base0 hover:text-sol-base1"
              }`}
            >
              {v}
            </button>
          ))}
        </div>
        {view === "config" ? (
          <>
            <div className="flex items-center gap-1">
              {(["all", "agent", "model"] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => setTypeFilter(f)}
                  className={`px-2.5 py-1 rounded text-xs cursor-pointer ${
                    typeFilter === f
                      ? "bg-sol-blue text-sol-base03"
                      : "bg-sol-base02 text-sol-base0 hover:text-sol-base1"
                  }`}
                >
                  {f}
                </button>
              ))}
            </div>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search bots"
              className="min-w-0 flex-1 px-2 py-1 bg-sol-base02 border border-sol-base01 rounded text-xs text-sol-base0 outline-none focus:border-sol-blue"
            />
            <button
              onClick={openNew}
              className="px-2 py-1 flex items-center gap-1 rounded text-xs text-sol-blue hover:bg-sol-blue/10 cursor-pointer border border-sol-blue/40"
              title="New bot"
            >
              <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 5v14" /><path d="M5 12h14" />
              </svg>
              New bot
            </button>
          </>
        ) : (
          <div className="flex items-center gap-2 flex-wrap ml-auto">
            <button
              onClick={() => void refreshUsage()}
              disabled={refreshingUsage}
              className={`px-2 py-1 rounded text-xs bg-sol-base02 text-sol-base0 hover:text-sol-base1 ${
                refreshingUsage ? "opacity-50 cursor-wait animate-spin" : "cursor-pointer"
              }`}
              title="Sync model usage from CRS"
            >
              ↻
            </button>
            <div className="flex items-center gap-1">
              {([["live", "Live"], ["over-time", "Over time"]] as const).map(([m, label]) => (
                <button
                  key={m}
                  onClick={() => setUsageMode(m)}
                  className={`px-2 py-1 rounded text-xs cursor-pointer ${
                    usageMode === m
                      ? "bg-sol-blue text-sol-base03"
                      : "bg-sol-base02 text-sol-base0 hover:text-sol-base1"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            <input
              type="text"
              value={usageTimeInput}
              onChange={(e) => setUsageTimeInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") commitUsageTime(); }}
              onBlur={commitUsageTime}
              placeholder="day, week, month, year, all, 2024-05, 2024-q2, 2024-05-15, day-7 to day"
              className="px-2 py-1 rounded text-xs w-56 bg-sol-base02 text-sol-base1 border border-sol-base01 outline-none placeholder:text-sol-base01"
            />
            {usageMode === "over-time" && (
              <div className="flex items-center gap-1">
                {([["daily", "D"], ["weekly", "W"], ["monthly", "M"]] as const).map(([g, label]) => (
                  <button
                    key={g}
                    onClick={() => setGranularity(g)}
                    className={`px-1.5 py-1 rounded text-[10px] cursor-pointer ${
                      granularity === g
                        ? "bg-sol-blue text-sol-base03"
                        : "bg-sol-base02 text-sol-base01 hover:text-sol-base0"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        </div>
      </div>
      <div className="flex-1 min-h-0 overflow-auto" onClick={(e) => { if (expandedName && !(e.target as HTMLElement).closest('[data-bot-card]')) setExpandedName(null); }}>
        {view === "usage" ? (
          <div className="flex min-h-full flex-col gap-3 p-3">
            {usageMode === "over-time" ? (
              <UsageOverTimeView granularity={granularity} metric={usageMetric} time={usageTime} onMetricChange={setUsageMetric} />
            ) : (
              <>
                <UsageLimits />
                <UsageTable time={usageTime} metric={usageMetric} onMetricChange={setUsageMetric} />
              </>
            )}
          </div>
        ) : isLoading ? (
          <ListLoading />
        ) : loadError && !data ? (
          <ListError error={loadError} />
        ) : filtered.length === 0 ? (
          query || typeFilter !== "all" ? <p className="text-sol-base01 italic p-2">No matching bots</p> : <ListEmpty label="bots" />
        ) : (
          <div className="px-3 pt-2">
            <table className="w-full text-xs border-collapse">
              <thead>
                <tr className="text-sol-base01 text-left text-xs border-b border-sol-base02">
                  {COLUMNS.map((col) => {
                    const active = sortKey === col.key;
                    return (
                      <th
                        key={col.key}
                        onClick={() => onSort(col.key)}
                        className={`py-1 px-1.5 cursor-pointer select-none hover:text-sol-base1 ${col.align === "right" ? "text-right" : ""}`}
                      >
                        {col.label}{active ? (sortDir === "asc" ? " \u2191" : " \u2193") : ""}
                      </th>
                    );
                  })}
                  <th className="py-1 px-1.5 text-center font-medium">On</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((bot) => (
                  <Fragment key={bot.name}>
                    <tr
                      className={`border-b border-sol-base02/40 hover:bg-sol-base02/50 cursor-pointer ${expandedName === bot.name ? "bg-sol-base02/50" : ""}`}
                      onClick={() => setExpandedName(expandedName === bot.name ? null : bot.name)}
                    >
                      <td className="px-1.5 py-1">
                        <span className="inline-flex items-center gap-1 min-w-0">
                          <span className="text-sol-base1 font-medium">{bot.name}</span>
                          {bot.name === "default" && <span className="text-[0.55rem] px-1 rounded bg-sol-base02 text-sol-base01 shrink-0">def</span>}
                          {bot.has_api_key && <span className="text-[0.55rem] px-1 rounded bg-sol-green/15 text-sol-green shrink-0">key</span>}
                          {bot.ref_bot_name && <span className="text-[0.55rem] px-1 rounded bg-sol-blue/15 text-sol-blue shrink-0" title={bot.ref_bot_name}>ref</span>}
                        </span>
                      </td>
                      <td className="px-1.5 py-1 text-sol-base01 whitespace-nowrap">{bot.backend || "-"}</td>
                      <td className="px-1.5 py-1 font-mono text-sol-base01">{bot.model || "-"}</td>
                      <td className="px-1.5 py-1 text-sol-base0 whitespace-nowrap">{bot.type || "agent"}</td>
                      <td className="px-1.5 py-1 text-sol-base01 whitespace-nowrap">{bot.tier || "-"}</td>
                      <td className="px-1.5 py-1 text-right text-sol-base0 whitespace-nowrap tabular-nums">{fmtPrice(bot.route_weight)}</td>
                      <td className="px-1.5 py-1 text-right text-sol-base0 whitespace-nowrap tabular-nums">{fmtPrice(bot.price_input)}</td>
                      <td className="px-1.5 py-1 text-right text-sol-base0 whitespace-nowrap tabular-nums">{fmtPrice(bot.price_output)}</td>
                      <td className="px-1.5 py-1 text-center">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            const action = bot.enabled !== false ? "disable" : "enable";
                            apiJson(`/api/bot/${action}`, { name: bot.name }).then(revalidate).catch(() => {});
                          }}
                          disabled={bot.name === "default"}
                          className={`w-3 h-3 rounded-full cursor-pointer border ${
                            bot.enabled !== false
                              ? "bg-sol-green/60 border-sol-green"
                              : "bg-sol-red/40 border-sol-red"
                          } ${bot.name === "default" ? "opacity-50 cursor-not-allowed" : "hover:scale-110"}`}
                          title={bot.enabled !== false ? "Enabled — click to disable" : "Disabled — click to enable"}
                        />
                      </td>
                    </tr>
                    {expandedName === bot.name && (
                      <tr className="border-b border-sol-base02">
                        <td colSpan={COL_COUNT} className="p-2">
                          <BotDetail bot={bot} onClose={() => setExpandedName(null)} onSaved={revalidate} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {/* Only show modal for creating new bots */}
      {form && (
        <BotForm
          form={form}
          setForm={setForm}
          isEdit={false}
          hasApiKey={false}
          busy={busy}
          error={error}
          onSave={saveNew}
          onCancel={() => { if (!busy) { setForm(null); setEditing(null); } }}
        />
      )}
      {!form && error && <div className="p-2 text-xs text-sol-red border-t border-sol-base02">{error}</div>}
    </div>
  );
}
