import { useState, useCallback } from "react";
import { API, authFetch } from "../api";

interface ToolCall {
  id: string;
  function: { name: string; arguments: string };
  status?: string;
}

interface ApprovalModalProps {
  chatId: string;
  toolCalls: ToolCall[];
  visible: boolean;
  onApproved: () => void;
}

function truncate(s: string, n: number): string {
  if (!s) return "";
  return s.length > n ? s.slice(0, n) + "..." : s;
}

function formatToolCall(tc: ToolCall): string {
  const name = tc.function.name;
  let args: Record<string, unknown> = {};
  try { args = JSON.parse(tc.function.arguments); } catch {}

  if (name === "bash") return `$ ${truncate((args.command as string) || "", 120)}`;
  if (name === "file_read") return `read("${args.path || ""}")`;
  if (name === "file_write") return `write("${args.path || ""}")`;
  if (name === "file_edit") return `edit("${args.path || ""}")`;
  try {
    return `${name}(${truncate(JSON.stringify(args, null, 0), 120)})`;
  } catch { return name; }
}

export default function ApprovalModal({ chatId, toolCalls, visible, onApproved }: ApprovalModalProps) {
  const [decisions, setDecisions] = useState<Record<string, boolean>>({});

  const setDecision = useCallback((id: string, approved: boolean) => {
    setDecisions((prev) => ({ ...prev, [id]: approved }));
  }, []);

  const submit = useCallback(async (overrideDecisions?: Record<string, boolean>) => {
    const d = overrideDecisions || decisions;
    await authFetch(`${API}/api/chat/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, decisions: d }),
    });
    setDecisions({});
    onApproved();
  }, [chatId, decisions, onApproved]);

  const submitAll = useCallback((approved: boolean) => {
    const d: Record<string, boolean> = {};
    for (const tc of toolCalls) d[tc.id] = approved;
    submit(d);
  }, [toolCalls, submit]);

  if (!visible || toolCalls.length === 0) return null;

  const allDecided = toolCalls.every((tc) => tc.id in decisions);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-sol-base03 border border-sol-base01 rounded-lg shadow-lg w-full max-w-xl mx-4 p-4 flex flex-col gap-3">
        <div className="text-sm text-sol-yellow font-semibold">Tool Approval</div>
        {toolCalls.map((tc) => (
          <div key={tc.id} className="flex items-center gap-2">
            <span className="text-[0.8rem] font-mono text-sol-cyan flex-1 truncate">
              {formatToolCall(tc)}
            </span>
            <button
              onClick={() => setDecision(tc.id, true)}
              className={`px-2 py-1 rounded text-xs font-semibold cursor-pointer ${
                decisions[tc.id] === true
                  ? "bg-sol-green text-sol-base03"
                  : "border border-sol-green text-sol-green"
              }`}
            >
              Approve
            </button>
            <button
              onClick={() => setDecision(tc.id, false)}
              className={`px-2 py-1 rounded text-xs font-semibold cursor-pointer ${
                decisions[tc.id] === false
                  ? "bg-sol-red text-sol-base03"
                  : "border border-sol-red text-sol-red"
              }`}
            >
              Deny
            </button>
          </div>
        ))}
        <div className="flex items-center gap-2 pt-2 border-t border-sol-base02">
          <button
            onClick={() => submitAll(true)}
            className="px-2 py-1 bg-sol-green text-sol-base03 rounded text-xs font-semibold cursor-pointer"
          >
            Approve All
          </button>
          <button
            onClick={() => submitAll(false)}
            className="px-2 py-1 bg-sol-red text-sol-base03 rounded text-xs font-semibold cursor-pointer"
          >
            Deny All
          </button>
          <div className="flex-1" />
          {allDecided && (
            <button
              onClick={() => submit()}
              className="px-3 py-1 bg-sol-blue text-sol-base03 rounded text-xs font-semibold cursor-pointer"
            >
              Submit
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
