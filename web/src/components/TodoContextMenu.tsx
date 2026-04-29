import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { API, authFetch } from "../api";
import { priorityColorClass } from "./badges";

interface TodoContextMenuProps {
  todo: { todo_id: string; status: string; priority?: string };
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

async function updateTodoPriority(todoId: string, priority: string): Promise<boolean> {
  const res = await authFetch(`${API}/api/todo/update`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ todo_id: todoId, priority }),
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

type SubmenuChild = { label: string; action: () => void; checked?: boolean; className?: string };
type MenuItem =
  | { type: "item"; label: string; action: () => void }
  | { type: "submenu"; label: string; key: string; children: SubmenuChild[] }
  | { type: "separator" };

const PRIORITY_OPTIONS = ["high", "medium", "low", "none"] as const;

export default function TodoContextMenu({ todo, x, y, onClose, onAction, onChatListRefresh }: TodoContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);
  const submenuRef = useRef<HTMLDivElement>(null);
  const submenuRowRef = useRef<HTMLDivElement>(null);
  const [openSubmenu, setOpenSubmenu] = useState<string | null>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const [submenuFlip, setSubmenuFlip] = useState<{ up: boolean; left: boolean } | null>(null);

  useLayoutEffect(() => {
    if (!menuRef.current) return;
    const rect = menuRef.current.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const margin = 4;
    let left = x;
    let top = y;
    if (left + rect.width > vw - margin) left = Math.max(margin, vw - rect.width - margin);
    if (top + rect.height > vh - margin) top = Math.max(margin, y - rect.height);
    setPos({ left, top });
  }, [x, y]);

  useLayoutEffect(() => {
    if (!openSubmenu) {
      setSubmenuFlip(null);
      return;
    }
    if (!submenuRef.current || !submenuRowRef.current) return;
    const subRect = submenuRef.current.getBoundingClientRect();
    const rowRect = submenuRowRef.current.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const margin = 4;
    const flipLeft = rowRect.right + subRect.width > vw - margin;
    const flipUp = rowRect.top + subRect.height > vh - margin;
    setSubmenuFlip({ up: flipUp, left: flipLeft });
  }, [openSubmenu]);

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

  const currentPriority = todo.priority || "none";

  const items: MenuItem[] = [];

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
  items.push({ type: "separator" });

  items.push({
    type: "submenu",
    label: "Set priority",
    key: "priority",
    children: PRIORITY_OPTIONS.map((p) => ({
      label: p,
      checked: p === currentPriority,
      className: priorityColorClass(p),
      action: async () => {
        await updateTodoPriority(todo.todo_id, p);
        onAction();
        onClose();
      },
    })),
  });
  items.push({ type: "separator" });

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

  return createPortal(
    <div
      ref={menuRef}
      className="fixed z-[100] bg-sol-base02 border border-sol-base01 rounded shadow-lg py-0.5 min-w-[8rem]"
      style={{
        left: pos?.left ?? x,
        top: pos?.top ?? y,
        visibility: pos ? "visible" : "hidden",
      }}
    >
      {items.map((item, idx) => {
        if (item.type === "separator") {
          return <div key={`sep-${idx}`} className="border-t border-sol-base01/30 my-0.5" />;
        }
        if (item.type === "submenu") {
          const open = openSubmenu === item.key;
          const flip = open ? submenuFlip : null;
          const submenuPosClass = [
            flip?.left ? "right-full mr-0.5" : "left-full ml-0.5",
            flip?.up ? "bottom-0 -mb-0.5" : "top-0 -mt-0.5",
          ].join(" ");
          return (
            <div
              key={item.key}
              ref={open ? submenuRowRef : undefined}
              className="relative"
              onMouseEnter={() => setOpenSubmenu(item.key)}
            >
              <div className="flex items-center justify-between gap-3 px-2.5 py-0.5 text-xs text-sol-base0 hover:bg-sol-base01/30 cursor-default">
                <span>{item.label}</span>
                <span className="text-sol-base01">{"▸"}</span>
              </div>
              {open && (
                <div
                  ref={submenuRef}
                  className={`absolute ${submenuPosClass} bg-sol-base02 border border-sol-base01 rounded shadow-lg py-0.5 min-w-[6rem]`}
                  style={{ visibility: submenuFlip ? "visible" : "hidden" }}
                >
                  {item.children.map((c) => (
                    <button
                      key={c.label}
                      onClick={c.action}
                      className={`w-full text-left px-2.5 py-0.5 text-xs hover:bg-sol-base01/30 cursor-pointer flex items-center gap-1.5 ${c.className || "text-sol-base0"}`}
                    >
                      <span className="w-2.5 shrink-0 text-sol-base0">{c.checked ? "✓" : ""}</span>
                      <span>{c.label}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        }
        return (
          <button
            key={item.label}
            onClick={item.action}
            onMouseEnter={() => setOpenSubmenu(null)}
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
