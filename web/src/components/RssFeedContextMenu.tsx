import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

interface RssFeedContextMenuProps {
  x: number;
  y: number;
  onClose: () => void;
  onRename: () => void;
  onDelete: () => void;
}

export default function RssFeedContextMenu({ x, y, onClose, onRename, onDelete }: RssFeedContextMenuProps) {
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

  const items: { label: string; action: () => void }[] = [
    { label: "Rename", action: () => { onRename(); onClose(); } },
    { label: "Delete", action: () => { onDelete(); onClose(); } },
  ];

  return createPortal(
    <div
      ref={menuRef}
      className="fixed z-[100] bg-sol-base02 border border-sol-base01 rounded shadow-lg py-0.5"
      style={{ left: x, top: y }}
    >
      {items.map((item) => (
        <button
          key={item.label}
          onClick={item.action}
          className="w-full text-left px-2.5 py-0.5 text-xs text-sol-base0 hover:bg-sol-base01/30 cursor-pointer"
        >
          {item.label}
        </button>
      ))}
    </div>,
    document.body,
  );
}
