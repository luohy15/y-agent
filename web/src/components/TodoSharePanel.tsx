import { useState } from "react";
import { API, authFetch } from "../api";
import type { ExistingShare } from "./SharePopover";

const kinds = ["chat", "note", "link"] as const;
type Kind = typeof kinds[number];
type Selection = Record<Kind, string[]>;
type Options = Record<Kind, { id: string; label: string }[]>;
export interface OutgoingGrant {
  todo_id: string;
  recipient: string;
  share_id: string;
  items: { kind: Kind; ref_id: string }[];
}
interface Props {
  todoId: string;
  publicShare: ExistingShare | null;
  grants: OutgoingGrant[];
  options: Options;
  refresh: () => Promise<unknown>;
}
type Audience = "public" | "private";
type Password = "keep" | "none" | "generate" | "custom";
const action = "rounded bg-sol-base02 px-2 py-1 text-sol-cyan disabled:opacity-50";
const input = "w-full rounded bg-sol-base02 p-2 text-sol-base1";

function currentPicks(options: Options, audience: Audience, share: Props["publicShare"], grant?: OutgoingGrant): Selection {
  const ids = (kind: Kind) => options[kind].map(item => item.id).filter(id =>
    audience === "public" ? (share?.selection?.[`${kind}_ids`]?.includes(id) ?? true)
      : grant?.items.some(item => item.kind === kind && item.ref_id === id));
  return { chat: ids("chat"), note: ids("note"), link: ids("link") };
}

async function request(path: string, method: "POST" | "DELETE", data?: object) {
  const res = await authFetch(`${API}/api/${path}`, {
    method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
  });
  const json = await res.json();
  if (!res.ok) throw new Error(typeof json.detail === "string" ? json.detail : `Share request failed (${res.status})`);
  return json;
}

export default function TodoSharePanel({ todoId, publicShare, grants, options, refresh }: Props) {
  const [audience, setAudience] = useState<Audience>("public");
  const [form, setForm] = useState(!publicShare && !grants.length);
  const [recipient, setRecipient] = useState("");
  const [editing, setEditing] = useState(false);
  const [picks, setPicks] = useState(() => currentPicks(options, "public", publicShare));
  const [password, setPassword] = useState<Password>("none");
  const [custom, setCustom] = useState("");
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState("");
  const url = (id: string) => `${window.location.origin}/t/${id}`;
  const edit = (next: Audience, grant?: OutgoingGrant) => {
    setAudience(next); setForm(true); setEditing(!!grant);
    setRecipient(grant?.recipient ?? ""); setPicks(currentPicks(options, next, publicShare, grant));
    setPassword(publicShare?.has_password ? "keep" : "none"); setCustom(""); setFeedback(""); setConfirm("");
  };
  const run = async (operation: () => Promise<string>) => {
    setBusy(true); setFeedback("");
    try { setFeedback(await operation()); }
    catch (err) { setFeedback(err instanceof Error ? err.message : "Share request failed"); }
    finally { setBusy(false); }
  };
  const copy = async (value: string) => {
    try { await navigator.clipboard.writeText(value); return "Link copied"; }
    catch { return `Copy this link: ${value}`; }
  };
  const save = async () => {
    let message: string;
    if (audience === "private") {
      const result = await request("todo/share", "POST", { todo_id: todoId, to: recipient.trim(),
        notes: picks.note, chats: picks.chat, links: picks.link });
      message = `Shared with ${recipient.trim()}. Notification ${result.notified ? "sent" : "not delivered"}.`;
    } else {
      const result = await request("trace/share", "POST", { trace_id: todoId,
        note_ids: picks.note, chat_ids: picks.chat, link_ids: picks.link,
        ...(password === "generate" ? { generate_password: true } : password === "keep" ? {} :
          { password: password === "custom" ? custom : "" }),
      });
      const secret = result.password ?? (password === "custom" ? custom : "");
      message = await copy(url(result.share_id) + (secret ? `?p=${encodeURIComponent(secret)}` : ""));
    }
    await refresh(); setForm(false); return message;
  };
  const row = (id: string, label: string, selection: Selection, grant?: OutgoingGrant) => (
    <div key={id} className="border-b border-sol-base02 py-2">
      <strong className="break-all">{label}</strong>
      <div className="text-sol-base01">{kinds.map(kind => `${selection[kind].length} ${kind}(s)`).join(" · ")}</div>
      {!grant && <div className="break-all">{url(id)} {publicShare?.has_password && "[password]"}</div>}
      <div className="mt-1 flex gap-1">
        {!grant && <button className={action} onClick={() => run(() => copy(url(id)))}>Copy link</button>}
        <button className={action} onClick={() => edit(grant ? "private" : "public", grant)}>Edit</button>
        <button className={action} onClick={() => {
          if (confirm !== id) { setConfirm(id); return; }
          void run(async () => {
            await request(grant ? `todo/share?${new URLSearchParams({ todo_id: todoId, to: grant.recipient })}`
              : `trace/share?${new URLSearchParams({ share_id: id })}`, "DELETE");
            await refresh(); setConfirm(""); return "Unshared";
          });
        }}>{confirm === id ? "Confirm unshare" : "Unshare"}</button>
      </div>
    </div>
  );
  return <fieldset disabled={busy} className="space-y-2 text-sol-base0">
    <legend className="font-semibold text-sol-base1">{form ? "Share" : "Existing shares"}</legend>
    {!form ? <>
      {publicShare && row(publicShare.share_id, "Public link", currentPicks(options, "public", publicShare))}
      {grants.map(grant => row(grant.share_id, grant.recipient, currentPicks(options, "private", null, grant), grant))}
      <button className={action} onClick={() => edit(publicShare ? "private" : "public")}>+ Add share</button>
    </> : <>
      <div className="flex gap-1">{(["public", "private"] as const).map(next =>
        <button key={next} aria-pressed={next === audience} className={`${action} flex-1 aria-pressed:text-sol-base3`}
          onClick={() => next !== audience && edit(next)}>{next === "public" ? "Public link" : "Specific user"}</button>)}</div>
      {audience === "private" && <label>Share with<input className={input} placeholder="Email or user ID"
        readOnly={editing} value={recipient} onChange={event => setRecipient(event.target.value)} /></label>}
      {kinds.map(kind => {
        const all = picks[kind].length === options[kind].length;
        const choose = (ids: string[]) => setPicks(prev => ({ ...prev, [kind]: ids }));
        return <section key={kind}><div className="flex justify-between">
          <strong className="capitalize">{kind}s ({options[kind].length})</strong>
          {!!options[kind].length && <button className="text-sol-cyan" onClick={() => choose(all ? [] : options[kind].map(item => item.id))}>
            {all ? "Clear all" : "Select all"}</button>}
        </div><div className="max-h-24 overflow-y-auto">{options[kind].map(item =>
          <label key={item.id} className="flex items-center gap-2 py-0.5">
            <input type="checkbox" checked={picks[kind].includes(item.id)} onChange={event => choose(
              event.target.checked ? [...picks[kind], item.id] : picks[kind].filter(id => id !== item.id))}/>
            <span className="truncate">{item.label}</span><small className="ml-auto">#{item.id}</small>
          </label>)}</div></section>;
      })}
      {audience === "public" && <details><summary>Password options</summary>
        <select aria-label="Link password" className={input} value={password} onChange={event => setPassword(event.target.value as Password)}>
          {publicShare?.has_password && <option value="keep">Keep existing password</option>}
          <option value="none">No password</option><option value="generate">Auto-generate password</option>
          <option value="custom">Custom password</option>
        </select>{password === "custom" && <input aria-label="Custom password" className={input}
          value={custom} onChange={event => setCustom(event.target.value)} />}</details>}
      <div>{kinds.reduce((total, kind) => total + picks[kind].length, 0)} items selected</div>
      <button className="w-full rounded bg-sol-blue py-1 font-semibold text-sol-base03 disabled:opacity-50"
        disabled={audience === "private" ? !recipient.trim() : password === "custom" && !custom.trim()}
        onClick={() => run(save)}>{busy ? "Saving…" : audience === "public" ? "Copy link" : editing ? "Save changes" : "Share"}</button>
      {(publicShare || grants.length > 0) && <button className={action} onClick={() => setForm(false)}>Existing shares</button>}
    </>}
    <div role="status" className="break-all">{feedback}</div>
  </fieldset>;
}
