// Shared badge styles for trace_id, chat_id, and skill across the app

// --- Skill → solarized color token ---
const SKILL_SOL_COLOR: Record<string, string> = {
  DM:              "blue",
  dev:             "green",
  "dev-manager":   "cyan",
  todo:            "yellow",
  "skill-manager": "magenta",
  finance:         "orange",
  calendar:        "violet",
  git:             "yellow",
};
const DEFAULT_SOL_COLOR = "violet";

export function getSkillSolColor(skill: string): string {
  return SKILL_SOL_COLOR[skill] || DEFAULT_SOL_COLOR;
}

export function getSkillColor(skill: string) {
  const c = getSkillSolColor(skill);
  return { bg: `bg-sol-${c}/20`, text: `text-sol-${c}` };
}

// Extended color set for waterfall chart / trace views
export function getSkillChartColors(skill: string) {
  const c = getSkillSolColor(skill);
  return {
    bg: `bg-sol-${c}/10`,
    border: `border-sol-${c}/30`,
    text: `text-sol-${c}`,
    dot: `bg-sol-${c}`,
    bar: `bg-sol-${c}/60`,
  };
}

// --- Badge base classes ---
const BADGE_BASE = "inline-flex items-center px-1.5 py-0.5 rounded font-mono font-medium shrink-0";

// trace_id: orange
export const TRACE_BADGE = `${BADGE_BASE} bg-sol-orange/20 text-sol-orange`;

// chat_id: blue
export const CHAT_BADGE = `${BADGE_BASE} bg-sol-blue/20 text-sol-blue`;

// skill: dynamic color from map (use with getSkillColor)
export function skillBadgeClass(skill: string) {
  const c = getSkillColor(skill);
  return `${BADGE_BASE} ${c.bg} ${c.text}`;
}

// Strip [trace:... from:... to:... from_chat:... to_chat:...] prefix from message content
export function stripTracePrefix(content: string): string {
  return content.replace(/^\[trace:\S+\s+from:\S+\s+to:\S+\s+from_chat:\S+\s+to_chat:\S+\]\n?/, "");
}
