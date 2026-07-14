import { useEffect, useState } from "react";
import { useActiveTocId, type TocItem } from "./DocsToc";

type Props = {
  items: TocItem[];
};

/**
 * Below-lg table of contents: a floating button fixed under the sticky share
 * header that opens a dismissible dropdown. Mirrors ChatToc's mobile pattern
 * so the TOC affordance is consistent across the app. Hidden entirely when
 * there are fewer than 2 headings (a single-entry TOC has nothing to jump to).
 */
export default function MobileToc({ items }: Props) {
  const [open, setOpen] = useState(false);
  const activeId = useActiveTocId(items);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open]);

  if (items.length < 2) {
    return null;
  }

  const scrollTo = (id: string) => {
    const el = document.getElementById(id);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
      history.replaceState(null, "", `#${id}`);
    }
    setOpen(false);
  };

  return (
    <div className="lg:hidden fixed top-16 right-3 z-30">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label="Table of contents"
        aria-expanded={open}
        className={`w-9 h-9 rounded-lg border flex items-center justify-center cursor-pointer shadow-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-sol-cyan focus-visible:outline-offset-2 ${
          open ? "text-sol-cyan border-sol-cyan bg-sol-base02" : "text-sol-base1 border-sol-base01 bg-sol-base02 hover:bg-sol-base01/30"
        }`}
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" />
          <line x1="3" y1="6" x2="3.01" y2="6" /><line x1="3" y1="12" x2="3.01" y2="12" /><line x1="3" y1="18" x2="3.01" y2="18" />
        </svg>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} />
          <nav
            aria-label="On this page"
            className="absolute right-0 top-11 z-30 w-56 max-h-80 overflow-y-auto bg-sol-base03 border border-sol-base01 rounded-lg shadow-xl p-2"
          >
            <div className="text-[11px] uppercase tracking-wider text-sol-base01 px-2 pb-1.5 mb-1 border-b border-sol-base02">
              On this page
            </div>
            {items.map((it) => (
              <a
                key={it.id}
                href={`#${it.id}`}
                onClick={(e) => {
                  e.preventDefault();
                  scrollTo(it.id);
                }}
                className={`block px-2.5 py-1.5 rounded text-[13px] leading-snug truncate border-l-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sol-cyan focus-visible:outline-offset-2 ${
                  it.level === 3 ? "pl-5 text-[12.5px]" : ""
                } ${
                  activeId === it.id
                    ? "text-sol-cyan border-sol-cyan bg-sol-base02"
                    : "text-sol-base1 border-transparent hover:bg-sol-base02 hover:text-sol-cyan"
                }`}
              >
                {it.text}
              </a>
            ))}
          </nav>
        </>
      )}
    </div>
  );
}
