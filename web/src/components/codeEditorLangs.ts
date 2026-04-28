import type { Extension } from "@codemirror/state";

type LangLoader = () => Promise<Extension>;

const wrapStream = async (
  importer: () => Promise<{ [k: string]: unknown }>,
  exportName: string,
): Promise<Extension> => {
  const [{ StreamLanguage }, mod] = await Promise.all([
    import("@codemirror/language"),
    importer(),
  ]);
  const parser = mod[exportName] as Parameters<typeof StreamLanguage.define>[0];
  return StreamLanguage.define(parser);
};

const loadJs = async (opts: { jsx?: boolean; typescript?: boolean }): Promise<Extension> => {
  const { javascript } = await import("@codemirror/lang-javascript");
  return javascript(opts);
};

export const langLoaders: Record<string, LangLoader> = {
  js: () => loadJs({}),
  mjs: () => loadJs({}),
  cjs: () => loadJs({}),
  jsx: () => loadJs({ jsx: true }),
  ts: () => loadJs({ typescript: true }),
  tsx: () => loadJs({ typescript: true, jsx: true }),

  py: async () => (await import("@codemirror/lang-python")).python(),

  json: async () => (await import("@codemirror/lang-json")).json(),

  md: async () => (await import("@codemirror/lang-markdown")).markdown(),
  markdown: async () => (await import("@codemirror/lang-markdown")).markdown(),

  yaml: async () => (await import("@codemirror/lang-yaml")).yaml(),
  yml: async () => (await import("@codemirror/lang-yaml")).yaml(),

  html: async () => (await import("@codemirror/lang-html")).html(),
  htm: async () => (await import("@codemirror/lang-html")).html(),

  css: async () => (await import("@codemirror/lang-css")).css(),

  xml: async () => (await import("@codemirror/lang-xml")).xml(),

  sql: async () => (await import("@codemirror/lang-sql")).sql(),

  rs: async () => (await import("@codemirror/lang-rust")).rust(),

  go: async () => (await import("@codemirror/lang-go")).go(),

  java: async () => (await import("@codemirror/lang-java")).java(),

  c: async () => (await import("@codemirror/lang-cpp")).cpp(),
  h: async () => (await import("@codemirror/lang-cpp")).cpp(),
  cc: async () => (await import("@codemirror/lang-cpp")).cpp(),
  cpp: async () => (await import("@codemirror/lang-cpp")).cpp(),
  hpp: async () => (await import("@codemirror/lang-cpp")).cpp(),
  cxx: async () => (await import("@codemirror/lang-cpp")).cpp(),
  hxx: async () => (await import("@codemirror/lang-cpp")).cpp(),

  php: async () => (await import("@codemirror/lang-php")).php(),

  vue: async () => (await import("@codemirror/lang-vue")).vue(),

  sh: () => wrapStream(() => import("@codemirror/legacy-modes/mode/shell"), "shell"),
  bash: () => wrapStream(() => import("@codemirror/legacy-modes/mode/shell"), "shell"),
  zsh: () => wrapStream(() => import("@codemirror/legacy-modes/mode/shell"), "shell"),

  toml: () => wrapStream(() => import("@codemirror/legacy-modes/mode/toml"), "toml"),

  dockerfile: () =>
    wrapStream(() => import("@codemirror/legacy-modes/mode/dockerfile"), "dockerFile"),

  lua: () => wrapStream(() => import("@codemirror/legacy-modes/mode/lua"), "lua"),
};

const langCache = new Map<string, Extension>();
const inflight = new Map<string, Promise<Extension>>();

export function getCachedLanguage(ext: string): Extension | undefined {
  return langCache.get(ext);
}

export async function loadLanguage(ext: string): Promise<Extension | null> {
  const key = ext.toLowerCase();
  const cached = langCache.get(key);
  if (cached) return cached;
  const loader = langLoaders[key];
  if (!loader) return null;
  const existing = inflight.get(key);
  if (existing) return existing;
  const p = loader()
    .then((ext) => {
      langCache.set(key, ext);
      inflight.delete(key);
      return ext;
    })
    .catch((err) => {
      inflight.delete(key);
      throw err;
    });
  inflight.set(key, p);
  return p;
}

export function resolveLangKey(filePath: string): string {
  const slash = filePath.lastIndexOf("/");
  const base = slash >= 0 ? filePath.slice(slash + 1) : filePath;
  if (base === "Dockerfile" || base.endsWith(".Dockerfile")) return "dockerfile";
  const dot = base.lastIndexOf(".");
  return dot >= 0 ? base.slice(dot + 1).toLowerCase() : "";
}
