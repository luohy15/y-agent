import { useEffect, useState } from "react";

export type TocItem = {
  id: string;
  text: string;
  level: number;
};

type Props = {
  items: TocItem[];
};

export default function DocsToc({ items }: Props) {
  const [activeId, setActiveId] = useState<string | null>(null);

  useEffect(() => {
    if (items.length === 0) {
      setActiveId(null);
      return;
    }
    const els = items
      .map((it) => document.getElementById(it.id))
      .filter((el): el is HTMLElement => !!el);
    if (els.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const intersecting = entries.filter((e) => e.isIntersecting);
        if (intersecting.length === 0) return;
        intersecting.sort(
          (a, b) => a.target.getBoundingClientRect().top - b.target.getBoundingClientRect().top,
        );
        setActiveId(intersecting[0].target.id);
      },
      { rootMargin: "-40% 0px -55% 0px", threshold: 0 },
    );
    els.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [items]);

  if (items.length === 0) {
    return null;
  }

  return (
    <nav aria-label="On this page" className="text-sm">
      <div className="text-[11px] uppercase tracking-wider text-sol-base01 mb-2">
        On this page
      </div>
      <ul className="flex flex-col gap-1">
        {items.map((it) => (
          <li
            key={it.id}
            className={it.level === 3 ? "pl-3" : ""}
          >
            <a
              href={`#${it.id}`}
              onClick={(e) => {
                e.preventDefault();
                const el = document.getElementById(it.id);
                if (el) {
                  el.scrollIntoView({ behavior: "smooth", block: "start" });
                  history.replaceState(null, "", `#${it.id}`);
                  setActiveId(it.id);
                }
              }}
              className={`block py-0.5 transition-colors ${
                activeId === it.id
                  ? "text-sol-cyan"
                  : "text-sol-base1 hover:text-sol-cyan"
              }`}
            >
              {it.text}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
