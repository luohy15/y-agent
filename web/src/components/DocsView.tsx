import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const DEFAULT_SLUG = "getting-started";

export default function DocsView() {
  const { slug } = useParams<{ slug?: string }>();
  const effectiveSlug = slug || DEFAULT_SLUG;
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setContent(null);
    setError(null);
    fetch(`/docs-content/${effectiveSlug}.md`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const ctype = res.headers.get("content-type") || "";
        if (ctype.includes("text/html")) throw new Error("Doc not found");
        return res.text();
      })
      .then((text) => {
        if (!cancelled) setContent(text);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message || e));
      });
    return () => {
      cancelled = true;
    };
  }, [effectiveSlug]);

  return (
    <div className="min-h-screen bg-sol-base03 text-sol-base0">
      <header className="max-w-3xl mx-auto px-6 pt-6 pb-3 flex items-center justify-between border-b border-sol-base02">
        <Link to="/" className="text-sol-base1 font-semibold tracking-tight hover:text-sol-cyan">y-agent</Link>
        <nav className="flex items-center gap-5 text-sm">
          <Link to="/docs" className="text-sol-base1 hover:text-sol-cyan">Docs</Link>
          <a href="https://github.com/luohy15/y-agent" target="_blank" rel="noopener noreferrer" className="text-sol-base1 hover:text-sol-cyan">GitHub</a>
        </nav>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-10">
        {error ? (
          <div className="text-sm">
            <p className="text-sol-red">Doc not found.</p>
            <p className="mt-2 text-sol-base1">
              <Link to="/docs" className="hover:text-sol-cyan underline">Back to Docs</Link>
            </p>
          </div>
        ) : content === null ? (
          <div className="text-sm text-sol-base01">Loading…</div>
        ) : (
          <article className="prose prose-sm max-w-none text-sol-base0">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
          </article>
        )}
      </main>
    </div>
  );
}
