import type { PanelItem } from "./panelCatalog";

interface RightActivityBarProps<Key extends string> {
  items: PanelItem<Key>[];
  activePanel: Key;
  contentOpen: boolean;
  mobile?: boolean;
  onSelectPanel: (panel: Key) => void;
}

export default function RightActivityBar<Key extends string>({ items, activePanel, contentOpen, mobile, onSelectPanel }: RightActivityBarProps<Key>) {
  const handlePanelClick = (panel: Key) => {
    onSelectPanel(panel);
  };

  const btnClass = (active: boolean) => mobile
    ? `h-8 flex items-center justify-center rounded cursor-pointer shrink-0 ${active ? "text-sol-base1 bg-sol-base02" : "text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"}`
    : `w-8 h-8 flex items-center justify-center rounded cursor-pointer ${active ? "text-sol-base1 bg-sol-base02" : "text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"}`;

  return (
    <div className={mobile ? "flex items-center gap-1 px-2 py-1 border-b border-sol-base02 shrink-0 overflow-x-auto" : "hidden sm:flex shrink-0 w-10 bg-sol-base03 border-l border-sol-base02 flex-col items-center pt-2 gap-1"}>
      {items.map((item) => (
        <button
          key={item.key}
          data-right-panel={item.key}
          onClick={() => handlePanelClick(item.key)}
          className={btnClass(contentOpen && activePanel === item.key)}
          title={item.label}
        >
          {item.icon}
        </button>
      ))}
    </div>
  );
}
