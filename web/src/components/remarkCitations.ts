type Node = {
  type?: string;
  value?: string;
  url?: string;
  children?: Node[];
  [key: string]: unknown;
};

const CITATION_RUN_RE = /\[\d+\](?:\[\d+\])*/g;
const CITATION_INDEX_RE = /\[(\d+)\]/g;

function splitCitationText(node: Node): Node[] | null {
  if (node.type !== "text" || typeof node.value !== "string") return null;

  const value = node.value;
  const nodes: Node[] = [];
  let lastIndex = 0;

  for (const match of value.matchAll(CITATION_RUN_RE)) {
    const matchText = match[0];
    const index = match.index ?? 0;
    if (index > lastIndex) {
      nodes.push({ type: "text", value: value.slice(lastIndex, index) });
    }

    const indices = Array.from(matchText.matchAll(CITATION_INDEX_RE), (m) => m[1]);
    nodes.push({
      type: "link",
      url: `cite://${indices.join(",")}`,
      children: [{ type: "text", value: matchText }],
    });
    lastIndex = index + matchText.length;
  }

  if (nodes.length === 0) return null;
  if (lastIndex < value.length) {
    nodes.push({ type: "text", value: value.slice(lastIndex) });
  }
  return nodes;
}

function visit(node: Node): void {
  if (!node.children) return;

  for (let i = 0; i < node.children.length; i++) {
    const child = node.children[i];
    const replacement = splitCitationText(child);
    if (replacement) {
      node.children.splice(i, 1, ...replacement);
      i += replacement.length - 1;
    } else {
      visit(child);
    }
  }
}

export default function remarkCitations() {
  return (tree: Node) => visit(tree);
}
