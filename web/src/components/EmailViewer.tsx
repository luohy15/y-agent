import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { API, getStoredEmail, jsonFetcher as fetcher } from "../api";
import { emailSnippet, formatEmailDate, formatEmailDateFull, formatEmailDateTime, isHtmlContent, parseSender, sanitizeEmailHtml, splitOwnAndQuoted } from "../utils/email";

interface Email {
  email_id: string;
  from_addr: string;
  date: number; // unix ms
  subject?: string;
  to_addrs?: string[];
  cc_addrs?: string[];
  content?: string;
  thread_id?: string;
  thread_count?: number;
}

const AVATAR_COLORS = ["bg-sol-blue", "bg-sol-cyan", "bg-sol-green", "bg-sol-yellow", "bg-sol-orange", "bg-sol-red", "bg-sol-magenta", "bg-sol-violet"];

function avatarColor(seed: string): string {
  let hash = 0;
  for (let i = 0; i < seed.length; i++) hash = (hash * 31 + seed.charCodeAt(i)) | 0;
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length];
}

function Avatar({ name, email }: { name: string; email: string }) {
  const initial = (name || email || "?").trim().charAt(0).toUpperCase() || "?";
  return (
    <div className={`shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-sol-base03 text-xs font-medium ${avatarColor(email || name)}`}>
      {initial}
    </div>
  );
}

// Decorative outline star, matching Gmail's collapsed-row affordance (no backend flag yet).
function Star() {
  return (
    <svg className="shrink-0 w-3.5 h-3.5 text-sol-base01" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
    </svg>
  );
}

function QuotedToggle({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  if (!text) return null;
  return (
    <div className="mt-1">
      <button
        onClick={() => setOpen(!open)}
        title={open ? "Hide trimmed content" : "Show trimmed content"}
        className="px-1.5 leading-none rounded bg-sol-base02 text-sol-base01 hover:text-sol-base0 text-xs cursor-pointer"
      >
        •••
      </button>
      {open && (
        <pre className="text-sol-base01 text-xs whitespace-pre-wrap break-words mt-1">{text}</pre>
      )}
    </div>
  );
}

// Sanitized HTML email body inside a shadow root, so embedded <style> blocks
// can't leak class rules into the app document. HTML emails are designed for
// light backgrounds, so the wrapper forces one regardless of the app theme.
function HtmlBody({ html }: { html: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const root = el.shadowRoot || el.attachShadow({ mode: "open" });
    root.innerHTML =
      '<div style="background:#fff;color:#222;padding:12px;border-radius:4px;overflow-x:auto;font-size:14px;line-height:1.5">' +
      sanitizeEmailHtml(html) +
      "</div>";
  }, [html]);
  return <div ref={ref} />;
}

// Gmail-style combined to+cc recipient line, e.g. "me, Aria": the logged-in user's
// own address renders as "me", others as their parsed display name; de-duplicated
// by bare address across to + cc.
function recipientLine(email: Email): string {
  const own = (getStoredEmail() || "").toLowerCase();
  const seen = new Set<string>();
  const names: string[] = [];
  for (const entry of [...(email.to_addrs || []), ...(email.cc_addrs || [])]) {
    const { name, email: addr } = parseSender(entry);
    const key = addr.toLowerCase();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    names.push(own && key === own ? "me" : name);
  }
  return names.join(", ");
}

// Gmail-style recipient-details dropdown: a small triangle next to the recipient
// line that toggles an anchored popover with a label:value metadata table. Only
// fields already on the Email type are shown; mailed-by is derived from the
// sender's email domain.
function RecipientDetails({ email }: { email: Email }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const handleKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, [open]);

  const domain = parseSender(email.from_addr).email.split("@")[1] || "";
  const rows: [string, string][] = [["from", email.from_addr]];
  rows.push(["to", (email.to_addrs || []).join(", ")]);
  if (email.cc_addrs && email.cc_addrs.length > 0) rows.push(["cc", email.cc_addrs.join(", ")]);
  rows.push(["date", formatEmailDateFull(email.date)]);
  rows.push(["subject", email.subject || ""]);
  if (domain) rows.push(["mailed-by", domain]);

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        onClick={() => setOpen(!open)}
        title={open ? "Hide details" : "Show details"}
        className="text-sol-base01 hover:text-sol-base0 cursor-pointer align-middle"
      >
        <svg className="w-3 h-3" viewBox="0 0 24 24" fill="currentColor"><path d="M7 10l5 5 5-5z" /></svg>
      </button>
      {open && (
        <div className="absolute left-0 top-full mt-1 z-50 w-max max-w-[24rem] bg-sol-base02 border border-sol-base01 rounded shadow-lg p-3">
          <table className="text-xs">
            <tbody>
              {rows.map(([label, value]) => (
                <tr key={label}>
                  <td className="text-sol-base01 text-right align-top whitespace-nowrap pr-2 py-0.5">{label}:</td>
                  <td className="text-sol-base0 break-words py-0.5">{value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// One-line summary for a collapsed message: avatar + sender + snippet + date (+ star).
function CollapsedRow({ email, onClick }: { email: Email; onClick: () => void }) {
  const { name, email: addr } = parseSender(email.from_addr);
  return (
    <button
      onClick={onClick}
      title="Expand message"
      className="w-full text-left flex items-center gap-2 py-2 border-b border-sol-base02 cursor-pointer hover:bg-sol-base02/40 px-1"
    >
      <Avatar name={name} email={addr} />
      <span className="shrink-0 text-sol-base0 text-sm font-medium max-w-[10rem] truncate">{name}</span>
      <span className="flex-1 truncate text-sol-base01 text-xs">{emailSnippet(email.content)}</span>
      <span className="shrink-0 text-sol-base01 text-xs">{formatEmailDate(email.date)}</span>
      <Star />
    </button>
  );
}

// Count bubble standing in for a run of consecutively collapsed messages.
function CountBubble({ count, onClick }: { count: number; onClick: () => void }) {
  return (
    <div className="py-1 border-b border-sol-base02 pl-1">
      <button
        onClick={onClick}
        title={`Show ${count} more ${count === 1 ? "message" : "messages"}`}
        className="w-9 h-7 rounded-full bg-sol-base02 text-sol-base01 hover:text-sol-base0 hover:bg-sol-base01/30 text-xs cursor-pointer"
      >
        {count}
      </button>
    </div>
  );
}

// A fully expanded message: header (avatar + sender + <email> + date + actions),
// combined to+cc recipient line, full body, and a trimmed-quoted-content toggle.
function ExpandedMessage({ email }: { email: Email }) {
  const { name, email: addr } = parseSender(email.from_addr);
  const { own, quoted } = splitOwnAndQuoted(email.content);
  const recipients = recipientLine(email);
  return (
    <div className="py-3 border-b border-sol-base02 px-1">
      <div className="flex items-start gap-2">
        <Avatar name={name} email={addr} />
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2">
            <span className="text-sol-base0 text-sm font-medium truncate">{name}</span>
            {addr && addr !== name && <span className="text-sol-base01 text-xs truncate">&lt;{addr}&gt;</span>}
            <span className="ml-auto shrink-0 text-sol-base01 text-xs">{formatEmailDateTime(email.date)}</span>
            <button title="Reply" className="shrink-0 text-sol-base01 hover:text-sol-base0 cursor-pointer">
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 17 4 12 9 7" /><path d="M20 18v-2a4 4 0 0 0-4-4H4" /></svg>
            </button>
            <button title="More" className="shrink-0 text-sol-base01 hover:text-sol-base0 cursor-pointer">
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="12" cy="19" r="1.6" /></svg>
            </button>
          </div>
          {recipients && (
            <div className="flex items-center gap-1">
              <div className="min-w-0 text-sol-base01 text-xs truncate">to {recipients}</div>
              <RecipientDetails email={email} />
            </div>
          )}
        </div>
      </div>
      {email.content && (
        <div className="mt-3">
          {isHtmlContent(email.content) ? (
            <HtmlBody html={email.content} />
          ) : (
            <>
              <pre className="text-sol-base0 text-sm whitespace-pre-wrap break-words leading-relaxed">{own}</pre>
              <QuotedToggle text={quoted} />
            </>
          )}
        </div>
      )}
    </div>
  );
}

// Gmail-style collapsed conversation: latest expanded, earlier ones collapsed to
// one-line rows; runs of consecutively collapsed messages bundle behind a count
// bubble. Remounted per thread via `key`, so collapse state resets on selection.
function ThreadView({ emails }: { emails: Email[] }) {
  const ordered = [...emails].sort((a, b) => a.date - b.date);
  // Gmail expands both the first and the latest message; only the middle ones
  // collapse. Threads of 1-2 messages keep everything expanded (nothing to hide).
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() =>
    ordered.length <= 2
      ? new Set(ordered.map((e) => e.email_id))
      : new Set([ordered[0].email_id, ordered[ordered.length - 1].email_id])
  );
  const [revealedIds, setRevealedIds] = useState<Set<string>>(() => new Set());

  const expand = (id: string) => setExpandedIds((prev) => new Set(prev).add(id));
  const reveal = (ids: string[]) => setRevealedIds((prev) => { const next = new Set(prev); ids.forEach((id) => next.add(id)); return next; });

  const subject = ordered[0].subject;
  const items: React.ReactNode[] = [];
  let i = 0;
  while (i < ordered.length) {
    const m = ordered[i];
    if (expandedIds.has(m.email_id)) {
      items.push(<ExpandedMessage key={m.email_id} email={m} />);
      i++;
      continue;
    }
    // Maximal run of consecutively collapsed messages.
    let j = i;
    while (j < ordered.length && !expandedIds.has(ordered[j].email_id)) j++;
    const run = ordered.slice(i, j);
    // First of the run always shows as a one-line row; the rest bundle behind a
    // count bubble until revealed.
    items.push(<CollapsedRow key={run[0].email_id} email={run[0]} onClick={() => expand(run[0].email_id)} />);
    const rest = run.slice(1);
    const hidden = rest.filter((e) => !revealedIds.has(e.email_id));
    if (rest.length > 0 && hidden.length >= 2) {
      items.push(<CountBubble key={`bubble-${run[0].email_id}`} count={hidden.length} onClick={() => reveal(hidden.map((e) => e.email_id))} />);
    } else {
      rest.forEach((e) => items.push(<CollapsedRow key={e.email_id} email={e} onClick={() => expand(e.email_id)} />));
    }
    i = j;
  }

  return (
    <div className="h-full overflow-y-auto bg-sol-base03 text-sm">
      <div className="max-w-3xl mx-auto px-4 py-4">
        <h1 className="text-sol-base1 text-lg font-medium mb-3 break-words">
          {subject || "(no subject)"}
          {ordered.length > 1 && <span className="text-sol-base01 text-sm font-normal ml-2">({ordered.length})</span>}
        </h1>
        {items}
      </div>
    </div>
  );
}

interface EmailViewerProps {
  threadId?: string | null;
  emailId?: string | null;
  account?: string | null;
}

export default function EmailViewer({ threadId, emailId, account }: EmailViewerProps) {
  const key = threadId || emailId;
  const swrKey = key
    ? `${API}/api/email/thread/${encodeURIComponent(key)}${account ? `?account=${encodeURIComponent(account)}` : ""}`
    : null;
  const { data: emails, isLoading, error } = useSWR<Email[]>(swrKey, fetcher, { revalidateOnFocus: false });

  if (!key) {
    return (
      <div className="h-full flex items-center justify-center bg-sol-base03">
        <p className="text-sol-base01 italic text-sm">Select an email to read</p>
      </div>
    );
  }
  if (isLoading && !emails) {
    return <div className="h-full bg-sol-base03"><p className="text-sol-base01 italic text-sm p-4">Loading...</p></div>;
  }
  if (error || !Array.isArray(emails) || emails.length === 0) {
    return <div className="h-full bg-sol-base03"><p className="text-sol-red text-sm p-4">Failed to load email</p></div>;
  }

  return <ThreadView key={key} emails={emails} />;
}
