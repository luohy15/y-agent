import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { API } from "../api";

interface NoteShareResponse {
  note_id: string;
  content_key: string;
  front_matter?: { title?: string; tags?: string[]; [key: string]: unknown };
  content: string;
  created_at?: string;
  updated_at?: string;
}

function stripFrontMatter(content: string): string {
  if (!content.startsWith("---\n")) return content;
  const end = content.indexOf("\n---\n", 4);
  return end >= 0 ? content.slice(end + 5).replace(/^\n/, "") : content;
}

function titleFromContent(content: string): string | null {
  const body = stripFrontMatter(content);
  const heading = body.split("\n").find((line) => /^#\s+/.test(line));
  return heading ? heading.replace(/^#\s+/, "").trim() : null;
}

export default function ShareNoteView() {
  const { shareId } = useParams<{ shareId: string }>();
  const [searchParams] = useSearchParams();
  const [data, setData] = useState<NoteShareResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [needsPassword, setNeedsPassword] = useState(false);
  const [passwordInput, setPasswordInput] = useState("");
  const [shareLabel, setShareLabel] = useState("share");

  const fetchShare = useCallback(async (password?: string) => {
    if (!shareId) return;
    setLoading(true);
    setError(null);
    const url = `${API}/api/note/share?share_id=${encodeURIComponent(shareId)}${password ? `&password=${encodeURIComponent(password)}` : ""}`;
    const res = await fetch(url);
    if (res.status === 401) {
      setNeedsPassword(true);
      setLoading(false);
      return;
    }
    if (res.status === 403) {
      setNeedsPassword(true);
      setLoading(false);
      throw new Error("Invalid password");
    }
    if (res.status === 429) {
      setLoading(false);
      throw new Error("Too many attempts. Try again later.");
    }
    if (!res.ok) {
      setLoading(false);
      throw new Error("Shared note not found");
    }
    const body: NoteShareResponse = await res.json();
    setData(body);
    setNeedsPassword(false);
    setLoading(false);
  }, [shareId]);

  useEffect(() => {
    const urlPassword = searchParams.get("p") || undefined;
    fetchShare(urlPassword).catch((err) => setError(err.message || "Failed to load shared note"));
  }, [fetchShare, searchParams]);

  const title = useMemo(() => {
    if (!data) return "Shared Note";
    return data.front_matter?.title || titleFromContent(data.content) || data.content_key;
  }, [data]);

  const submitPassword = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      await fetchShare(passwordInput);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load shared note");
    }
  };

  if (loading) {
    return <div className="min-h-screen bg-sol-base03 text-sol-base1 flex items-center justify-center text-sm">Loading shared note...</div>;
  }

  if (needsPassword && !data) {
    return (
      <div className="min-h-screen bg-sol-base03 text-sol-base1 flex items-center justify-center p-4">
        <form onSubmit={submitPassword} className="w-full max-w-sm border border-sol-base02 rounded p-4 bg-sol-base03">
          <h1 className="text-lg font-semibold mb-2">Password required</h1>
          {error && <div className="text-sol-red text-sm mb-2">{error}</div>}
          <input
            type="password"
            value={passwordInput}
            onChange={(event) => setPasswordInput(event.target.value)}
            placeholder="Password"
            className="w-full px-3 py-2 bg-sol-base02 text-sol-base1 rounded outline-none mb-3"
            autoFocus
          />
          <button type="submit" className="w-full px-3 py-2 bg-sol-blue text-sol-base03 rounded font-semibold cursor-pointer">
            Open note
          </button>
        </form>
      </div>
    );
  }

  if (error || !data) {
    return <div className="min-h-screen bg-sol-base03 text-sol-red flex items-center justify-center text-sm">{error || "Shared note not found"}</div>;
  }

  return (
    <div className="min-h-screen bg-sol-base03 text-sol-base1">
      <header className="sticky top-0 z-10 bg-sol-base03/95 border-b border-sol-base02 px-4 py-3">
        <div className="max-w-4xl mx-auto flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="text-xs text-sol-base01 font-mono truncate">{data.content_key}</div>
            <h1 className="text-lg font-semibold truncate">{title}</h1>
          </div>
          <button
            onClick={() => { navigator.clipboard.writeText(window.location.href); setShareLabel("copied!"); setTimeout(() => setShareLabel("share"), 1500); }}
            className="font-mono cursor-pointer px-2 py-1 rounded text-xs font-semibold bg-sol-base02 text-sol-base01 hover:text-sol-base0"
          >
            {shareLabel}
          </button>
        </div>
      </header>
      <main className="max-w-4xl mx-auto px-4 py-6">
        {data.front_matter?.tags && data.front_matter.tags.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-4">
            {data.front_matter.tags.map((tag) => (
              <span key={tag} className="text-[0.65rem] bg-sol-base02 text-sol-base0 px-1.5 py-0.5 rounded">{tag}</span>
            ))}
          </div>
        )}
        <article className="prose prose-invert max-w-none prose-pre:bg-sol-base02 prose-code:text-sol-cyan">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{stripFrontMatter(data.content)}</ReactMarkdown>
        </article>
      </main>
    </div>
  );
}
