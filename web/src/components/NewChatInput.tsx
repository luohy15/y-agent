import { useState, useCallback } from "react";
import { useSWRConfig } from "swr";
import { API, authFetch } from "../api";

interface NewChatInputProps {
  onCreated: (chatId: string) => void;
}

export default function NewChatInput({ onCreated }: NewChatInputProps) {
  const { mutate } = useSWRConfig();
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [autoApprove, setAutoApprove] = useState(() => localStorage.getItem("autoApprove") === "true");

  const handleSubmit = useCallback(async () => {
    const text = prompt.trim();
    if (!text || loading) return;

    setLoading(true);
    try {
      const res = await authFetch(`${API}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: text, auto_approve: autoApprove }),
      });
      const data = await res.json();
      mutate(`${API}/api/chat/list`);
      onCreated(data.chat_id);
    } finally {
      setLoading(false);
    }
  }, [prompt, loading, autoApprove, mutate, onCreated]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="w-full max-w-2xl px-6">
      <textarea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="What would you like to do?"
        rows={4}
        autoFocus
        className="w-full px-4 py-3 bg-sol-base02 border border-sol-base01 rounded-lg text-sm text-sol-base0 outline-none focus:border-sol-blue resize-none"
      />
      <div className="flex items-center justify-end gap-3 mt-2">
        <label className="flex items-center gap-2 text-xs text-sol-base1 cursor-pointer select-none">
          <span>Auto-approve</span>
          <button
            type="button"
            onClick={() => setAutoApprove((v) => { const next = !v; localStorage.setItem("autoApprove", String(next)); return next; })}
            className={`relative w-8 h-4 rounded-full transition-colors ${autoApprove ? "bg-sol-green" : "bg-sol-base02"}`}
          >
            <span className={`absolute top-0.5 left-0.5 w-3 h-3 rounded-full bg-sol-base3 transition-transform ${autoApprove ? "translate-x-4" : ""}`} />
          </button>
        </label>
        <button
          onClick={handleSubmit}
          disabled={!prompt.trim() || loading}
          className="px-4 py-1.5 bg-sol-blue text-sol-base03 rounded-md text-sm font-semibold cursor-pointer disabled:opacity-40 disabled:cursor-default"
        >
          {loading ? "Sending..." : "Send"}
        </button>
      </div>
    </div>
  );
}
