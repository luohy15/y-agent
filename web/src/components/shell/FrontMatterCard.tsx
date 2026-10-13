import { Fragment, type ReactNode } from "react";

export const MARKDOWN_ARTICLE_TABLE_CLASSES = "[&_table]:block [&_table]:max-w-full [&_table]:overflow-x-auto";

export interface FrontMatterCardProps {
  data: Record<string, unknown>;
  tags?: ReactNode;
  forceTagsBlock?: boolean;
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (Array.isArray(v)) return v.map(String).join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export function FrontMatterCard({ data, tags, forceTagsBlock }: FrontMatterCardProps) {
  const entries = Object.entries(data);
  if (entries.length === 0 && !forceTagsBlock) return null;
  const title = typeof data.title === "string" ? data.title : undefined;
  const tagsRaw = data.tags ?? data.tag;
  const tagList: string[] = Array.isArray(tagsRaw)
    ? tagsRaw.map(String).filter((s) => s.length > 0)
    : typeof tagsRaw === "string" && tagsRaw.trim() !== ""
    ? tagsRaw.split(",").map((s) => s.trim()).filter(Boolean)
    : [];
  const rest = entries.filter(([k, v]) => {
    if (k === "title" || k === "tags" || k === "tag") return false;
    if (v === "" || v === null || v === undefined) return false;
    if (Array.isArray(v) && v.length === 0) return false;
    return true;
  });
  const showTags = tags !== undefined || tagList.length > 0 || forceTagsBlock;
  if (!title && !showTags && rest.length === 0) return null;

  return (
    <div className="not-prose mb-4 rounded border border-sol-base02 bg-sol-base02/30 px-4 py-3">
      {title && (
        <div className="text-sol-base1 font-semibold text-base break-words mb-2">{title}</div>
      )}
      {showTags && (
        tags !== undefined ? (
          <div className="mb-2">{tags}</div>
        ) : (
          <div className="flex flex-wrap gap-1 mb-2">
            {tagList.map((t) => (
              <span
                key={t}
                className="inline-flex items-center px-1.5 py-0.5 rounded text-[0.65rem] font-mono bg-sol-base02 text-sol-base01"
              >
                {t}
              </span>
            ))}
          </div>
        )
      )}
      {rest.length > 0 && (
        <div className="grid grid-cols-[fit-content(40%)_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-xs">
          {rest.map(([k, v]) => (
            <Fragment key={k}>
              <div className="text-sol-base01 [overflow-wrap:anywhere]">{k}</div>
              <div className="text-sol-base0 [overflow-wrap:anywhere]">{formatValue(v)}</div>
            </Fragment>
          ))}
        </div>
      )}
    </div>
  );
}
