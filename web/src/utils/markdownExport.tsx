import DOMPurify from "dompurify";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";

export type MarkdownExportFormat = "md" | "html" | "pdf";

export interface MarkdownHeading {
  id: string;
  text: string;
  level: 2 | 3;
}

export function exportFilename(path: string, format: MarkdownExportFormat): string {
  const basename = path.replace(/\\/g, "/").split("/").pop() || "download";
  const stem = basename.replace(/\.[^.]*$/, "") || basename;
  return `${stem}.${format}`;
}

export function availableFormats(path: string): MarkdownExportFormat[] {
  return /\.md$/i.test(path) ? ["md", "html", "pdf"] : ["md"];
}

export function renderMarkdownBody(markdown: string): string {
  const html = renderToStaticMarkup(
    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSlug]}>
      {markdown}
    </ReactMarkdown>
  );
  return DOMPurify.sanitize(html);
}

export function extractMarkdownHeadings(root: ParentNode): MarkdownHeading[] {
  return Array.from(root.querySelectorAll<HTMLElement>("h2[id], h3[id]")).map((element) => ({
    id: element.id,
    text: element.textContent || "",
    level: element.tagName === "H3" ? 3 : 2,
  }));
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
  }[character]!));
}

function renderTableOfContents(bodyHtml: string): string {
  const document = new DOMParser().parseFromString(bodyHtml, "text/html");
  const headings = extractMarkdownHeadings(document);
  if (headings.length === 0) return "";

  return `<nav class="markdown-toc" aria-label="Table of contents">
  <div class="markdown-toc-title">Contents</div>
  <ol>
${headings.map((heading) => `    <li class="markdown-toc-level-${heading.level}"><a href="#${escapeHtml(heading.id)}">${escapeHtml(heading.text)}</a></li>`).join("\n")}
  </ol>
</nav>`;
}

function injectTableOfContents(bodyHtml: string): string {
  const toc = renderTableOfContents(bodyHtml);
  if (!toc) return bodyHtml;

  const h1Match = /<h1[^>]*>.*?<\/h1>/is.exec(bodyHtml);
  if (!h1Match) return `${toc}\n${bodyHtml}`;

  const insertAt = h1Match.index + h1Match[0].length;
  return `${bodyHtml.slice(0, insertAt)}\n${toc}\n${bodyHtml.slice(insertAt)}`;
}

export async function requestPdfExport(
  fetchImpl: (url: string, init?: RequestInit) => Promise<Response>,
  url: string,
  html: string,
  filename: string
): Promise<Blob> {
  const res = await fetchImpl(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ html, filename }),
  });
  if (!res.ok) {
    let detail = "";
    try {
      detail = (await res.json())?.detail ?? "";
    } catch {
      // response body wasn't JSON; fall through to the generic message
    }
    throw new Error(detail || `PDF export failed (${res.status})`);
  }
  return res.blob();
}

export function buildHtmlDocument({ title, bodyHtml }: { title: string; bodyHtml: string }): string {
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${escapeHtml(title)}</title>
  <style>
    :root {
      color-scheme: light;
      /* Explicit CJK families across macOS / Windows / Linux+Android so glyphs
         resolve to a real installed font instead of relying on the browser's
         last-resort fallback (which prints tofu on some systems). */
      --cjk-fallback: "PingFang SC", "Hiragino Sans GB", "Heiti SC", "STHeiti", "Microsoft YaHei", "微软雅黑", "SimHei", "SimSun", "Noto Sans CJK SC", "Noto Sans CJK TC", "Source Han Sans SC", "Source Han Sans CN", "WenQuanYi Micro Hei", "Droid Sans Fallback";
    }
    * { box-sizing: border-box; }
    body { max-width: 900px; margin: 0 auto; padding: 48px 40px; color: #263238; background: #fff; font: 16px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, var(--cjk-fallback), sans-serif; }
    h1, h2, h3, h4, h5, h6 { color: #1b2b34; line-height: 1.25; margin: 1.75em 0 .65em; }
    h1 { font-size: 2em; margin-top: 0; } h2 { font-size: 1.55em; } h3 { font-size: 1.25em; }
    p, ul, ol, blockquote, pre, table { margin: 0 0 1em; }
    ul, ol { padding-left: 1.6em; }
    li + li { margin-top: .25em; }
    a { color: #268bd2; text-decoration: underline; }
    .markdown-toc { break-inside: avoid; margin: 0 0 2em; padding: 1em 1.2em; border: 1px solid #cbd5d7; border-radius: 5px; background: #f8faf9; font-size: .9em; }
    .markdown-toc-title { margin-bottom: .45em; color: #1b2b34; font-weight: 600; }
    .markdown-toc ol { margin: 0; padding-left: 1.35em; }
    .markdown-toc li { margin: .15em 0; }
    .markdown-toc-level-3 { margin-left: 1.15em !important; }
    blockquote { border-left: 4px solid #93a1a1; color: #586e75; margin-left: 0; padding-left: 1em; }
    code { padding: .1em .35em; border-radius: 3px; background: #f3f5f5; font: .9em ui-monospace, SFMono-Regular, Menlo, Consolas, var(--cjk-fallback), monospace; }
    pre { overflow-x: auto; padding: 1em; border-radius: 5px; background: #f3f5f5; } pre code { padding: 0; background: transparent; }
    table { width: 100%; border-collapse: collapse; } th, td { border: 1px solid #cbd5d7; padding: .5em .7em; text-align: left; vertical-align: top; } th { background: #edf1f1; }
    img { max-width: 100%; height: auto; }
    hr { border: 0; border-top: 1px solid #cbd5d7; margin: 2em 0; }
    @media print { body { max-width: none; padding: 0; font-size: 11pt; } a { color: inherit; } pre { white-space: pre-wrap; word-break: break-word; } }
  </style>
</head>
<body>
${injectTableOfContents(bodyHtml)}
</body>
</html>`;
}
