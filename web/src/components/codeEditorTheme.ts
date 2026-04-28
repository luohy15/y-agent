import { EditorView } from "@codemirror/view";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { tags as t } from "@lezer/highlight";
import type { Extension } from "@codemirror/state";

const FONT_MONO =
  'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace';

export const solarizedDarkTheme = EditorView.theme(
  {
    "&": {
      backgroundColor: "#002b36",
      color: "#839496",
      fontSize: "13px",
      height: "100%",
    },
    ".cm-content": {
      fontFamily: FONT_MONO,
      caretColor: "#839496",
      padding: "12px 0",
    },
    ".cm-cursor, .cm-dropCursor": { borderLeftColor: "#839496" },
    ".cm-gutters": {
      backgroundColor: "#002b36",
      color: "#586e75",
      border: "none",
      borderRight: "1px solid #073642",
      fontFamily: FONT_MONO,
    },
    ".cm-lineNumbers .cm-gutterElement": {
      padding: "0 12px 0 8px",
    },
    ".cm-activeLine": { backgroundColor: "rgba(255,255,255,0.04)" },
    ".cm-activeLineGutter": { backgroundColor: "transparent" },
    ".cm-selectionBackground, ::selection": { backgroundColor: "rgba(38,139,210,0.30)" },
    "&.cm-focused .cm-selectionBackground, &.cm-focused ::selection": {
      backgroundColor: "rgba(38,139,210,0.45)",
    },
    ".cm-scroller": { fontFamily: "inherit" },
    ".cm-line": { padding: "0 12px 0 16px" },
  },
  { dark: true },
);

const solarizedDarkHighlight = HighlightStyle.define([
  { tag: [t.keyword, t.controlKeyword, t.modifier], color: "#859900" },
  { tag: [t.string, t.character, t.regexp], color: "#2aa198" },
  { tag: [t.comment, t.lineComment, t.blockComment, t.docComment], color: "#586e75", fontStyle: "italic" },
  { tag: [t.number, t.bool, t.null, t.atom], color: "#d33682" },
  { tag: [t.typeName, t.className, t.namespace, t.definition(t.typeName)], color: "#b58900" },
  { tag: [t.function(t.variableName), t.function(t.propertyName), t.definition(t.function(t.variableName))], color: "#268bd2" },
  { tag: [t.variableName, t.propertyName, t.attributeName], color: "#839496" },
  { tag: [t.heading, t.heading1, t.heading2, t.heading3, t.heading4, t.heading5, t.heading6], color: "#cb4b16", fontWeight: "bold" },
  { tag: [t.link, t.url], color: "#268bd2", textDecoration: "underline" },
  { tag: t.invalid, color: "#dc322f" },
  { tag: [t.meta, t.processingInstruction], color: "#6c71c4" },
  { tag: [t.operator, t.punctuation, t.bracket, t.separator], color: "#93a1a1" },
  { tag: [t.tagName], color: "#268bd2" },
  { tag: [t.escape, t.special(t.string)], color: "#cb4b16" },
  { tag: [t.emphasis], fontStyle: "italic" },
  { tag: [t.strong], fontWeight: "bold" },
  { tag: [t.strikethrough], textDecoration: "line-through" },
  { tag: [t.quote], color: "#586e75", fontStyle: "italic" },
]);

export const solarizedDarkSyntaxHighlight: Extension = syntaxHighlighting(solarizedDarkHighlight);
