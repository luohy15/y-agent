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

// Split an email body into the author's own text and the trailing quoted reply
// chain (everything from the first `On ... wrote:` marker onward).
export function splitOwnAndQuoted(s: string | undefined): { own: string; quoted: string } {
  if (!s) return { own: "", quoted: "" };
  const match = s.search(/^>?\s*On .+wrote:\s*$/m);
  if (match < 0) return { own: s.trim(), quoted: "" };
  return { own: s.slice(0, match).trim(), quoted: s.slice(match).trim() };
}
