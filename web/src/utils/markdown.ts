function parseFrontMatterScalar(raw: string): string {
  let value = raw.trim();
  if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
    value = value.slice(1, -1);
  }
  return value;
}

export function parseFrontMatter(content: string): { data: Record<string, unknown>; body: string } {
  const match = content.match(/^---\r?\n([\s\S]*?)\r?\n---(\r?\n|$)/);
  if (!match) return { data: {}, body: content };
  const yaml = match[1];
  const body = content.slice(match[0].length);
  const data: Record<string, unknown> = {};
  const lines = yaml.split(/\r?\n/);
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (line.trim() === "") { index++; continue; }
    const keyValue = line.match(/^([A-Za-z_][\w.-]*)\s*:\s*(.*)$/);
    if (!keyValue) { index++; continue; }
    const key = keyValue[1];
    const rest = keyValue[2];
    if (rest.trim() === "") {
      const items: string[] = [];
      let itemIndex = index + 1;
      while (itemIndex < lines.length) {
        const item = lines[itemIndex].match(/^\s+-\s+(.*)$/);
        if (!item) break;
        items.push(parseFrontMatterScalar(item[1]));
        itemIndex++;
      }
      data[key] = items.length > 0 ? items : "";
      index = items.length > 0 ? itemIndex : index + 1;
      continue;
    }
    const value = rest.trim();
    if (value.startsWith("[") && value.endsWith("]")) {
      const inner = value.slice(1, -1).trim();
      data[key] = inner === "" ? [] : inner.split(",").map((item) => parseFrontMatterScalar(item));
    } else {
      data[key] = parseFrontMatterScalar(value);
    }
    index++;
  }
  return { data, body };
}
