export function formatEmailDate(ts: number): string {
  if (!ts) return "";
  const d = new Date(ts);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function formatEmailDateTime(ts: number): string {
  if (!ts) return "";
  const d = new Date(ts);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit" });
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
