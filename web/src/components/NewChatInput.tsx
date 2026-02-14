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

  const handleSubmit = useCallback(async () => {
    const text = prompt.trim();
    if (!text || loading) return;

    setLoading(true);
    try {
      const res = await authFetch(`${API}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: text }),
      });
      const data = await res.json();
      mutate(`${API}/api/chat/list`);
      onCreated(data.chat_id);
    } finally {
      setLoading(false);
    }
  }, [prompt, loading, mutate, onCreated]);

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
      <div className="flex justify-end mt-2">
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
