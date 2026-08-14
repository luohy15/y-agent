import { useMemo } from "react";
import type { PanelItem } from "./panelCatalog";

interface RightActivityBarProps<Key extends string> {
  items: PanelItem<Key>[];
  activePanel: Key;
  onSelectPanel: (panel: Key) => void;
  onRefresh: () => void;
  onClose: () => void;
  refreshing?: boolean;
  /**
   * Keys rendered dimmed and inert after the live items (design-3158).
   * Default empty: authenticated app keeps its existing selection behavior.
   * Unavailable keys may appear in `items` (for icon/label) or only here with
   * a matching entry still required in `items` so the icon can render.
   */
  unavailableKeys?: readonly Key[];
  /** Optional title override for an unavailable key. */
  unavailableTitles?: Partial<Record<Key, string>>;
  /** Optional click handler for unavailable items (e.g. demo toast). Default: no-op. */
  onUnavailableSelect?: (key: Key) => void;
}

// Round-2 gap closure (plan-3046-right-sidebar.md R2/R3): a single horizontal
// header row, part of the resizable drawer content pane, so it disappears
// with the drawer when collapsed. Category buttons switch the visible panel
// only — clicking the active category no longer collapses the drawer, that
// is now solely `onClose`'s job (desktop Close / mobile Close, both wired by
// the caller). Desktop and mobile render the identical shape.
export default function RightActivityBar<Key extends string>({ items, activePanel, onSelectPanel, onRefresh, onClose, refreshing, unavailableKeys = [], unavailableTitles, onUnavailableSelect }: RightActivityBarProps<Key>) {
  const unavailableSet = useMemo(() => new Set(unavailableKeys), [unavailableKeys]);
  const liveItems = useMemo(
    () => items.filter((item) => !unavailableSet.has(item.key)),
    [items, unavailableSet],
  );
  const unavailableItems = useMemo(() => {
    if (unavailableKeys.length === 0) return [] as PanelItem<Key>[];
    const byKey = new Map(items.map((item) => [item.key, item]));
    const result: PanelItem<Key>[] = [];
    const seen = new Set<Key>();
    for (const key of unavailableKeys) {
      if (seen.has(key)) continue;
      const item = byKey.get(key);
      if (!item) continue;
      seen.add(key);
      result.push(item);
    }
    return result;
  }, [unavailableKeys, items]);

  const btnClass = (active: boolean) =>
    `h-8 w-8 flex items-center justify-center rounded cursor-pointer shrink-0 ${active ? "text-sol-base1 bg-sol-base02" : "text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"}`;

  return (
    <div className="flex items-center justify-between gap-1 px-2 py-0.5 border-b border-sol-base02 shrink-0">
      <div className="flex items-center gap-1 overflow-x-auto">
        {liveItems.map((item) => (
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
        {unavailableItems.map((item) => {
          const title = unavailableTitles?.[item.key] ?? `${item.label} — not part of the demo`;
          return (
            <button
              key={`unavailable:${item.key}`}
              type="button"
              data-right-panel={item.key}
              data-unavailable={item.label}
              disabled={!onUnavailableSelect}
              onClick={() => onUnavailableSelect?.(item.key)}
              className="h-8 w-8 flex items-center justify-center rounded shrink-0 text-sol-base01/40 cursor-not-allowed"
              title={title}
              aria-disabled="true"
            >
              {item.icon}
            </button>
          );
        })}
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
