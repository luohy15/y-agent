import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { API, authFetch, jsonFetcher as fetcher } from "../api";
import { ListEmpty, ListError, ListLoading } from "./ListStates";

interface BotConfig {
  name: string;
  base_url?: string;
  backend?: string | null;
  model?: string | null;
  description?: string | null;
  max_tokens?: number | null;
  custom_api_path?: string | null;
  has_api_key?: boolean;
  price_input?: number | null;
  price_output?: number | null;
  enabled?: boolean;
}

type SortKey = "name" | "backend" | "model" | "price_input" | "price_output";
type SortDir = "asc" | "desc";

const SORT_STORAGE_KEY = "botListSort";
const SORT_KEYS: SortKey[] = ["name", "backend", "model", "price_input", "price_output"];

// Read the persisted sort state, falling back to Name asc when absent/invalid.
function loadSort(): { key: SortKey; dir: SortDir } {
  try {
    const saved = JSON.parse(localStorage.getItem(SORT_STORAGE_KEY) || "");
    if (SORT_KEYS.includes(saved?.key) && (saved?.dir === "asc" || saved?.dir === "desc")) {
      return { key: saved.key, dir: saved.dir };
    }
  } catch { /* ignore */ }
  return { key: "name", dir: "asc" };
}

// Mirror the Python fmt_price helper: 4 significant figures, "-" when missing.
function fmtPrice(price?: number | null): string {
  if (price === null || price === undefined) return "-";
  return Number(price.toPrecision(4)).toString();
}

function botValue(bot: BotConfig, key: SortKey): string | number | null {
  switch (key) {
    case "name": return bot.name;
    case "backend": return bot.backend || "";
    case "model": return bot.model || "";
    case "price_input": return bot.price_input ?? null;
    case "price_output": return bot.price_output ?? null;
  }
}

function SortHeader({ label, columnKey, sortKey, sortDir, onSort, className }: {
  label: string;
  columnKey: SortKey;
  sortKey: SortKey;
  sortDir: SortDir;
  onSort: (key: SortKey) => void;
  className?: string;
}) {
  const active = sortKey === columnKey;
  return (
    <th
      onClick={() => onSort(columnKey)}
      className={`px-1.5 py-1 font-medium cursor-pointer select-none hover:text-sol-base1 whitespace-nowrap ${className || "text-left"}`}
    >
      <span className="inline-flex items-center gap-0.5">
        {label}
        {active && <span className="text-[0.55rem]">{sortDir === "asc" ? "▲" : "▼"}</span>}
      </span>
    </th>
  );
}

interface BotFormState {
  name: string;
  base_url: string;
  api_key: string;
  backend: string;
  model: string;
  description: string;
  max_tokens: string;
  custom_api_path: string;
}

interface BotListProps {
  isLoggedIn: boolean;
  onChange?: () => void;
}

function emptyForm(): BotFormState {
  return {
    name: "",
    base_url: "",
    api_key: "",
    backend: "",
    model: "",
    description: "",
    max_tokens: "",
    custom_api_path: "",
  };
}

function formFromBot(bot: BotConfig): BotFormState {
  return {
    name: bot.name,
    base_url: bot.base_url || "",
    api_key: "",
    backend: bot.backend || "",
    model: bot.model || "",
    description: bot.description || "",
    max_tokens: bot.max_tokens ? String(bot.max_tokens) : "",
    custom_api_path: bot.custom_api_path || "",
  };
}

async function apiJson(path: string, body: unknown) {
  const res = await authFetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const data = await res.json();
      msg = typeof data.detail === "string" ? data.detail : msg;
    } catch { /* ignore */ }
    throw new Error(msg);
  }
  return res.json();
}

function Field({ label, hint, required, children }: { label: string; hint?: string; required?: boolean; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-sol-base01 text-[0.65rem] uppercase tracking-wide">
        {label}{required ? " *" : ""}
      </span>
      {children}
      {hint && <span className="text-sol-base01/70 text-[0.65rem] leading-snug">{hint}</span>}
    </label>
  );
}

interface BotFormProps {
  form: BotFormState;
  setForm: (form: BotFormState) => void;
  isEdit: boolean;
  hasApiKey: boolean;
  busy: boolean;
  error: string | null;
  onSave: () => void;
  onCancel: () => void;
  onDelete?: () => void;
}

function BotForm({ form, setForm, isEdit, hasApiKey, busy, error, onSave, onCancel, onDelete }: BotFormProps) {
  const canSave = form.name.trim().length > 0 && !busy;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onCancel}>
      <div
        className="w-full max-w-lg bg-sol-base03 border border-sol-base01 rounded-lg shadow-2xl overflow-hidden text-xs max-h-[90vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-4 py-3 border-b border-sol-base02 flex items-center justify-between shrink-0">
          <div className="text-sol-base1 text-sm font-semibold">{isEdit ? "Edit bot" : "New bot"}</div>
          <button onClick={onCancel} className="text-sol-base01 hover:text-sol-base1 cursor-pointer text-sm leading-none" title="Close">&times;</button>
        </div>
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
          {error && <div className="text-sol-red border border-sol-red/30 bg-sol-red/10 rounded px-2 py-1">{error}</div>}
          <div className="grid grid-cols-2 gap-3">
            <Field label="Name" required>
              <input
                type="text"
                value={form.name}
                disabled={isEdit}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="w-full px-2 py-1 bg-sol-base02 border border-sol-base01 rounded text-sol-base0 outline-none focus:border-sol-blue disabled:opacity-70"
                autoFocus
              />
            </Field>
            <Field label="Backend">
              <select
                value={form.backend}
                onChange={(e) => setForm({ ...form, backend: e.target.value })}
                className="w-full px-2 py-1 bg-sol-base02 border border-sol-base01 rounded text-sol-base0 outline-none focus:border-sol-blue"
              >
                <option value="">(default)</option>
                <option value="codex">codex</option>
                <option value="claude_code">claude_code</option>
                <option value="gemini">gemini</option>
                <option value="openai">openai</option>
              </select>
            </Field>
          </div>
          <Field label="Model">
            <input
              type="text"
              value={form.model}
              onChange={(e) => setForm({ ...form, model: e.target.value })}
              placeholder="openai/gpt-5.2"
              className="w-full px-2 py-1 bg-sol-base02 border border-sol-base01 rounded text-sol-base0 font-mono outline-none focus:border-sol-blue"
            />
          </Field>
          <Field label="Base URL">
            <input
              type="text"
              value={form.base_url}
              onChange={(e) => setForm({ ...form, base_url: e.target.value })}
              className="w-full px-2 py-1 bg-sol-base02 border border-sol-base01 rounded text-sol-base0 font-mono outline-none focus:border-sol-blue"
            />
          </Field>
          <Field label="API key" hint={isEdit && hasApiKey ? "Stored. Leave blank to keep the current key." : "Stored server-side."}>
            <input
              type="password"
              value={form.api_key}
              onChange={(e) => setForm({ ...form, api_key: e.target.value })}
              autoComplete="new-password"
              className="w-full px-2 py-1 bg-sol-base02 border border-sol-base01 rounded text-sol-base0 font-mono outline-none focus:border-sol-blue"
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Max tokens">
              <input
                type="number"
                min="1"
                value={form.max_tokens}
                onChange={(e) => setForm({ ...form, max_tokens: e.target.value })}
                className="w-full px-2 py-1 bg-sol-base02 border border-sol-base01 rounded text-sol-base0 outline-none focus:border-sol-blue"
              />
            </Field>
            <Field label="API path">
              <input
                type="text"
                value={form.custom_api_path}
                onChange={(e) => setForm({ ...form, custom_api_path: e.target.value })}
                placeholder="/chat/completions"
                className="w-full px-2 py-1 bg-sol-base02 border border-sol-base01 rounded text-sol-base0 font-mono outline-none focus:border-sol-blue"
              />
            </Field>
          </div>
          <Field label="Description">
            <textarea
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              rows={3}
              className="w-full px-2 py-1 bg-sol-base02 border border-sol-base01 rounded text-sol-base0 outline-none focus:border-sol-blue resize-y"
            />
          </Field>
        </div>
        <div className="flex items-center gap-2 px-4 py-3 border-t border-sol-base02 shrink-0">
          {isEdit && onDelete && form.name !== "default" && (
            <button
              onClick={onDelete}
              disabled={busy}
              className="px-3 py-1.5 rounded text-xs bg-sol-red/20 text-sol-red hover:bg-sol-red/30 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer border border-sol-red/40"
            >
              Delete
            </button>
          )}
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={onCancel}
              disabled={busy}
              className="px-3 py-1.5 rounded text-xs text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02 disabled:opacity-50 cursor-pointer"
            >
              Cancel
            </button>
            <button
              onClick={onSave}
              disabled={!canSave}
              className="px-3 py-1.5 rounded text-xs bg-sol-blue/20 text-sol-blue hover:bg-sol-blue/30 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer border border-sol-blue/40"
            >
              {busy ? "Saving..." : isEdit ? "Save" : "Create"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function BotList({ isLoggedIn, onChange }: BotListProps) {
  const [spinning, setSpinning] = useState(false);
  const [query, setQuery] = useState("");
  const [form, setForm] = useState<BotFormState | null>(null);
  const [editing, setEditing] = useState<BotConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>(() => loadSort().key);
  const [sortDir, setSortDir] = useState<SortDir>(() => loadSort().dir);

  const { data, error: loadError, isLoading, mutate } = useSWR<BotConfig[]>(
    isLoggedIn ? `${API}/api/bot/list` : null,
    fetcher,
  );

  const bots = useMemo(() => data || [], [data]);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return bots;
    return bots.filter((b) =>
      b.name.toLowerCase().includes(q) ||
      (b.model || "").toLowerCase().includes(q) ||
      (b.backend || "").toLowerCase().includes(q),
    );
  }, [bots, query]);

  const sorted = useMemo(() => {
    const dirMul = sortDir === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      const av = botValue(a, sortKey);
      const bv = botValue(b, sortKey);
      // Missing values (null price / empty string) always sort last, regardless of direction.
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
    localStorage.setItem(SORT_STORAGE_KEY, JSON.stringify({ key: sortKey, dir: sortDir }));
  }, [sortKey, sortDir]);

  useEffect(() => {
    if (!form) {
      setBusy(false);
      setError(null);
    }
  }, [form]);

  const refresh = async () => {
    setSpinning(true);
    await mutate();
    onChange?.();
    window.setTimeout(() => setSpinning(false), 500);
  };

  const openNew = () => {
    setEditing(null);
    setForm(emptyForm());
  };

  const openEdit = async (bot: BotConfig) => {
    setBusy(true);
    setError(null);
    try {
      const full = await fetcher(`${API}/api/bot/config?name=${encodeURIComponent(bot.name)}`);
      setEditing(full);
      setForm(formFromBot(full));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
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
      ...(!editing || form.api_key ? { api_key: form.api_key } : {}),
    };
    try {
      await apiJson(editing ? "/api/bot/update" : "/api/bot", body);
      setForm(null);
      setEditing(null);
      await mutate();
      onChange?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const toggleEnabled = async (bot: BotConfig) => {
    const action = bot.enabled ? "disable" : "enable";
    try {
      await apiJson(`/api/bot/${action}`, { name: bot.name });
      await mutate();
      onChange?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const deleteCurrent = async () => {
    if (!editing || busy) return;
    if (!window.confirm(`Delete bot '${editing.name}'?`)) return;
    setBusy(true);
    setError(null);
    try {
      await apiJson("/api/bot/delete", { name: editing.name });
      setForm(null);
      setEditing(null);
      await mutate();
      onChange?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  if (!isLoggedIn) {
    return <div className="p-3 text-xs text-sol-base01">Sign in to manage bots.</div>;
  }

  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="p-2 border-b border-sol-base02 shrink-0 flex items-center gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search bots"
          className="min-w-0 flex-1 px-2 py-1 bg-sol-base02 border border-sol-base01 rounded text-xs text-sol-base0 outline-none focus:border-sol-blue"
        />
        <button
          onClick={refresh}
          className="w-7 h-7 flex items-center justify-center rounded text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02 cursor-pointer"
          title="Refresh bots"
        >
          <svg className={`w-3.5 h-3.5 ${spinning ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" /><path d="M3 21v-5h5" /><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" /><path d="M16 8h5V3" />
          </svg>
        </button>
        <button
          onClick={openNew}
          className="w-7 h-7 flex items-center justify-center rounded text-sol-blue hover:bg-sol-blue/10 cursor-pointer"
          title="New bot"
        >
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 5v14" /><path d="M5 12h14" />
          </svg>
        </button>
      </div>
      <div className="flex-1 min-h-0 overflow-auto p-2">
        {isLoading ? (
          <ListLoading />
        ) : loadError && !data ? (
          <ListError error={loadError} />
        ) : filtered.length === 0 ? (
          query ? <p className="text-sol-base01 italic p-2">No matching bots</p> : <ListEmpty label="bots" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[0.65rem] border-collapse">
              <thead>
                <tr className="text-sol-base01 border-b border-sol-base02">
                  <SortHeader label="Name" columnKey="name" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
                  <SortHeader label="Backend" columnKey="backend" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
                  <SortHeader label="Model" columnKey="model" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
                  <SortHeader label="In/1M" columnKey="price_input" sortKey={sortKey} sortDir={sortDir} onSort={onSort} className="text-right" />
                  <SortHeader label="Out/1M" columnKey="price_output" sortKey={sortKey} sortDir={sortDir} onSort={onSort} className="text-right" />
                  <th className="px-1.5 py-1 w-8" />
                </tr>
              </thead>
              <tbody>
                {sorted.map((bot) => (
                  <tr
                    key={bot.name}
                    onClick={() => openEdit(bot)}
                    className="border-b border-sol-base02/40 hover:bg-sol-base02/50 cursor-pointer"
                  >
                    <td className="px-1.5 py-1 max-w-[8rem]">
                      <span className="inline-flex items-center gap-1 min-w-0">
                        <span className="text-sol-base1 font-medium truncate">{bot.name}</span>
                        {bot.name === "default" && <span className="text-[0.55rem] px-1 rounded bg-sol-base02 text-sol-base01 shrink-0">def</span>}
                        {bot.has_api_key && <span className="text-[0.55rem] px-1 rounded bg-sol-green/15 text-sol-green shrink-0">key</span>}
                      </span>
                    </td>
                    <td className="px-1.5 py-1 text-sol-base01 whitespace-nowrap">{bot.backend || "-"}</td>
                    <td className="px-1.5 py-1 font-mono text-sol-base01 max-w-[10rem] truncate">{bot.model || "-"}</td>
                    <td className="px-1.5 py-1 text-right text-sol-base0 whitespace-nowrap tabular-nums">{fmtPrice(bot.price_input)}</td>
                    <td className="px-1.5 py-1 text-right text-sol-base0 whitespace-nowrap tabular-nums">{fmtPrice(bot.price_output)}</td>
                    <td className="px-1.5 py-1 text-center">
                      <button
                        onClick={(e) => { e.stopPropagation(); toggleEnabled(bot); }}
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
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {form && (
        <BotForm
          form={form}
          setForm={setForm}
          isEdit={!!editing}
          hasApiKey={!!editing?.has_api_key}
          busy={busy}
          error={error}
          onSave={save}
          onCancel={() => { if (!busy) { setForm(null); setEditing(null); } }}
          onDelete={editing ? deleteCurrent : undefined}
        />
      )}
      {!form && error && <div className="p-2 text-xs text-sol-red border-t border-sol-base02">{error}</div>}
    </div>
  );
}
