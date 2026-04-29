import { NavLink } from "react-router";

export type DocsItem = {
  slug: string;
  title: string;
  category?: string;
  order?: number;
};

type Props = {
  items: DocsItem[] | null;
  error: string | null;
  onNavigate?: () => void;
};

function groupByCategory(items: DocsItem[]): { category: string; items: DocsItem[] }[] {
  const seen = new Map<string, DocsItem[]>();
  for (const it of items) {
    const cat = it.category || "Docs";
    const arr = seen.get(cat) ?? [];
    arr.push(it);
    seen.set(cat, arr);
  }
  return Array.from(seen.entries()).map(([category, items]) => ({ category, items }));
}

export default function DocsSidebar({ items, error, onNavigate }: Props) {
  return (
    <nav className="flex flex-col gap-5 py-6 pr-4 text-sm">
      {error ? (
        <div className="text-sol-red text-xs px-2">Failed to load docs index.</div>
      ) : items === null ? (
        <div className="text-sol-base01 text-xs px-2">Loading…</div>
      ) : (
        groupByCategory(items).map(({ category, items: group }) => (
          <div key={category} className="flex flex-col">
            <div className="text-[11px] uppercase tracking-wider text-sol-base01 px-2 mb-1">
              {category}
            </div>
            <ul className="flex flex-col">
              {group.map((it) => (
                <li key={it.slug}>
                  <NavLink
                    to={`/docs/${it.slug}`}
                    onClick={onNavigate}
                    className={({ isActive }) =>
                      `block pl-2 pr-2 py-1 border-l text-sol-base1 hover:text-sol-cyan transition-colors ${
                        isActive
                          ? "border-sol-cyan text-sol-cyan"
                          : "border-transparent"
                      }`
                    }
                  >
                    {it.title}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))
      )}
    </nav>
  );
}
