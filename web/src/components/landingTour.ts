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
  { key: "note", label: "笔记", sub: "note", x: 621, y: 93, tagged: true },
  { key: "link", label: "链接", sub: "link", x: 759, y: 93, tagged: true },
  { key: "entity", label: "实体", sub: "知识图谱", x: 856, y: 185, tagged: true },
  { key: "rss", label: "RSS", sub: "订阅", x: 856, y: 315, tagged: true },
  { key: "mail", label: "邮件", sub: "Gmail 同步", x: 759, y: 407, tagged: true },
  { key: "fin", label: "财务", sub: "账本 · 持仓", x: 621, y: 407, tagged: false },
  { key: "rem", label: "提醒", sub: "reminder", x: 524, y: 315, tagged: true },
  { key: "cal", label: "日历", sub: "calendar", x: 524, y: 185, tagged: true },
];

// [title, what it is, real counterpart]
export const PARTS: Record<string, [string, string, string]> = {
  phone: ["手机", "任何浏览器打开 Web 就能派任务、看进度。", "React Web 应用，`POST /api/chat/message`"],
  tablet: ["平板", "同一个 Web 应用，同一份会话。", "同一套 API 与登录"],
  laptop: ["电脑", "同一个 Web 应用，同一份会话。", "同一套 API 与登录"],
  tg: ["Telegram", "私聊机器人也能发任务；manager 的回答会自动推回来。", "Telegram webhook，仅私聊"],
  cli: ["命令行", "终端里 `y chat` 发同样的任务。", "`y` CLI，同一套 API"],
  cloud: ["云端会话", "真正干活的地方。跑在云端机器上，设备关了也不停。", "worker 在 EC2 的 tmux 里运行 Claude Code"],
  todo: ["任务 T", "关联的中心：笔记、链接、日程、提醒、会话都能挂到一个任务上。", "`todo` 表；trace ID 就是 todo ID"],
  note: ["笔记", "计划、决策、日记，挂到任务上。", "`note_todo_relation`，`y assoc note`"],
  link: ["链接", "收藏和抓取的网页内容，挂到任务上。", "`link_todo_relation`，`y assoc link`"],
  entity: ["实体", "人、产品、组织：把笔记、链接、RSS 串成知识图谱。", "`entity_note / entity_link / entity_rss_relation`"],
  rss: ["RSS", "订阅源和条目，能挂到实体上。", "`rss_feed`，`y rss`"],
  mail: ["邮件", "多个 Gmail 账号同步进来，可打标签。", "`email`，`y email sync-gmail`"],
  fin: ["财务", "账本、持仓、FIRE 进度。目前不挂任务、不打标签，由会话读取。", "finance 模块，`y finance`"],
  rem: ["提醒", "定时提醒，可挂到任务或日程。", "`reminder.todo_id` / `calendar_event_id`"],
  cal: ["日历", "日程事件，可挂到任务。", "`calendar_event.todo_id`"],
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
  { ch: 0, t: "两件事", x: "Y agent 每天被用，是因为两件事：在任何设备上把任务交出去；所有数据在同一处，彼此能连起来。下面各用一个例子演示。",
    r: "示例场景，固定脚本，示意数据。", e: "这是教学动画，不是实时监控。",
    a: [], dim: [], edges: [], mv: {} },
  { ch: 1, t: "从手边任何设备发出", x: "在手机浏览器里说一句：「帮我理一下下周」。平板、电脑、Telegram、命令行都是同一个入口。",
    r: "Web / Telegram / `y chat` 都进同一个 API：`POST /api/chat/message`", e: "Telegram 只支持私聊。",
    a: ["phone", "cloud"], dim: HUB, edges: [], mv: { msg: ["phone", "cloud"] }, st: { phone: "已发送", cloud: "运行中" } },
  { ch: 1, t: "云端接手，设备可以离开", x: "任务交给云端会话执行。手机锁屏、关掉页面都不影响它继续干活。",
    r: "API 入队 → worker 在 EC2 的 tmux 里运行 Claude Code，独立于客户端连接", e: "长任务会跨 Lambda 调用续跑，但对你透明。",
    a: ["cloud"], dim: HUB, edges: [], mv: { msg: ["cloud"] }, st: { phone: "已离开", cloud: "运行中" } },
  { ch: 1, t: "换一台设备看结果", x: "回到电脑前，打开同一个会话就看到回答。进度和结果在每台设备上都一样。",
    r: "消息先存库，再经 SSE 推给打开的页面；manager 会话的回答还会推到 Telegram", e: "普通会话不推 Telegram，在 Web 上看。",
    a: ["laptop", "phone", "tablet", "cloud"], dim: HUB, edges: [], mv: { res: ["cloud", "laptop"] }, st: { cloud: "已完成", laptop: "同一会话", phone: "同一会话", tablet: "同一会话" } },
  { ch: 2, t: "任务是中心", x: "刚才那条请求挂在任务 T 上。会话、笔记、链接、日程都能往一个任务上挂。",
    r: "trace ID 就是 todo ID：一个任务下的所有会话连在一起", e: "不是每句话都自动建任务；这里是预设的任务 T。",
    a: ["todo", "cloud"], dim: CLIENTS, edges: ["trace"], hot: ["trace"], mv: {} },
  { ch: 2, t: "直接关联", x: "笔记、链接、日程、提醒直接挂到任务上；提醒也能挂到日程。打开任务就能看到它们。",
    r: "`note_todo_relation`、`link_todo_relation`、`calendar_event.todo_id`、`reminder.todo_id`", e: "关联是显式建立的（`y assoc` 等），不是自动猜测。",
    a: ["todo", "note", "link", "cal", "rem"], dim: [...CLIENTS, "entity", "rss", "mail", "fin"], edges: DIRECT, hot: DIRECT.slice(1), mv: {} },
  { ch: 2, t: "知识图谱", x: "人、产品、组织这类实体，把笔记、链接、RSS 订阅串在一起。",
    r: "`entity_note_relation`、`entity_link_relation`、`entity_rss_relation`", e: "",
    a: ["entity", "note", "link", "rss"], dim: [...CLIENTS, "mail", "fin", "cal", "rem"], edges: GRAPH, hot: ["g-note", "g-link", "g-rss"], mv: {} },
  { ch: 2, t: "标签横穿一切", x: "同一套标签可以打在任务、笔记、链接、邮件、日程、提醒、RSS、实体、会话上，一个标签拉出跨类别的一串。",
    r: "标签载体：todo、note、entity、chat、calendar_event、reminder、routine、link、email、rss_feed", e: "财务目前不是标签载体，所以圈在这里断开。",
    a: TAGGED, dim: CLIENTS, edges: [...GRAPH, "ring"], hot: ["ring"], tags: true, mv: {} },
  { ch: 2, t: "会话一起读写", x: "回到「理一下下周」：云端会话同时读日程、待回邮件和持仓，写出一份周计划笔记，挂回任务 T。",
    r: "同一个会话里用 `y calendar`、`y email`、`y finance` 读，写 note 后 `y assoc note`", e: "能读到什么取决于会话实际执行的命令；数据不会自动流动。",
    a: ["cloud", "cal", "mail", "fin", "note", "todo"], dim: [...CLIENTS, "link", "entity", "rss", "rem"], edges: ["trace", "d-note", "r-cal", "r-mail", "r-fin", "w-note"], hot: ["r-cal", "r-mail", "r-fin", "w-note"],
    mv: { cal: ["cal", "cloudIn1"], mail: ["mail", "cloudIn2"], fin: ["fin", "cloudIn3"], note: ["cloudOut", "note"] }, st: { cloud: "读取 · 写入" } },
  { ch: 2, t: "所以少开很多 app", x: "待办、笔记、稍后读、RSS、日历提醒、记账不再分散在各自的 app 里。它们在同一处，能互相连，任何设备都能派任务去处理它们。",
    r: "同一个 PostgreSQL 存储，Web / Telegram / CLI 共用同一套 API", e: "这是作者自己的使用取舍，不是逐项功能对等。",
    a: ["todo", "cloud"], dim: [], edges: [...GRAPH, "ring"], hot: [], ghosts: true, mv: {}, st: { cloud: "随时待命" } },
];

// First step of each chapter, for the chapter buttons.
export const CHAPTERS: { ch: 1 | 2; label: string; step: number }[] = [
  { ch: 1, label: "一 随处派发", step: 1 },
  { ch: 2, label: "二 一处全连", step: 4 },
];

export const POS: Record<string, Pt> = {
  ...Object.fromEntries(SATS.map(s => [s.key, [s.x, s.y] as Pt])),
  phone: [205, 71], tablet: [205, 155], laptop: [205, 239], cloud: [315, 220],
  cloudIn1: [300, 196], cloudIn2: [315, 286], cloudIn3: [330, 308], cloudOut: [330, 196],
};
