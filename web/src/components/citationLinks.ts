export type NormalizedCitationLink = {
  url: string;
  title?: string;
  snippet?: string;
  last_updated?: string;
};

export function normalizeLink(link: unknown): NormalizedCitationLink | null {
  if (!link) return null;
  if (typeof link === "string") return { url: link };
  if (typeof link === "object" && typeof (link as { url?: unknown }).url === "string") {
    return link as NormalizedCitationLink;
  }
  return null;
}

export function normalizeLinks(links?: unknown[]): NormalizedCitationLink[] {
  return links?.map(normalizeLink).filter((link): link is NormalizedCitationLink => Boolean(link)) ?? [];
}
