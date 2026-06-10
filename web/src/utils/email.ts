export function formatEmailDate(ts: number): string {
  if (!ts) return "";
  const d = new Date(ts);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

// Gmail-style expanded-header timestamp, e.g. "Sat, Feb 28, 3:40 AM"; the year is
// shown only for messages from a previous year.
export function formatEmailDateTime(ts: number): string {
  if (!ts) return "";
  const d = new Date(ts);
  const opts: Intl.DateTimeFormatOptions = { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" };
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = "numeric";
  return d.toLocaleString(undefined, opts);
}

// Parse a `From:` header value into a display name + bare email. Falls back to the
// raw string for both fields when there is no `Name <addr>` shape.
export function parseSender(from: string | undefined): { name: string; email: string } {
  if (!from) return { name: "", email: "" };
  const m = from.match(/^\s*"?([^"<]*?)"?\s*<([^>]+)>\s*$/);
  if (m) {
    const email = m[2].trim();
    return { name: m[1].trim() || email, email };
  }
  const trimmed = from.trim();
  return { name: trimmed, email: trimmed };
}

// Split an email body into the author's own text and the trailing quoted reply
// chain (everything from the first `On ... wrote:` marker onward).
export function splitOwnAndQuoted(s: string | undefined): { own: string; quoted: string } {
  if (!s) return { own: "", quoted: "" };
  const match = s.search(/^>?\s*On .+wrote:\s*$/m);
  if (match < 0) return { own: s.trim(), quoted: "" };
  return { own: s.slice(0, match).trim(), quoted: s.slice(match).trim() };
}
