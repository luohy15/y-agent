// Shared remark plugin: drop HTML comment nodes so markdown comments like
// `<!-- SCREENSHOT: chat -->` don't leak as visible text. react-markdown (no
// rehype-raw) renders raw `html` mdast node values as escaped text, so a
// standalone or inline comment shows up verbatim in docs / notes / chat. This
// strips them before render. Used by every ReactMarkdown call site (DocsView,
// SharedNote, MessageBubble) to keep the behavior DRY.

interface MdastNode {
  type: string;
  value?: string;
  children?: MdastNode[];
}

const HTML_COMMENT_ONLY = /^\s*<!--[\s\S]*?-->\s*$/;

function stripComments(node: MdastNode): void {
  if (!node.children) return;
  node.children = node.children.filter(
    (child) => !(child.type === "html" && typeof child.value === "string" && HTML_COMMENT_ONLY.test(child.value)),
  );
  for (const child of node.children) stripComments(child);
}

export default function remarkStripComments() {
  return (tree: MdastNode) => {
    stripComments(tree);
  };
}
