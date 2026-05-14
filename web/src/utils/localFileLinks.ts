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

interface LocalFileLinkOptions {
  allowRelative?: boolean;
}

export function localFilePathFromMarkdownHref(href?: string | null, options: LocalFileLinkOptions = {}): string | null {
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
  if (!hasFileLikeSegment(decoded)) return null;

  return decoded;
}
