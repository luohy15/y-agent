import { Fragment, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
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

const SORT_KEY_STORAGE_KEY = "botViewSortKey";
const SORT_DIR_STORAGE_KEY = "botViewSortDir";

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

export default function BotViewer() {
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [sortKey, setSortKey] = useState<SortKey>(loadSortKey());
  const [sortDir, setSortDir] = useState<SortDir>(loadSortDir());
  const [expandedName, setExpandedName] = useState<string | null>(null);
  const [form, setForm] = useState<BotFormState | null>(null);
  const [editing, setEditing] = useState<BotConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      <div className="p-2 border-b border-sol-base02 shrink-0 flex items-center gap-2 flex-wrap">
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
      </div>
      <div className="flex-1 min-h-0 overflow-auto" onClick={(e) => { if (expandedName && !(e.target as HTMLElement).closest('[data-bot-card]')) setExpandedName(null); }}>
        {isLoading ? (
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
