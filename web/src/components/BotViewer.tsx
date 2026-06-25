import { Fragment, useEffect, useMemo, useState } from "react";
import useSWR, { mutate as globalMutate } from "swr";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
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

// Selected metric's value for a single daily row.
function metricValue(row: ModelUsageRow, metric: UsageMetric): number {
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

// Resolve a free-text usage time expression into a usage-endpoint query window.
// Shared by Live and Over-time (mirrors FinanceViewer's Income Statement time input UX);
// supported tokens are a focused subset because the usage endpoint only takes
// from_date/to_date (finance's Fava grammar is server-side). Supported: empty/"today",
// "week", "month"/"mtd", "year"/"ytd", "all", a bare "YYYY", or "YYYY-MM". Unknown input
// falls back to today.
function parseUsageTime(value: string): { fromDate: string | null; toDate: string | null; limit: number | null } {
  const v = value.trim().toLowerCase();
  const today = new Date();
  const todayStr = localDateStr(today);
  if (v === "" || v === "today" || v === "day") return { fromDate: null, toDate: null, limit: null };
  if (v === "all") return { fromDate: "2000-01-01", toDate: todayStr, limit: 100000 };
  if (v === "week") return { fromDate: mondayOf(todayStr), toDate: todayStr, limit: null };
  if (v === "month" || v === "mtd") {
    const first = new Date(today.getFullYear(), today.getMonth(), 1);
    return { fromDate: localDateStr(first), toDate: todayStr, limit: null };
  }
  if (v === "year" || v === "ytd") {
    const first = new Date(today.getFullYear(), 0, 1);
    return { fromDate: localDateStr(first), toDate: todayStr, limit: null };
  }
  const yearMatch = /^(\d{4})$/.exec(v);
  if (yearMatch) return { fromDate: `${yearMatch[1]}-01-01`, toDate: `${yearMatch[1]}-12-31`, limit: 100000 };
  const monthMatch = /^(\d{4})-(\d{2})$/.exec(v);
  if (monthMatch) {
    const last = new Date(Number(monthMatch[1]), Number(monthMatch[2]), 0); // day 0 of next month = last day of this month
    return { fromDate: `${monthMatch[1]}-${monthMatch[2]}-01`, toDate: localDateStr(last), limit: null };
  }
  return { fromDate: null, toDate: null, limit: null }; // unknown -> today
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
                <span>Cache: {fmtNum(u.cache_create_tokens)}/{fmtNum(u.cache_read_tokens)}</span>
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
  const { fromDate, toDate, limit } = parseUsageTime(time);
  const params = new URLSearchParams();
  if (fromDate) params.set("from_date", fromDate);
  if (toDate) params.set("to_date", toDate);
  if (limit != null) params.set("limit", String(limit));
  const qs = params.toString();
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

  if (isLoading) return <ListLoading />;
  if (error && !data) return <ListError error={error} />;
  if (rows.length === 0) return <ListEmpty label="usage" />;

  return (
    <div className="h-full min-h-0 flex flex-col gap-3 px-3 pt-2 pb-2">
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
        <div className="flex-1 min-h-0 overflow-auto">
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

// Live per-model table columns (sort-independent of the pie's metric toggle). Numeric
// columns default to descending on first click, string columns ascending — matching the
// config table's clickable-header behavior. Cache is one column sorted by cache_create.
type LiveSortKey = "model" | "provider" | "all_tokens" | "cost" | "requests" | "input_tokens" | "output_tokens" | "cache_create_tokens";

const LIVE_COLUMNS: { key: LiveSortKey; label: string; numeric: boolean }[] = [
  { key: "model", label: "Model", numeric: false },
  { key: "provider", label: "Provider", numeric: false },
  { key: "all_tokens", label: "Tokens", numeric: true },
  { key: "cost", label: "Cost", numeric: true },
  { key: "requests", label: "Requests", numeric: true },
  { key: "input_tokens", label: "Input", numeric: true },
  { key: "output_tokens", label: "Output", numeric: true },
  { key: "cache_create_tokens", label: "Cache (cr/rd)", numeric: true },
];

function liveSortValue(a: ModelUsageAgg, key: LiveSortKey): string | number {
  if (key === "model") return a.model;
  if (key === "provider") return a.provider || "";
  return a[key];
}

// Per-model usage snapshot for Live mode: aggregates daily rows over the selected
// time range (source=crs only). Defaults to today when no range is given. A single
// donut pie driven by the shared metric sits above the metric toggle and per-model table.
function UsageTable({ time, metric, onMetricChange }: { time: string; metric: UsageMetric; onMetricChange: (m: UsageMetric) => void }) {
  const { fromDate, toDate, limit } = parseUsageTime(time);
  const params = new URLSearchParams();
  if (fromDate) params.set("from_date", fromDate);
  if (toDate) params.set("to_date", toDate);
  if (limit != null) params.set("limit", String(limit));
  const qs = params.toString();
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

  if (isLoading) return <ListLoading />;
  if (error && !data) return <ListError error={error} />;
  if (rows.length === 0) return <ListEmpty label="usage" />;

  return (
    <div className="h-full min-h-0 flex flex-col gap-3 px-3 pt-2 pb-2">
      <div className="shrink-0 rounded border border-sol-base02 bg-sol-base03 p-3">
        <div className="mb-2 flex items-start justify-between gap-3">
          <div>
            <div className="text-sol-base1 text-xs font-medium uppercase tracking-wide">
              {metric === "cost" ? "Cost" : metric === "requests" ? "Requests" : "Tokens"} by model
            </div>
            <div className="text-sol-base01 text-[10px]">Each slice is a model's share (top 7 + Other), source=crs</div>
          </div>
          {/* Single consolidated totals strip: the three headline numbers are the
              point of this view, so the value is the prominent element (large,
              tabular, accent) with a quiet uppercase caption stacked above it. */}
          <div className="shrink-0 flex items-start gap-4 tabular-nums">
            {([
              ["Tokens", fmtCompact(totals.all_tokens)],
              ["Cost", fmtCost(totals.cost)],
              ["Requests", fmtNum(totals.requests)],
            ] as const).map(([label, value], i) => (
              <Fragment key={label}>
                {i > 0 && <span className="self-stretch w-px bg-sol-base02" />}
                <span className="flex flex-col items-end whitespace-nowrap leading-tight">
                  <span className="text-sol-base01 text-[10px] uppercase tracking-wide">{label}</span>
                  <span className="text-sol-cyan text-xl font-semibold">{value}</span>
                </span>
              </Fragment>
            ))}
          </div>
        </div>
        {pieData.length === 0 ? (
          <div className="text-xs text-sol-base01/70 italic text-center py-12">No {metric} in this range</div>
        ) : (
          <ResponsiveContainer width="100%" height={240}>
            <PieChart margin={{ top: 4, right: 8, left: 8, bottom: 4 }}>
              <Pie data={pieData} dataKey="value" nameKey="model" cx="50%" cy="50%" outerRadius={70} innerRadius={36} stroke={SOL.base03} isAnimationActive={false}>
                {pieData.map((d, i) => (
                  <Cell key={d.model} fill={MODEL_COLORS[i % MODEL_COLORS.length]} />
                ))}
              </Pie>
              <Tooltip content={<UsagePieTooltip metric={metric} total={pieTotal} />} />
              <Legend
                layout="horizontal"
                verticalAlign="bottom"
                align="center"
                iconType="circle"
                wrapperStyle={{ fontSize: 10 }}
                formatter={(value) => <span style={{ color: SOL.base0 }}>{value}</span>}
              />
            </PieChart>
          </ResponsiveContainer>
        )}
        <MetricToggle metric={metric} onChange={onMetricChange} />
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto">
        <table className="w-full text-xs border-collapse">
          <thead className="sticky top-0 z-10">
            <tr className="text-sol-base01 text-left text-xs bg-sol-base03 border-b border-sol-base02">
              {LIVE_COLUMNS.map((col) => {
                const active = sortKey === col.key;
                return (
                  <th
                    key={col.key}
                    onClick={() => onSort(col.key)}
                    className={`py-1 px-1.5 bg-sol-base03 cursor-pointer select-none hover:text-sol-base1 ${col.numeric ? "text-right" : ""}`}
                  >
                    {col.label}{active ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {sortedRows.map((r) => (
              <tr key={r.model} className="border-b border-sol-base02/40 hover:bg-sol-base02/50">
                <td className="px-1.5 py-1 font-mono text-sol-base1">{r.model}</td>
                <td className="px-1.5 py-1 text-sol-base01 whitespace-nowrap">{r.provider || "-"}</td>
                <td className="px-1.5 py-1 text-right text-sol-base1 tabular-nums">{fmtCompact(r.all_tokens)}</td>
                <td className="px-1.5 py-1 text-right text-sol-base0 tabular-nums">{fmtCost(r.cost)}</td>
                <td className="px-1.5 py-1 text-right text-sol-base0 tabular-nums">{fmtNum(r.requests)}</td>
                <td className="px-1.5 py-1 text-right text-sol-base0 tabular-nums">{fmtCompact(r.input_tokens)}</td>
                <td className="px-1.5 py-1 text-right text-sol-base0 tabular-nums">{fmtCompact(r.output_tokens)}</td>
                <td className="px-1.5 py-1 text-right text-sol-base0 tabular-nums">{fmtCompact(r.cache_create_tokens)}/{fmtCompact(r.cache_read_tokens)}</td>
              </tr>
            ))}
            <tr className="font-medium">
              <td className="sticky bottom-0 px-1.5 py-1 text-sol-base1 bg-sol-base02 border-t border-sol-base02">Total</td>
              <td className="sticky bottom-0 px-1.5 py-1 text-sol-base01 bg-sol-base02 border-t border-sol-base02"></td>
              <td className="sticky bottom-0 px-1.5 py-1 text-right text-sol-base1 tabular-nums bg-sol-base02 border-t border-sol-base02">{fmtCompact(totals.all_tokens)}</td>
              <td className="sticky bottom-0 px-1.5 py-1 text-right text-sol-base1 tabular-nums bg-sol-base02 border-t border-sol-base02">{fmtCost(totals.cost)}</td>
              <td className="sticky bottom-0 px-1.5 py-1 text-right text-sol-base1 tabular-nums bg-sol-base02 border-t border-sol-base02">{fmtNum(totals.requests)}</td>
              <td className="sticky bottom-0 px-1.5 py-1 text-right text-sol-base1 tabular-nums bg-sol-base02 border-t border-sol-base02">{fmtCompact(totals.input_tokens)}</td>
              <td className="sticky bottom-0 px-1.5 py-1 text-right text-sol-base1 tabular-nums bg-sol-base02 border-t border-sol-base02">{fmtCompact(totals.output_tokens)}</td>
              <td className="sticky bottom-0 px-1.5 py-1 text-right text-sol-base1 tabular-nums bg-sol-base02 border-t border-sol-base02">{fmtCompact(totals.cache_create_tokens)}/{fmtCompact(totals.cache_read_tokens)}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function BotViewer() {
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
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [sortKey, setSortKey] = useState<SortKey>(loadSortKey());
  const [sortDir, setSortDir] = useState<SortDir>(loadSortDir());
  const [expandedName, setExpandedName] = useState<string | null>(null);
  const [form, setForm] = useState<BotFormState | null>(null);
  const [editing, setEditing] = useState<BotConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshingUsage, setRefreshingUsage] = useState(false);

  // Trigger the CRS model-usage sync, then revalidate the usage SWR caches
  // (LiveUsageView / OverTimeView are keyed on the model-daily URL).
  const refreshUsage = async () => {
    setRefreshingUsage(true);
    try {
      const res = await authFetch(`${API}/api/usage/sync`, { method: "POST" });
      if (!res.ok) throw new Error("Failed to sync model usage");
      await globalMutate(
        (key) => typeof key === "string" && key.startsWith(`${API}/api/usage/model-daily`),
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
              placeholder="today, week, month, year, all, 2024, 2024-05"
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
          usageMode === "over-time" ? (
            <UsageOverTimeView granularity={granularity} metric={usageMetric} time={usageTime} onMetricChange={setUsageMetric} />
          ) : (
            <UsageTable time={usageTime} metric={usageMetric} onMetricChange={setUsageMetric} />
          )
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
