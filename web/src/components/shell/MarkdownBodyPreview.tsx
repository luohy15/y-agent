import { useRef, useState, type ReactNode, type RefObject } from "react";

export interface MarkdownBodyHeading {
  text: string;
  id: string;
  level: number;
}

export interface MarkdownBodyPreviewProps {
  children?: ReactNode;
  metadata?: ReactNode;
  headings: MarkdownBodyHeading[];
  articleClassName: string;
  rootClassName?: string;
  articleRef?: RefObject<HTMLDivElement | null>;
  tocItemClassName?: (level: number) => string;
}

function defaultTocItemClassName(level: number): string {
  return level === 3 ? "pl-3" : "";
}

function MarkdownToc({
  headings,
  articleRef,
  itemClassName,
  onSelect,
}: {
  headings: MarkdownBodyHeading[];
  articleRef: RefObject<HTMLDivElement | null>;
  itemClassName: (level: number) => string;
  onSelect?: () => void;
}) {
  return (
    <ul className="space-y-1">
      {headings.map((heading) => (
        <li key={heading.id} className={itemClassName(heading.level)}>
          <a
            href={`#${heading.id}`}
            onClick={(event) => {
              event.preventDefault();
              const root = articleRef.current ?? document;
              const target = typeof CSS !== "undefined" && typeof CSS.escape === "function"
                ? root.querySelector(`#${CSS.escape(heading.id)}`)
                : Array.from(root.querySelectorAll("[id]")).find((node) => node.id === heading.id) ?? null;
              target?.scrollIntoView({ block: "start" });
              onSelect?.();
            }}
            className="text-xs text-sol-base0 hover:text-sol-blue no-underline block truncate cursor-pointer"
          >
            {heading.text}
          </a>
        </li>
      ))}
    </ul>
  );
}

const TOC_ICON = (
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" />
    <line x1="3" y1="6" x2="3.01" y2="6" /><line x1="3" y1="12" x2="3.01" y2="12" /><line x1="3" y1="18" x2="3.01" y2="18" />
  </svg>
);

export default function MarkdownBodyPreview({
  children,
  metadata,
  headings,
  articleClassName,
  rootClassName = "flex h-full",
  articleRef: articleRefProp,
  tocItemClassName = defaultTocItemClassName,
}: MarkdownBodyPreviewProps) {
  const internalRef = useRef<HTMLDivElement | null>(null);
  const articleRef = articleRefProp ?? internalRef;
  const [tocOpen, setTocOpen] = useState(false);
  const [tocCollapsed, setTocCollapsed] = useState(() => localStorage.getItem("markdownTocCollapsed") === "true");
  return (
    <div className={rootClassName}>
      <div
        ref={(node) => { articleRef.current = node; }}
        className={articleClassName}
      >
        {metadata}
        {children}
      </div>
      {headings.length > 0 && (
        <nav className={`hidden lg:flex flex-col shrink-0 border-l border-sol-base02 transition-all duration-200 ${tocCollapsed ? "w-8" : "w-48"}`} data-testid="toc-desktop">
          <button
            type="button"
            onClick={() => setTocCollapsed((value) => {
              const next = !value;
              localStorage.setItem("markdownTocCollapsed", String(next));
              return next;
            })}
            className="p-2 text-sol-base01 hover:text-sol-base0 cursor-pointer text-xs shrink-0"
            title={tocCollapsed ? "Expand TOC" : "Collapse TOC"}
          >
            {tocCollapsed ? "◀" : "▶"}
          </button>
          {!tocCollapsed && (
            <div className="overflow-y-auto px-3 pb-3">
              <div className="text-xs text-sol-base01 mb-2">Contents</div>
              <MarkdownToc headings={headings} articleRef={articleRef} itemClassName={tocItemClassName} />
            </div>
          )}
        </nav>
      )}
      {headings.length > 0 && (
        <div className="hidden md:block lg:hidden absolute top-2 right-2 z-10" data-testid="toc-tablet">
          <button type="button" onClick={() => setTocOpen((value) => !value)} className="w-8 h-8 rounded bg-sol-base02 border border-sol-base01 text-sol-base1 flex items-center justify-center cursor-pointer hover:bg-sol-base01/30" title="Table of contents">{TOC_ICON}</button>
          {tocOpen && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setTocOpen(false)} />
              <nav className="absolute right-0 top-10 z-50 w-56 max-h-64 overflow-y-auto bg-sol-base03 border border-sol-base01 rounded shadow-float p-3">
                <div className="text-xs text-sol-base01 mb-2">Contents</div>
                <MarkdownToc headings={headings} articleRef={articleRef} itemClassName={tocItemClassName} onSelect={() => setTocOpen(false)} />
              </nav>
            </>
          )}
        </div>
      )}
      {headings.length > 0 && (
        <div className="md:hidden" data-testid="toc-mobile">
          <button type="button" onClick={() => setTocOpen((value) => !value)} className="fixed right-4 bottom-14 z-40 w-10 h-10 rounded-full bg-sol-base02 border border-sol-base01 text-sol-base1 flex items-center justify-center shadow-float cursor-pointer" title="Table of contents">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" />
              <line x1="3" y1="6" x2="3.01" y2="6" /><line x1="3" y1="12" x2="3.01" y2="12" /><line x1="3" y1="18" x2="3.01" y2="18" />
            </svg>
          </button>
          {tocOpen && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setTocOpen(false)} />
              <nav className="fixed right-4 bottom-26 z-50 w-56 max-h-64 overflow-y-auto bg-sol-base03 border border-sol-base01 rounded shadow-float p-3">
                <div className="text-xs text-sol-base01 mb-2">Contents</div>
                <MarkdownToc headings={headings} articleRef={articleRef} itemClassName={tocItemClassName} onSelect={() => setTocOpen(false)} />
              </nav>
            </>
          )}
        </div>
      )}
    </div>
  );
}
