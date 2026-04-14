export function formatDateTime(d: Date): { date: string; time: string } {
  return {
    date: d.toLocaleDateString([], { year: "numeric", month: "2-digit", day: "2-digit" }),
    time: d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
  };
}
