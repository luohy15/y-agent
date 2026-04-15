// Shared badge styles for trace_id, chat_id, and skill across the app

// --- Skill → solarized color token ---
const SKILL_SOL_COLOR: Record<string, string> = {
  DM:              "blue",
  dev:             "green",
  cto:             "cyan",
  todo:            "yellow",
  hr:              "magenta",
  finance:         "orange",
  calendar:        "violet",
  git:             "yellow",
};
const DEFAULT_SOL_COLOR = "violet";

export function getSkillSolColor(skill: string): string {
  return SKILL_SOL_COLOR[skill] || DEFAULT_SOL_COLOR;
}

// Static color maps — TailwindCSS needs complete class strings in source
const SKILL_COLOR_MAP: Record<string, { bg: string; text: string }> = {
  blue:    { bg: "bg-sol-blue/20",    text: "text-sol-blue" },
  green:   { bg: "bg-sol-green/20",   text: "text-sol-green" },
  cyan:    { bg: "bg-sol-cyan/20",    text: "text-sol-cyan" },
  yellow:  { bg: "bg-sol-yellow/20",  text: "text-sol-yellow" },
  magenta: { bg: "bg-sol-magenta/20", text: "text-sol-magenta" },
  orange:  { bg: "bg-sol-orange/20",  text: "text-sol-orange" },
  violet:  { bg: "bg-sol-violet/20",  text: "text-sol-violet" },
  red:     { bg: "bg-sol-red/20",     text: "text-sol-red" },
};

const SKILL_CHART_COLOR_MAP: Record<string, { bg: string; border: string; text: string; dot: string; bar: string }> = {
  blue:    { bg: "bg-sol-blue/10",    border: "border-sol-blue/30",    text: "text-sol-blue",    dot: "bg-sol-blue",    bar: "bg-sol-blue/60" },
  green:   { bg: "bg-sol-green/10",   border: "border-sol-green/30",   text: "text-sol-green",   dot: "bg-sol-green",   bar: "bg-sol-green/60" },
  cyan:    { bg: "bg-sol-cyan/10",    border: "border-sol-cyan/30",    text: "text-sol-cyan",    dot: "bg-sol-cyan",    bar: "bg-sol-cyan/60" },
  yellow:  { bg: "bg-sol-yellow/10",  border: "border-sol-yellow/30",  text: "text-sol-yellow",  dot: "bg-sol-yellow",  bar: "bg-sol-yellow/60" },
  magenta: { bg: "bg-sol-magenta/10", border: "border-sol-magenta/30", text: "text-sol-magenta", dot: "bg-sol-magenta", bar: "bg-sol-magenta/60" },
  orange:  { bg: "bg-sol-orange/10",  border: "border-sol-orange/30",  text: "text-sol-orange",  dot: "bg-sol-orange",  bar: "bg-sol-orange/60" },
  violet:  { bg: "bg-sol-violet/10",  border: "border-sol-violet/30",  text: "text-sol-violet",  dot: "bg-sol-violet",  bar: "bg-sol-violet/60" },
  red:     { bg: "bg-sol-red/10",     border: "border-sol-red/30",     text: "text-sol-red",     dot: "bg-sol-red",     bar: "bg-sol-red/60" },
};

const DEFAULT_SKILL_COLOR = SKILL_COLOR_MAP["violet"];
const DEFAULT_CHART_COLOR = SKILL_CHART_COLOR_MAP["violet"];

export function getSkillColor(skill: string) {
  return SKILL_COLOR_MAP[getSkillSolColor(skill)] || DEFAULT_SKILL_COLOR;
}

// Extended color set for waterfall chart / trace views
export function getSkillChartColors(skill: string) {
  return SKILL_CHART_COLOR_MAP[getSkillSolColor(skill)] || DEFAULT_CHART_COLOR;
}

// --- Badge base classes ---
const BADGE_BASE = "inline-flex items-center px-1.5 py-0.5 rounded font-mono font-medium shrink-0";

// trace_id: gray
export const TRACE_BADGE = `${BADGE_BASE} bg-sol-base01/20 text-sol-base01`;

// chat_id: blue
export const CHAT_BADGE = `${BADGE_BASE} bg-sol-blue/20 text-sol-blue`;

// skill: dynamic color from map (use with getSkillColor)
export function skillBadgeClass(skill: string) {
  const c = getSkillColor(skill);
  return `${BADGE_BASE} ${c.bg} ${c.text}`;
}

// --- Status badge (todo status) ---
const STATUS_COLOR: Record<string, string> = {
  active: "bg-sol-blue/20 text-sol-blue",
  pending: "bg-sol-base02 text-sol-base01",
  completed: "bg-sol-green/20 text-sol-green",
};

export function statusBadgeClass(status: string): string {
  return STATUS_COLOR[status] || "bg-sol-base02 text-sol-base01";
}

// --- Priority color ---
const PRIORITY_COLOR: Record<string, string> = {
  high: "text-sol-red",
  medium: "text-sol-yellow",
  low: "text-sol-green",
};

export function priorityColorClass(priority: string): string {
  return PRIORITY_COLOR[priority] || "text-sol-base0";
}

// --- History action badge ---
const ACTION_COLOR: Record<string, string> = {
  created: "bg-sol-cyan/20 text-sol-cyan",
  completed: "bg-sol-green/20 text-sol-green",
  updated: "bg-sol-yellow/20 text-sol-yellow",
  activated: "bg-sol-blue/20 text-sol-blue",
  deleted: "bg-sol-red/20 text-sol-red",
};

export function actionBadgeClass(action: string): string {
  return ACTION_COLOR[action] || "bg-sol-base02 text-sol-base0";
}

// Strip [trace:... from:... to:... from_chat:... to_chat:...] prefix from message content
export function stripTracePrefix(content: string): string {
  return content.replace(/^\[trace:\S+\s+from:\S+\s+to:\S+\s+from_chat:\S+\s+to_chat:\S+\]\n?/, "");
}
