import type { PanelItem } from "./panelCatalog";

interface RightActivityBarProps<Key extends string> {
  items: PanelItem<Key>[];
  activePanel: Key;
  onSelectPanel: (panel: Key) => void;
  onRefresh: () => void;
  onClose: () => void;
  refreshing?: boolean;
}

// Round-2 gap closure (plan-3046-right-sidebar.md R2/R3): a single horizontal
// header row, part of the resizable drawer content pane, so it disappears
// with the drawer when collapsed. Category buttons switch the visible panel
// only — clicking the active category no longer collapses the drawer, that
// is now solely `onClose`'s job (desktop Close / mobile Close, both wired by
// the caller). Desktop and mobile render the identical shape.
export default function RightActivityBar<Key extends string>({ items, activePanel, onSelectPanel, onRefresh, onClose, refreshing }: RightActivityBarProps<Key>) {
  const btnClass = (active: boolean) =>
    `h-8 w-8 flex items-center justify-center rounded cursor-pointer shrink-0 ${active ? "text-sol-base1 bg-sol-base02" : "text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"}`;

  return (
    <div className="flex items-center justify-between gap-1 px-2 py-0.5 border-b border-sol-base02 shrink-0">
      <div className="flex items-center gap-1 overflow-x-auto">
        {items.map((item) => (
          <button
            key={item.key}
            data-right-panel={item.key}
            onClick={() => onSelectPanel(item.key)}
            className={btnClass(activePanel === item.key)}
            title={item.label}
          >
            {item.icon}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-1 shrink-0">
        <button
          onClick={onRefresh}
          className="p-1 text-sol-base01 hover:text-sol-base1 rounded cursor-pointer"
          title="Refresh"
        >
          <svg className={`w-3.5 h-3.5 transition-transform ${refreshing ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        </button>
        <button
          onClick={onClose}
          className="p-1 text-sol-base01 hover:text-sol-base1 rounded cursor-pointer"
          title="Close"
        >
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
    </div>
  );
}
