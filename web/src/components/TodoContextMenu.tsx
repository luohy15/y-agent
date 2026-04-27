import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { API, authFetch } from "../api";

interface TodoContextMenuProps {
  todo: { todo_id: string; status: string };
  x: number;
  y: number;
  onClose: () => void;
  onAction: () => void;
  onChatListRefresh?: () => void;
}

async function changeTodoStatus(todoId: string, status: string): Promise<boolean> {
  const res = await authFetch(`${API}/api/todo/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ todo_id: todoId, status }),
  });
  return res.ok;
}

async function markTraceRead(traceId: string): Promise<boolean> {
  const res = await authFetch(`${API}/api/chat/trace/read`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ trace_id: traceId }),
  });
  return res.ok;
}

async function markTraceUnread(traceId: string): Promise<boolean> {
  const res = await authFetch(`${API}/api/chat/trace/unread`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ trace_id: traceId }),
  });
  return res.ok;
}

type MenuItem = { type: "item"; label: string; action: () => void } | { type: "separator" };

export default function TodoContextMenu({ todo, x, y, onClose, onAction, onChatListRefresh }: TodoContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) onClose();
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    const handleScroll = () => onClose();
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    window.addEventListener("scroll", handleScroll, true);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
      window.removeEventListener("scroll", handleScroll, true);
    };
  }, [onClose]);

  const items: MenuItem[] = [];

  if (todo.status === "pending") {
    items.push({
      type: "item",
      label: "Activate",
      action: async () => { await changeTodoStatus(todo.todo_id, "active"); onAction(); onClose(); },
    });
    items.push({
      type: "item",
      label: "Delete",
      action: async () => { await changeTodoStatus(todo.todo_id, "deleted"); onAction(); onClose(); },
    });
  }
  if (todo.status === "active") {
    items.push({
      type: "item",
      label: "Finish",
      action: async () => { await changeTodoStatus(todo.todo_id, "completed"); onAction(); onClose(); },
    });
    items.push({
      type: "item",
      label: "Deactivate",
      action: async () => { await changeTodoStatus(todo.todo_id, "pending"); onAction(); onClose(); },
    });
    items.push({
      type: "item",
      label: "Delete",
      action: async () => { await changeTodoStatus(todo.todo_id, "deleted"); onAction(); onClose(); },
    });
  }
  if (todo.status === "completed") {
    items.push({
      type: "item",
      label: "Reopen",
      action: async () => { await changeTodoStatus(todo.todo_id, "active"); onAction(); onClose(); },
    });
    items.push({
      type: "item",
      label: "Delete",
      action: async () => { await changeTodoStatus(todo.todo_id, "deleted"); onAction(); onClose(); },
    });
  }
  if (todo.status === "deleted") {
    items.push({
      type: "item",
      label: "Re-add",
      action: async () => { await changeTodoStatus(todo.todo_id, "pending"); onAction(); onClose(); },
    });
    items.push({
      type: "item",
      label: "Reopen",
      action: async () => { await changeTodoStatus(todo.todo_id, "active"); onAction(); onClose(); },
    });
    items.push({
      type: "item",
      label: "Finish",
      action: async () => { await changeTodoStatus(todo.todo_id, "completed"); onAction(); onClose(); },
    });
  }

  if (items.length > 0) {
    items.push({ type: "separator" });
  }
  items.push({
    type: "item",
    label: "Mark read",
    action: async () => {
      await markTraceRead(todo.todo_id);
      onChatListRefresh?.();
      onAction();
      onClose();
    },
  });
  items.push({
    type: "item",
    label: "Mark unread",
    action: async () => {
      await markTraceUnread(todo.todo_id);
      onChatListRefresh?.();
      onAction();
      onClose();
    },
  });

  if (items.length === 0) return null;

  return createPortal(
    <div
      ref={menuRef}
      className="fixed z-[100] bg-sol-base02 border border-sol-base01 rounded shadow-lg py-0.5"
      style={{ left: x, top: y }}
    >
      {items.map((item, idx) => {
        if (item.type === "separator") {
          return <div key={`sep-${idx}`} className="border-t border-sol-base01/30 my-0.5" />;
        }
        return (
          <button
            key={item.label}
            onClick={item.action}
            className="w-full text-left px-2.5 py-0.5 text-xs text-sol-base0 hover:bg-sol-base01/30 cursor-pointer"
          >
            {item.label}
          </button>
        );
      })}
    </div>,
    document.body,
  );
}
