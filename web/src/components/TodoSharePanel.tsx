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
  shared_at?: string;
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
const blank: Selection = { chat: [], note: [], link: [] };
const sectionName: Record<Kind, string> = { chat: "Chats", note: "Notes", link: "Links" };

function currentPicks(options: Options, audience: Audience, share: Props["publicShare"], grant?: OutgoingGrant): Selection {
  const ids = (kind: Kind) => options[kind].map(item => item.id).filter(id =>
    audience === "public" ? (share?.selection?.[`${kind}_ids`]?.includes(id) ?? true)
      : grant?.items.some(item => item.kind === kind && item.ref_id === id));
  return { chat: ids("chat"), note: ids("note"), link: ids("link") };
}

function counts(selection: Selection) {
  const parts = (["note", "chat", "link"] as const)
    .map(kind => [selection[kind].length, kind] as const)
    .filter(([count]) => count > 0)
    .map(([count, kind]) => `${count} ${kind}${count === 1 ? "" : "s"}`);
  return parts.length ? parts.join(" · ") : "No items";
}

function sharedWhen(value?: string) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return ` · shared ${date.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })}`;
}

async function request(path: string, method: "POST" | "DELETE", data?: object) {
  const res = await authFetch(`${API}/api/${path}`, {
    method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
  });
  const json = await res.json();
  if (!res.ok) throw new Error(typeof json.detail === "string" ? json.detail : `Share request failed (${res.status})`);
  return json;
}

function NoteIcon() {
  return <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /></svg>;
}

function LinkIcon() {
  return <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" /><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" /></svg>;
}

export default function TodoSharePanel({ todoId, publicShare, grants, options, refresh }: Props) {
  const [audience, setAudience] = useState<Audience>("public");
  const [form, setForm] = useState(!publicShare && !grants.length);
  const [recipient, setRecipient] = useState("");
  const [editing, setEditing] = useState(false);
  const [picks, setPicks] = useState<Selection>(blank);
  const [password, setPassword] = useState<Password>("none");
  const [canKeep, setCanKeep] = useState(false);
  const [custom, setCustom] = useState("");
  const [feedback, setFeedback] = useState("");
  const [tone, setTone] = useState<"ok" | "bad">("ok");
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [copied, setCopied] = useState("");
  const selectedCount = kinds.reduce((total, kind) => total + picks[kind].length, 0);
  const url = (id: string) => `${window.location.origin}/t/${id}`;
  const clearNotice = () => { setFeedback(""); setConfirm(""); setCopied(""); };
  const openNew = (next: Audience) => {
    const keep = next === "public" && !!publicShare?.has_password;
    setAudience(next); setForm(true); setEditing(false); setRecipient(""); setPicks(blank);
    setPassword(keep ? "keep" : "none"); setCanKeep(keep); setCustom(""); clearNotice();
  };
  const openEdit = (next: Audience, grant?: OutgoingGrant) => {
    const keep = next === "public" && !!publicShare?.has_password;
    setAudience(next); setForm(true); setEditing(!!grant); setRecipient(grant?.recipient ?? "");
    setPicks(currentPicks(options, next, publicShare, grant));
    setPassword(keep ? "keep" : "none"); setCanKeep(keep); setCustom(""); clearNotice();
  };
  const run = async (operation: () => Promise<string>) => {
    setBusy(true); setFeedback("");
    try { setTone("ok"); setFeedback(await operation()); }
    catch (err) { setTone("bad"); setFeedback(err instanceof Error ? err.message : "Share request failed"); }
    finally { setBusy(false); }
  };
  const copy = async (id: string) => {
    const value = url(id);
    try { await navigator.clipboard.writeText(value); setCopied(id); return "Link copied"; }
    catch { setCopied(""); return `Copy this link: ${value}`; }
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
      const value = url(result.share_id) + (secret ? `?p=${encodeURIComponent(secret)}` : "");
      try { await navigator.clipboard.writeText(value); message = "Link copied"; }
      catch { message = `Copy this link: ${value}`; }
    }
    await refresh(); setForm(false); return message;
  };
  const unshare = (id: string, grant?: OutgoingGrant) => {
    if (confirm !== id) { setConfirm(id); return; }
    void run(async () => {
      await request(grant ? `todo/share?${new URLSearchParams({ todo_id: todoId, to: grant.recipient })}`
        : `trace/share?${new URLSearchParams({ share_id: id })}`, "DELETE");
      await refresh(); setConfirm(""); return "Unshared";
    });
  };
  const row = (id: string, who: string, meta: string, grant?: OutgoingGrant) => (
    <div key={id} className="mb-1.5 flex items-center gap-2 rounded-sm border border-sol-base02 bg-sol-base02/25 px-2 py-1.5">
      <div className="min-w-0 flex-1">
        <div className="truncate text-[11.5px] text-sol-base1">{who}</div>
        <div className="mt-px text-[10px] text-sol-base01">{meta}</div>
        {!grant && <div className="mt-0.5 truncate rounded-sm bg-sol-base02 px-1.5 py-0.5 text-[10.5px] text-sol-base0">{window.location.host}/t/{id}</div>}
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {!grant && <button type="button" className={`rounded-sm px-1.5 py-0.5 text-[10px] ${copied === id ? "bg-sol-green/20 font-semibold text-sol-green" : "bg-sol-base02 text-sol-base1"}`} onClick={() => run(() => copy(id))}>{copied === id ? "Copied" : "Copy link"}</button>}
        <button type="button" className="rounded-sm bg-sol-base02 px-1.5 py-0.5 text-[10px] text-sol-base1" onClick={() => openEdit(grant ? "private" : "public", grant)}>Edit</button>
        <button type="button" className="rounded-sm bg-sol-base02 px-1.5 py-0.5 text-[10px] text-sol-red" onClick={() => unshare(id, grant)}>{confirm === id ? "Confirm" : "Unshare"}</button>
      </div>
    </div>
  );
  const submit = busy ? "Saving…" : audience === "public" ? "Copy link" : recipient.trim() ? `Share with ${recipient.trim()}` : "Share";
  return <fieldset disabled={busy} className="m-0 flex max-h-[min(480px,75dvh)] w-full min-w-0 flex-col overflow-hidden border-0 p-0 text-xs text-sol-base0 max-sm:max-h-[min(360px,75dvh)]">
    <div className="flex shrink-0 items-center justify-between gap-2 border-b border-sol-base02 px-3 py-[9px]">
      <span className="text-[13px] font-semibold text-sol-base2">{form ? "Share" : "Shares"}</span>
      <span className="rounded-sm bg-sol-base02 px-1.5 py-px text-[11px] tabular-nums text-sol-base0">#{todoId}</span>
    </div>
    {!form ? <>
      <div data-share-scroll className="min-h-0 overflow-auto px-2.5 pt-1 pb-1">
        {grants.length > 0 && <div className="mt-2 mb-1 text-[9.5px] tracking-[0.1em] text-sol-base01 uppercase">Private</div>}
        {grants.map(grant => row(grant.share_id, grant.recipient, `${counts(currentPicks(options, "private", null, grant))}${sharedWhen(grant.shared_at)}`, grant))}
        {publicShare && <>
          <div className="mt-2 mb-1 text-[9.5px] tracking-[0.1em] text-sol-base01 uppercase">Public link</div>
          {row(publicShare.share_id, "Anyone with the link", `${counts(currentPicks(options, "public", publicShare))} · password: ${publicShare.has_password ? "set" : "none"}`)}
        </>}
        {feedback && <p role="status" className={`my-1 break-all text-[11px] ${tone === "bad" ? "text-sol-red" : "text-sol-green"}`}>{feedback}</p>}
      </div>
      <div className="shrink-0 border-t border-sol-base02 px-3 py-2">
        <button type="button" className="text-[11px] text-sol-blue" onClick={() => openNew(publicShare ? "private" : "public")}>+ Share with someone or create a public link</button>
      </div>
    </> : <>
      <div role="tablist" aria-label="Share audience" className="mx-3 mt-2 flex shrink-0 gap-0.5 rounded-sm bg-sol-base02 p-0.5">
        {(["public", "private"] as const).map(next =>
          <button key={next} type="button" role="tab" aria-selected={next === audience}
            className={`flex-1 rounded-sm px-0.5 py-1.5 text-[11.5px] ${next === audience ? "bg-sol-base03 font-semibold text-sol-base2 shadow-[0_0_0_1px_var(--color-sol-base02)]" : "text-sol-base0"}`}
            onClick={() => next !== audience && openNew(next)}>{next === "public" ? "Public link" : "Specific user"}</button>)}
      </div>
      <div data-share-scroll className="min-h-0 overflow-auto px-3 pt-2.5 pb-1.5">
        {audience === "private" ? <div>
          <div className="mb-1 text-[10.5px] text-sol-base01">Share with</div>
          <input className="y-field w-full rounded-sm px-[7px] py-[5px] text-[11.5px]" aria-label="Recipient email or user id" placeholder="email or user id"
            readOnly={editing} value={recipient} onChange={event => setRecipient(event.target.value)} />
          <p className="mt-1 text-[10px] text-sol-base01">Must be an admitted y-agent user.</p>
        </div> : <p className="mb-2.5 text-[11px] text-sol-base0">Anyone with the link can view this todo page. No sign-in.</p>}
        {kinds.map(kind => {
          const chosen = picks[kind];
          const items = options[kind];
          const choose = (ids: string[]) => setPicks(prev => ({ ...prev, [kind]: ids }));
          return <section key={kind}>
            <div className="mt-[11px] mb-1 flex items-center justify-between gap-2">
              <span className="text-[10px] tracking-[0.08em] text-sol-base01 uppercase">{sectionName[kind]} <b className="font-semibold tracking-normal text-sol-base0 normal-case">{chosen.length} / {items.length}</b></span>
              {items.length > 0 && <span className="flex shrink-0 items-center gap-2">
                <button type="button" className="text-[10.5px] text-sol-blue disabled:text-sol-base01" disabled={chosen.length === items.length} onClick={() => choose(items.map(item => item.id))}>Select all</button>
                <button type="button" className="text-[10.5px] text-sol-blue disabled:text-sol-base01" disabled={chosen.length === 0} onClick={() => choose([])}>Clear all</button>
              </span>}
            </div>
            <div className="max-h-[92px] overflow-auto rounded-sm border border-sol-base02 px-1.5 py-0.5">
              {items.map(item => <label key={item.id} className={`grid min-h-6 items-center gap-x-1.5 ${kind === "chat" ? "grid-cols-[12px_minmax(0,1fr)]" : "grid-cols-[12px_14px_minmax(0,1fr)]"}`}>
                <input type="checkbox" className="share-check" checked={chosen.includes(item.id)} onChange={event => choose(
                  event.target.checked ? [...chosen, item.id] : chosen.filter(id => id !== item.id))} />
                {kind !== "chat" && <span className="text-sol-base01">{kind === "note" ? <NoteIcon /> : <LinkIcon />}</span>}
                <span className={kind === "chat" ? "truncate font-mono text-xs tracking-[0.02em] text-sol-base2" : "truncate text-[11.5px] text-sol-base1"}>{kind === "chat" ? item.id : item.label}</span>
              </label>)}
            </div>
          </section>;
        })}
      </div>
      <footer className="shrink-0 border-t border-sol-base02 bg-sol-base03 px-3 pt-2 pb-2.5">
        <div className="mb-1.5 text-[11px] text-sol-base01">{selectedCount === 0 ? "Nothing selected" : `${selectedCount} selected`}</div>
        {audience === "private" ? <p className="mb-1.5 text-[10px] text-sol-base01">Read-only. They see these items, not your live files.</p> : <div className="mb-2">
          <div className="mb-1 text-[10.5px] text-sol-base01">Password</div>
          <div role="group" aria-label="Link password" className="flex gap-0.5 rounded-sm bg-sol-base02 p-0.5">
            {([...(canKeep ? [["keep", "Keep"]] : []), ["none", "None"], ["generate", "Auto"], ["custom", "Custom"]] as [Password, string][]).map(([value, label]) =>
              <button key={value} type="button" aria-pressed={password === value}
                className={`flex-1 rounded-sm px-0.5 py-1 text-[11px] ${password === value ? "bg-sol-base03 font-semibold text-sol-base2" : "text-sol-base0"}`}
                onClick={() => setPassword(value)}>{label}</button>)}
          </div>
          {password === "custom" && <input aria-label="Custom password" className="y-field mt-1.5 w-full rounded-sm px-[7px] py-[5px] text-[11.5px]" value={custom} onChange={event => setCustom(event.target.value)} />}
        </div>}
        {feedback && <p role="status" className={`mb-1.5 break-all text-[11px] ${tone === "bad" ? "text-sol-red" : "text-sol-green"}`}>{feedback}</p>}
        <button type="button" className="w-full rounded-sm bg-sol-blue px-2 py-1.5 text-[11px] font-semibold text-sol-base03 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={audience === "private" ? !recipient.trim() : password === "custom" && !custom.trim()}
          onClick={() => run(save)}>{submit}</button>
        {(publicShare || grants.length > 0) && <button type="button" className="mt-1.5 text-[11px] text-sol-blue" onClick={() => { setForm(false); clearNotice(); }}>Existing shares</button>}
      </footer>
    </>}
  </fieldset>;
}
