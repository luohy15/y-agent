import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSlug from "rehype-slug";
import DocsSidebar, { type DocsItem } from "./DocsSidebar";
import DocsToc, { type TocItem } from "./DocsToc";

const DEFAULT_SLUG = "getting-started";
const GITHUB_URL = "https://github.com/luohy15/y-agent";

function stripFrontMatter(text: string): string {
  if (!text.startsWith("---")) return text;
  const end = text.indexOf("\n---", 3);
  if (end === -1) return text;
  const after = text.indexOf("\n", end + 4);
  return after === -1 ? "" : text.slice(after + 1);
}

export default function DocsView() {
  const { slug } = useParams<{ slug?: string }>();
  const effectiveSlug = slug || DEFAULT_SLUG;

  const [content, setContent] = useState<string | null>(null);
  const [contentError, setContentError] = useState<string | null>(null);

  const [manifest, setManifest] = useState<DocsItem[] | null>(null);
  const [manifestError, setManifestError] = useState<string | null>(null);

  const [tocItems, setTocItems] = useState<TocItem[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const articleRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/docs-content/manifest.json")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        if (cancelled) return;
        if (Array.isArray(data?.items)) setManifest(data.items as DocsItem[]);
        else throw new Error("malformed manifest");
      })
      .catch((e) => {
        if (!cancelled) setManifestError(String(e?.message || e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setContent(null);
    setContentError(null);
    setTocItems([]);
    fetch(`/docs-content/${effectiveSlug}.md`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const ctype = res.headers.get("content-type") || "";
        if (ctype.includes("text/html")) throw new Error("Doc not found");
        return res.text();
      })
      .then((text) => {
        if (!cancelled) setContent(stripFrontMatter(text));
      })
      .catch((e) => {
        if (!cancelled) setContentError(String(e?.message || e));
      });
    return () => {
      cancelled = true;
    };
  }, [effectiveSlug]);

  useEffect(() => {
    if (content === null) return;
    const article = articleRef.current;
    if (!article) return;
    // Defer until after react-markdown commits the DOM
    const id = window.requestAnimationFrame(() => {
      const headings = Array.from(
        article.querySelectorAll<HTMLElement>("h2[id], h3[id]"),
      );
      const items = headings.map((h) => ({
        id: h.id,
        text: h.textContent || "",
        level: h.tagName === "H2" ? 2 : 3,
      }));
      setTocItems(items);
    });
    return () => window.cancelAnimationFrame(id);
  }, [content]);

  // Close drawer on slug change (mobile UX)
  useEffect(() => {
    setDrawerOpen(false);
  }, [effectiveSlug]);

  const markdownComponents = useMemo(
    () => ({
      a: ({
        href,
        children,
        ...props
      }: {
        href?: string;
        children?: React.ReactNode;
      } & React.AnchorHTMLAttributes<HTMLAnchorElement>) => {
        if (!href) return <a {...props}>{children}</a>;
        const isExternal = /^(https?:)?\/\//.test(href) || href.startsWith("mailto:");
        if (isExternal) {
          return (
            <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
              {children}
            </a>
          );
        }
        // Internal: rewrite relative .md links to /docs/<slug>
        const mdMatch = href.match(/^(?:\.?\/)?([^#?]+)\.md(#.*)?$/);
        if (mdMatch) {
          return (
            <Link to={`/docs/${mdMatch[1]}${mdMatch[2] || ""}`} {...(props as object)}>
              {children}
            </Link>
          );
        }
        return (
          <a href={href} {...props}>
            {children}
          </a>
        );
      },
    }),
    [],
  );

  return (
    <div className="min-h-screen bg-sol-base03 text-sol-base0">
      <header className="sticky top-0 z-20 bg-sol-base03/95 backdrop-blur border-b border-sol-base02">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-12 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="md:hidden text-sol-base1 hover:text-sol-cyan p-1 -ml-1"
              aria-label="Toggle docs sidebar"
              onClick={() => setDrawerOpen((v) => !v)}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
            </button>
            <Link to="/" className="text-sol-base1 font-semibold tracking-tight hover:text-sol-cyan">
              y-agent
            </Link>
            <span className="text-sol-base01 text-sm hidden sm:inline">/ Docs</span>
          </div>
          <nav className="flex items-center gap-5 text-sm">
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="text-sol-base1 hover:text-sol-cyan"
            >
              GitHub
            </a>
          </nav>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 flex gap-6">
        {/* Left sidebar (desktop) */}
        <aside className="hidden md:block w-56 shrink-0 sticky top-12 self-start max-h-[calc(100vh-3rem)] overflow-y-auto">
          <DocsSidebar items={manifest} error={manifestError} />
        </aside>

        {/* Mobile drawer */}
        {drawerOpen && (
          <div
            className="fixed inset-0 z-30 md:hidden"
            onClick={() => setDrawerOpen(false)}
          >
            <div className="absolute inset-0 bg-black/50" />
            <div
              className="absolute inset-y-0 left-0 w-64 bg-sol-base03 border-r border-sol-base02 overflow-y-auto"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="px-4 pt-3 flex items-center justify-between">
                <Link
                  to="/"
                  className="text-sol-base1 font-semibold hover:text-sol-cyan"
                  onClick={() => setDrawerOpen(false)}
                >
                  y-agent
                </Link>
                <button
                  type="button"
                  aria-label="Close docs sidebar"
                  className="text-sol-base1 hover:text-sol-cyan p-1"
                  onClick={() => setDrawerOpen(false)}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
              </div>
              <div className="px-2">
                <DocsSidebar
                  items={manifest}
                  error={manifestError}
                  onNavigate={() => setDrawerOpen(false)}
                />
              </div>
            </div>
          </div>
        )}

        {/* Middle: content */}
        <main className="flex-1 min-w-0 py-8">
          {contentError ? (
            <div className="text-sm">
              <p className="text-sol-red">Doc not found.</p>
              <p className="mt-2 text-sol-base1">
                <Link to="/docs/getting-started" className="hover:text-sol-cyan underline">
                  Back to Getting started
                </Link>
              </p>
            </div>
          ) : content === null ? (
            <div className="text-sm text-sol-base01">Loading…</div>
          ) : (
            <article
              ref={articleRef}
              className="prose prose-sm prose-invert max-w-[720px] text-sol-base0 prose-headings:text-sol-base1 prose-a:text-sol-cyan prose-strong:text-sol-base1 prose-code:text-sol-yellow prose-code:before:content-none prose-code:after:content-none prose-pre:bg-sol-base02 prose-pre:text-sol-base0"
            >
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeSlug]}
                components={markdownComponents}
              >
                {content}
              </ReactMarkdown>
            </article>
          )}
        </main>

        {/* Right: TOC */}
        <aside className="hidden lg:block w-48 shrink-0 sticky top-12 self-start max-h-[calc(100vh-3rem)] overflow-y-auto py-8">
          <DocsToc items={tocItems} />
        </aside>
      </div>
    </div>
  );
}
