import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSlug from "rehype-slug";
import { parseLocalFileReference } from "../../utils/localFileLinks";
import { parseFrontMatter } from "../../utils/markdown";
import { extractMarkdownHeadings } from "../../utils/markdownExport";
import { FrontMatterCard, MARKDOWN_ARTICLE_TABLE_CLASSES } from "./FrontMatterCard";
import MarkdownBodyPreview from "./MarkdownBodyPreview";

function resolveRelativePath(currentFilePath: string, href: string): string {
  const dir = currentFilePath.includes("/") ? currentFilePath.substring(0, currentFilePath.lastIndexOf("/") + 1) : "";
  const parts = (dir + href).split("/");
  const resolved: string[] = [];
  for (const part of parts) {
    if (part === "..") resolved.pop();
    else if (part !== ".") resolved.push(part);
  }
  return resolved.join("/");
}

function isRelativeLink(href: string): boolean {
  return !/^(https?:\/\/|mailto:|#|\/)/.test(href);
}

function isAbsoluteHttpLink(href: string): boolean {
  return /^https?:\/\//i.test(href);
}

export interface MarkdownPreviewProps {
  content: string;
  currentFilePath?: string;
  onOpenFile?: (path: string, line?: number) => void;
  onExternalLinkClick?: (url: string) => void;
}

/**
 * Shared markdown renderer used by FileViewer (auth + public).
 */
export default function MarkdownPreview({ content, currentFilePath, onOpenFile, onExternalLinkClick }: MarkdownPreviewProps) {
  const { data: frontMatter, body } = useMemo(() => parseFrontMatter(content ?? ""), [content]);
  const articleRef = useRef<HTMLDivElement | null>(null);
  const [headings, setHeadings] = useState<{ text: string; id: string; level: number }[]>([]);

  useEffect(() => {
    const article = articleRef.current;
    if (!article) {
      setHeadings([]);
      return;
    }
    const raf = window.requestAnimationFrame(() => {
      setHeadings(extractMarkdownHeadings(article));
    });
    return () => window.cancelAnimationFrame(raf);
  }, [body]);

  return (
    <MarkdownBodyPreview
      headings={headings}
      articleRef={articleRef}
      articleClassName={`flex-1 min-w-0 overflow-auto p-4 prose prose-invert prose-sm max-w-none text-sol-base0 break-words [&_pre]:overflow-x-auto ${MARKDOWN_ARTICLE_TABLE_CLASSES} [&_img]:max-w-full relative`}
      metadata={<FrontMatterCard data={frontMatter} />}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSlug]}
        components={{
          a: ({ href, children, ...props }) => {
            const fileRef = parseLocalFileReference(href, { allowRelative: false });
            if (fileRef && onOpenFile) {
              return (
                <a href={href} onClick={(e) => { e.preventDefault(); onOpenFile(fileRef.path, fileRef.line); }} {...props}>{children}</a>
              );
            }
            if (href && currentFilePath && onOpenFile && isRelativeLink(href)) {
              return (
                <a href={href} onClick={(e) => { e.preventDefault(); onOpenFile(resolveRelativePath(currentFilePath, href)); }} {...props}>{children}</a>
              );
            }
            if (href && onExternalLinkClick && isAbsoluteHttpLink(href)) {
              return (
                <a href={href} onClick={(e) => { e.preventDefault(); onExternalLinkClick(href); }} {...props}>{children}</a>
              );
            }
            return <a href={href} {...props}>{children}</a>;
          },
        }}
      >
        {body}
      </ReactMarkdown>
    </MarkdownBodyPreview>
  );
}
