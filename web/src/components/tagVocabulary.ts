export function tagVocabularyKey(api: string, editable: boolean): string | null {
  return editable ? `${api}/api/module/tag/list` : null;
}

export function toTagSuggestions(data: unknown): string[] | undefined {
  if (!Array.isArray(data) || !data.every((entry) => entry && typeof (entry as { tag?: unknown }).tag === "string")) {
    return undefined;
  }
  return data.map((entry: { tag: string }) => entry.tag);
}
