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

const DEFAULT_BASE_URL = "https://openrouter.ai/api/v1";

function emptyForm(): BotFormState {
  return {
    name: "",
    base_url: DEFAULT_BASE_URL,
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
    base_url: bot.base_url || DEFAULT_BASE_URL,
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
  const canSave = form.name.trim().length > 0 && form.model.trim().length > 0 && !busy;
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
          <Field label="Model" required>
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
    if (!form.model.trim()) { setError("Model is required"); return; }
    setBusy(true);
    setError(null);
    const body = {
      name: form.name.trim(),
      base_url: form.base_url.trim() || DEFAULT_BASE_URL,
      backend: form.backend || null,
      model: form.model.trim(),
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
      <div className="flex-1 min-h-0 overflow-y-auto p-2">
        {isLoading ? (
          <ListLoading />
        ) : loadError && !data ? (
          <ListError error={loadError} />
        ) : filtered.length === 0 ? (
          query ? <p className="text-sol-base01 italic p-2">No matching bots</p> : <ListEmpty label="bots" />
        ) : (
          <div className="space-y-1">
            {filtered.map((bot) => (
              <button
                key={bot.name}
                onClick={() => openEdit(bot)}
                className="w-full text-left flex flex-col gap-1 p-2 rounded border border-transparent hover:border-sol-base01 hover:bg-sol-base02/50 cursor-pointer"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-sol-base1 text-xs font-medium truncate min-w-0">{bot.name}</span>
                  {bot.name === "default" && <span className="text-[0.6rem] px-1.5 py-0.5 rounded bg-sol-base02 text-sol-base01 shrink-0">default</span>}
                  {bot.has_api_key && <span className="ml-auto text-[0.6rem] px-1.5 py-0.5 rounded bg-sol-green/15 text-sol-green shrink-0">key</span>}
                </div>
                <div className="flex items-center gap-1.5 min-w-0 text-[0.68rem] text-sol-base01 truncate">
                  <span className="font-mono truncate shrink-0 max-w-[45%]">{bot.model || "no model"}</span>
                  {(bot.backend || bot.description) && (
                    <>
                      <span className="text-sol-base01/60 shrink-0">·</span>
                      <span className="text-[0.65rem] text-sol-base01/80 truncate min-w-0">
                        {[bot.backend, bot.description].filter(Boolean).join(" - ")}
                      </span>
                    </>
                  )}
                </div>
              </button>
            ))}
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
