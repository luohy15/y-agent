// Scripted landing tour (todo 3864, visual spec pages/design-3864.html).
// A fixed teaching script, not live telemetry. Inline `code` spans in the
// copy are written with backticks and rendered by LandingTour.

export type Pt = [number, number];

export interface Sat {
  key: string;
  label: string;
  sub: string;
  x: number;
  y: number;
  tagged: boolean;
}

// Satellites sit on an ellipse around task T, leaving the left side free for the trace line.
export const SATS: Sat[] = [
  { key: "note", label: "Notes", sub: "note", x: 621, y: 93, tagged: true },
  { key: "link", label: "Links", sub: "link", x: 759, y: 93, tagged: true },
  { key: "entity", label: "Entities", sub: "graph", x: 856, y: 185, tagged: true },
  { key: "rss", label: "RSS", sub: "feeds", x: 856, y: 315, tagged: true },
  { key: "mail", label: "Email", sub: "Gmail sync", x: 759, y: 407, tagged: true },
  { key: "fin", label: "Finance", sub: "ledger", x: 621, y: 407, tagged: false },
  { key: "rem", label: "Reminders", sub: "reminder", x: 524, y: 315, tagged: true },
  { key: "cal", label: "Calendar", sub: "calendar", x: 524, y: 185, tagged: true },
];

// [title, what it is, real counterpart]
export const PARTS: Record<string, [string, string, string]> = {
  phone: ["Phone", "Open the web app in any browser to send tasks and follow progress.", "React web app, `POST /api/chat/message`"],
  tablet: ["Tablet", "The same web app, the same chats.", "Same API and sign-in"],
  laptop: ["Laptop", "The same web app, the same chats.", "Same API and sign-in"],
  tg: ["Telegram", "Send tasks to the bot in a private chat; manager replies come back on their own.", "Telegram webhook, private chats only"],
  cli: ["Terminal", "Send the same task from a terminal with `y chat`.", "`y` CLI, same API"],
  cloud: ["Cloud session", "Where the work actually happens. It runs on a cloud machine and keeps going when your device is off.", "A worker runs Claude Code in tmux on EC2"],
  todo: ["Task T", "The hub: notes, links, events, reminders and chats can all attach to one task.", "`todo` table; the trace ID is the todo ID"],
  note: ["Notes", "Plans, decisions and journals, attached to tasks.", "`note_todo_relation`, `y assoc note`"],
  link: ["Links", "Saved and fetched web pages, attached to tasks.", "`link_todo_relation`, `y assoc link`"],
  entity: ["Entities", "People, products, organizations: a knowledge graph tying notes, links and RSS together.", "`entity_note / entity_link / entity_rss_relation`"],
  rss: ["RSS", "Feeds and their items, which can attach to entities.", "`rss_feed`, `y rss`"],
  mail: ["Email", "Several Gmail accounts synced in, all taggable.", "`email`, `y email sync-gmail`"],
  fin: ["Finance", "Ledger, holdings, FIRE progress. Not attached to tasks or tagged yet; sessions read it.", "finance module, `y finance`"],
  rem: ["Reminders", "Timed reminders that can attach to a task or an event.", "`reminder.todo_id` / `calendar_event_id`"],
  cal: ["Calendar", "Events that can attach to a task.", "`calendar_event.todo_id`"],
};

export const CLIENTS = ["phone", "tablet", "laptop", "tg", "cli"];
const HUB = ["todo", ...SATS.map(s => s.key)];
const TAGGED = SATS.filter(s => s.tagged).map(s => s.key).concat("todo");

export const MOVERS = ["msg", "res", "cal", "mail", "fin", "note"] as const;
export type Mover = (typeof MOVERS)[number];

export interface Step {
  ch: 0 | 1 | 2;
  t: string;
  x: string;
  r: string;
  e: string;
  a: string[];
  dim: string[];
  edges: string[];
  hot?: string[];
  tags?: boolean;
  ghosts?: boolean;
  mv: Partial<Record<Mover, string[]>>;
  st?: Record<string, string>;
}

const DIRECT = ["trace", "d-note", "d-link", "d-cal", "d-rem", "d-remcal"];
const GRAPH = [...DIRECT, "g-note", "g-link", "g-rss"];

export const STEPS: Step[] = [
  { ch: 0, t: "Two things", x: "Two things make y-agent worth opening every day: you can hand off a task from any device, and all your data lives in one place where it links together. One example for each follows.",
    r: "An example scenario: a fixed script with illustrative data.", e: "This is a teaching animation, not live monitoring.",
    a: [], dim: [], edges: [], mv: {} },
  { ch: 1, t: "Send it from whatever is at hand", x: "In a phone browser, type “Help me plan next week.” Tablet, laptop, Telegram and the terminal are all the same entry point.",
    r: "Web, Telegram and `y chat` all reach the same API: `POST /api/chat/message`", e: "Telegram works in private chats only.",
    a: ["phone", "cloud"], dim: HUB, edges: [], mv: { msg: ["phone", "cloud"] }, st: { phone: "sent", cloud: "running" } },
  { ch: 1, t: "The cloud takes over", x: "A cloud session runs the task. Lock the phone or close the page, and the work keeps going.",
    r: "The API queues it; a worker runs Claude Code in tmux on EC2, independent of the client connection", e: "Long tasks continue across Lambda invocations without you noticing.",
    a: ["cloud"], dim: HUB, edges: [], mv: { msg: ["cloud"] }, st: { phone: "away", cloud: "running" } },
  { ch: 1, t: "Pick it up on another device", x: "Back at your laptop, open the same chat and the answer is there. Progress and results are identical on every device.",
    r: "Messages are stored first, then pushed to open pages over SSE; manager replies also go to Telegram", e: "Other sessions don’t push to Telegram; read them on the web.",
    a: ["laptop", "phone", "tablet", "cloud"], dim: HUB, edges: [], mv: { res: ["cloud", "laptop"] }, st: { cloud: "done", laptop: "same chat", phone: "same chat", tablet: "same chat" } },
  { ch: 2, t: "The task is the hub", x: "That request belongs to task T. Chats, notes, links and events can all attach to a single task.",
    r: "The trace ID is the todo ID: every chat under a task stays connected", e: "Not every message creates a task; task T is preset here.",
    a: ["todo", "cloud"], dim: CLIENTS, edges: ["trace"], hot: ["trace"], mv: {} },
  { ch: 2, t: "Direct links", x: "Notes, links, events and reminders attach straight to the task, and a reminder can also attach to an event. Open the task and they are all there.",
    r: "`note_todo_relation`, `link_todo_relation`, `calendar_event.todo_id`, `reminder.todo_id`", e: "Links are made explicitly (`y assoc` and friends), never guessed.",
    a: ["todo", "note", "link", "cal", "rem"], dim: [...CLIENTS, "entity", "rss", "mail", "fin"], edges: DIRECT, hot: DIRECT.slice(1), mv: {} },
  { ch: 2, t: "A knowledge graph", x: "Entities such as people, products and organizations tie notes, links and RSS feeds together.",
    r: "`entity_note_relation`, `entity_link_relation`, `entity_rss_relation`", e: "",
    a: ["entity", "note", "link", "rss"], dim: [...CLIENTS, "mail", "fin", "cal", "rem"], edges: GRAPH, hot: ["g-note", "g-link", "g-rss"], mv: {} },
  { ch: 2, t: "Tags cut across everything", x: "One set of tags works on tasks, notes, links, email, events, reminders, RSS, entities and chats, so a single tag pulls up items of every kind.",
    r: "Tag carriers: todo, note, entity, chat, calendar_event, reminder, routine, link, email, rss_feed", e: "Finance is not a tag carrier yet, so the ring breaks there.",
    a: TAGGED, dim: CLIENTS, edges: [...GRAPH, "ring"], hot: ["ring"], tags: true, mv: {} },
  { ch: 2, t: "One session reads and writes", x: "Back to “plan next week”: the cloud session reads your calendar, unanswered email and holdings, writes a weekly-plan note, and links it back to task T.",
    r: "In one session: read with `y calendar`, `y email`, `y finance`; write a note, then `y assoc note`", e: "What it reads depends on the commands the session actually runs; data never flows on its own.",
    a: ["cloud", "cal", "mail", "fin", "note", "todo"], dim: [...CLIENTS, "link", "entity", "rss", "rem"], edges: ["trace", "d-note", "r-cal", "r-mail", "r-fin", "w-note"], hot: ["r-cal", "r-mail", "r-fin", "w-note"],
    mv: { cal: ["cal", "cloudIn1"], mail: ["mail", "cloudIn2"], fin: ["fin", "cloudIn3"], note: ["cloudOut", "note"] }, st: { cloud: "reading · writing" } },
  { ch: 2, t: "So, far fewer apps", x: "Todos, notes, read-later, RSS, calendar reminders and budgeting no longer sit in separate apps. They live in one place, link to each other, and any device can send a task to work on them.",
    r: "One PostgreSQL store; web, Telegram and CLI share one API", e: "This reflects the author’s own usage, not feature-by-feature parity.",
    a: ["todo", "cloud"], dim: [], edges: [...GRAPH, "ring"], hot: [], ghosts: true, mv: {}, st: { cloud: "standing by" } },
];

// First step of each chapter, for the chapter buttons.
export const CHAPTERS: { ch: 1 | 2; label: string; step: number }[] = [
  { ch: 1, label: "1 Dispatch anywhere", step: 1 },
  { ch: 2, label: "2 Connect everything", step: 4 },
];

export const POS: Record<string, Pt> = {
  ...Object.fromEntries(SATS.map(s => [s.key, [s.x, s.y] as Pt])),
  phone: [205, 71], tablet: [205, 155], laptop: [205, 239], cloud: [315, 220],
  cloudIn1: [300, 196], cloudIn2: [315, 286], cloudIn3: [330, 308], cloudOut: [330, 196],
};
