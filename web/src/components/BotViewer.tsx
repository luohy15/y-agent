import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { API, jsonFetcher as fetcher } from "../api";
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

export default function BotViewer() {
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [form, setForm] = useState<BotFormState | null>(null);
  const [editing, setEditing] = useState<BotConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      // Missing values (null number / empty string) always sort last, regardless of direction.
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
    if (!form) {
      setBusy(false);
      setError(null);
    }
  }, [form]);

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
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
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
      <div className="flex-1 min-h-0 overflow-auto p-3">
        {isLoading ? (
          <ListLoading />
        ) : loadError && !data ? (
          <ListError error={loadError} />
        ) : filtered.length === 0 ? (
          query || typeFilter !== "all" ? <p className="text-sol-base01 italic p-2">No matching bots</p> : <ListEmpty label="bots" />
        ) : (
          <table className="w-full text-xs border-collapse">
            <thead className="sticky top-0 bg-sol-base03">
              <tr className="text-sol-base01 border-b border-sol-base02">
                {COLUMNS.map((col) => {
                  const active = sortKey === col.key;
                  return (
                    <th
                      key={col.key}
                      onClick={() => onSort(col.key)}
                      className={`px-2 py-1 font-medium cursor-pointer select-none hover:text-sol-base1 whitespace-nowrap ${col.align === "right" ? "text-right" : "text-left"}`}
                    >
                      <span className="inline-flex items-center gap-0.5">
                        {col.label}
                        {active && <span className="text-[0.55rem]">{sortDir === "asc" ? "▲" : "▼"}</span>}
                      </span>
                    </th>
                  );
                })}
                <th className="px-2 py-1 w-10 text-center font-medium">On</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((bot) => (
                <tr
                  key={bot.name}
                  onClick={() => openEdit(bot)}
                  className="border-b border-sol-base02/40 hover:bg-sol-base02/50 cursor-pointer"
                >
                  <td className="px-2 py-1">
                    <span className="inline-flex items-center gap-1 min-w-0">
                      <span className="text-sol-base1 font-medium">{bot.name}</span>
                      {bot.name === "default" && <span className="text-[0.55rem] px-1 rounded bg-sol-base02 text-sol-base01 shrink-0">def</span>}
                      {bot.has_api_key && <span className="text-[0.55rem] px-1 rounded bg-sol-green/15 text-sol-green shrink-0">key</span>}
                    </span>
                  </td>
                  <td className="px-2 py-1 text-sol-base01 whitespace-nowrap">{bot.backend || "-"}</td>
                  <td className="px-2 py-1 font-mono text-sol-base01">{bot.model || "-"}</td>
                  <td className="px-2 py-1 text-sol-base0 whitespace-nowrap">{bot.type || "agent"}</td>
                  <td className="px-2 py-1 text-sol-base01 whitespace-nowrap">{bot.tier || "-"}</td>
                  <td className="px-2 py-1 text-right text-sol-base0 whitespace-nowrap tabular-nums">{fmtPrice(bot.route_weight)}</td>
                  <td className="px-2 py-1 text-right text-sol-base0 whitespace-nowrap tabular-nums">{fmtPrice(bot.price_input)}</td>
                  <td className="px-2 py-1 text-right text-sol-base0 whitespace-nowrap tabular-nums">{fmtPrice(bot.price_output)}</td>
                  <td className="px-2 py-1 text-center">
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
