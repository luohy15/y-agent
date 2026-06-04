import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { API, authFetch, jsonFetcher as fetcher } from "../api";
import { ListEmpty, ListError, ListLoading } from "./ListStates";

export interface BotConfig {
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
  tier?: string | null;
  type?: string | null;
  route_weight?: number | null;
  enabled?: boolean;
  ref_bot_name?: string | null;
}

type TypeFilter = "agent" | "model";

const TYPE_FILTER_STORAGE_KEY = "botListTypeFilter";

// Read the persisted type filter, defaulting to "agent" when absent/invalid.
function loadTypeFilter(): TypeFilter {
  const saved = localStorage.getItem(TYPE_FILTER_STORAGE_KEY);
  return saved === "model" ? "model" : "agent";
}

// Mirror the Python fmt_price helper: 4 significant figures, "-" when missing.
export function fmtPrice(price?: number | null): string {
  if (price === null || price === undefined) return "-";
  return Number(price.toPrecision(4)).toString();
}

export interface BotFormState {
  name: string;
  base_url: string;
  api_key: string;
  backend: string;
  model: string;
  description: string;
  max_tokens: string;
  custom_api_path: string;
  type: string;
  tier: string;
  route_weight: string;
  ref_bot_name: string;
}

interface BotListProps {
  isLoggedIn: boolean;
  onChange?: () => void;
}

export function emptyForm(): BotFormState {
  return {
    name: "",
    base_url: "",
    api_key: "",
    backend: "",
    model: "",
    description: "",
    max_tokens: "",
    custom_api_path: "",
    type: "agent",
    tier: "",
    route_weight: "",
    ref_bot_name: "",
  };
}

export function formFromBot(bot: BotConfig): BotFormState {
  return {
    name: bot.name,
    base_url: bot.base_url || "",
    api_key: "",
    backend: bot.backend || "",
    model: bot.model || "",
    description: bot.description || "",
    max_tokens: bot.max_tokens ? String(bot.max_tokens) : "",
    custom_api_path: bot.custom_api_path || "",
    type: bot.type || "agent",
    tier: bot.tier || "",
    route_weight: bot.route_weight ? String(bot.route_weight) : "",
    ref_bot_name: bot.ref_bot_name || "",
  };
}

export async function apiJson(path: string, body: unknown) {
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

export function Field({ label, hint, required, children }: { label: string; hint?: string; required?: boolean; children: React.ReactNode }) {
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

export interface BotFormProps {
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

export function BotForm({ form, setForm, isEdit, hasApiKey, busy, error, onSave, onCancel, onDelete }: BotFormProps) {
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
          <Field label="Ref Bot Name" hint="Pointer to another bot config (e.g. 'codex'). Leave empty for a real bot.">
            <input
              type="text"
              value={form.ref_bot_name}
              onChange={(e) => setForm({ ...form, ref_bot_name: e.target.value })}
              placeholder="codex"
              className="w-full px-2 py-1 bg-sol-base02 border border-sol-base01 rounded text-sol-base0 font-mono outline-none focus:border-sol-blue"
            />
          </Field>
          <Field label="Model">
            <input
              type="text"
              value={form.model}
              onChange={(e) => setForm({ ...form, model: e.target.value })}
              placeholder="openai/gpt-5.2"
              className="w-full px-2 py-1 bg-sol-base02 border border-sol-base01 rounded text-sol-base0 font-mono outline-none focus:border-sol-blue"
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Type">
              <select
                value={form.type}
                onChange={(e) => setForm({ ...form, type: e.target.value })}
                className="w-full px-2 py-1 bg-sol-base02 border border-sol-base01 rounded text-sol-base0 outline-none focus:border-sol-blue"
              >
                <option value="agent">agent</option>
                <option value="model">model</option>
              </select>
            </Field>
            <Field label="Tier">
              <input
                type="text"
                value={form.tier}
                onChange={(e) => setForm({ ...form, tier: e.target.value })}
                className="w-full px-2 py-1 bg-sol-base02 border border-sol-base01 rounded text-sol-base0 outline-none focus:border-sol-blue"
              />
            </Field>
          </div>
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
            <Field label="Weight">
              <input
                type="number"
                step="any"
                value={form.route_weight}
                onChange={(e) => setForm({ ...form, route_weight: e.target.value })}
                className="w-full px-2 py-1 bg-sol-base02 border border-sol-base01 rounded text-sol-base0 outline-none focus:border-sol-blue"
              />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
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
  const [typeFilter, setTypeFilter] = useState<TypeFilter>(loadTypeFilter);

  const { data, error: loadError, isLoading, mutate } = useSWR<BotConfig[]>(
    isLoggedIn ? `${API}/api/bot/list` : null,
    fetcher,
  );

  const bots = useMemo(() => data || [], [data]);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return bots.filter((b) => {
      if ((b.type || "agent") !== typeFilter) return false;
      if (!q) return true;
      return (
        b.name.toLowerCase().includes(q) ||
        (b.model || "").toLowerCase().includes(q) ||
        (b.backend || "").toLowerCase().includes(q)
      );
    });
  }, [bots, query, typeFilter]);

  useEffect(() => {
    localStorage.setItem(TYPE_FILTER_STORAGE_KEY, typeFilter);
  }, [typeFilter]);

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
      type: form.type || null,
      tier: form.tier || null,
      route_weight: form.route_weight ? Number(form.route_weight) : null,
      ref_bot_name: form.ref_bot_name.trim() || null,
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
        <div className="flex items-center gap-1 shrink-0">
          {(["agent", "model"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setTypeFilter(f)}
              className={`px-2 py-1 rounded text-xs cursor-pointer ${
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
                <tr className="text-sol-base01 border-b border-sol-base02 text-left">
                  <th className="px-1.5 py-1 font-medium whitespace-nowrap">Name</th>
                  <th className="px-1.5 py-1 font-medium whitespace-nowrap">Backend</th>
                  <th className="px-1.5 py-1 font-medium whitespace-nowrap">Model</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((bot) => (
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
                        {bot.ref_bot_name && <span className="text-[0.55rem] px-1 rounded bg-sol-blue/15 text-sol-blue shrink-0" title={bot.ref_bot_name}>ref</span>}
                      </span>
                    </td>
                    <td className="px-1.5 py-1 text-sol-base01 whitespace-nowrap">{bot.backend || "-"}</td>
                    <td className="px-1.5 py-1 font-mono text-sol-base01 max-w-[10rem] truncate">{bot.model || "-"}</td>
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
