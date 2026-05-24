const URL_SCHEME_RE = /^[a-z][a-z0-9+.-]*:/i;
const CONTROL_CHAR_RE = /[\u0000-\u001f\u007f]/;

function decodePath(path: string): string | null {
  try {
    return decodeURI(path);
  } catch {
    return null;
  }
}

function hasFileLikeSegment(path: string): boolean {
  const segments = path.split("/").filter(Boolean);
  const name = segments[segments.length - 1] || "";
  return name.includes(".");
}

export interface LocalFileLinkOptions {
  allowRelative?: boolean;
}

export interface LocalFileReference {
  path: string;
  line?: number;
  column?: number;
}

function splitLineSuffix(path: string): LocalFileReference | null {
  const match = path.match(/^(.*?):(\d+)(?::(\d+))?$/);
  if (!match) return { path };

  const [, strippedPath, lineRaw, columnRaw] = match;
  const line = Number(lineRaw);
  if (!Number.isSafeInteger(line) || line < 1) return null;

  const result: LocalFileReference = { path: strippedPath, line };
  if (columnRaw !== undefined) {
    const column = Number(columnRaw);
    if (!Number.isSafeInteger(column) || column < 1) return null;
    result.column = column;
  }
  return result;
}

export function parseLocalFileReference(href?: string | null, options: LocalFileLinkOptions = {}): LocalFileReference | null {
  if (!href) return null;
  const allowRelative = options.allowRelative ?? true;
  if (CONTROL_CHAR_RE.test(href)) return null;
  if (href.startsWith("#") || URL_SCHEME_RE.test(href) || href.startsWith("//")) return null;

  const pathWithoutFragment = href.split("#", 1)[0];
  const decoded = decodePath(pathWithoutFragment);
  if (!decoded) return null;
  if (decoded.includes("?")) return null;

  const parts = decoded.split("/");
  if (parts.includes("..")) return null;

  const isAbsolutePath = decoded.startsWith("/");
  const isRelativePath = decoded.startsWith("./") || decoded.includes("/");
  if (!isAbsolutePath && (!allowRelative || !isRelativePath)) return null;

  const reference = splitLineSuffix(decoded);
  if (!reference) return null;
  if (!hasFileLikeSegment(reference.path)) return null;

  return reference;
}

export function localFilePathFromMarkdownHref(href?: string | null, options: LocalFileLinkOptions = {}): string | null {
  return parseLocalFileReference(href, options)?.path ?? null;
}
