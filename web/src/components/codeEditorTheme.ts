import { EditorView } from "@codemirror/view";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { tags as t } from "@lezer/highlight";
import type { Extension } from "@codemirror/state";

const FONT_MONO =
  'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace';

/** Dark themes: dark + solarized-dark. ST2 owns utils/theme.ts; keep local until merged. */
const DARK_THEMES = new Set(["dark", "solarized-dark"]);

export function isDark(theme?: string | null): boolean {
  const t =
    theme ??
    (typeof document !== "undefined" ? document.documentElement.dataset.theme : undefined) ??
    "light";
  return DARK_THEMES.has(t);
}

/** Solarized-dark editor chrome (also used for the neutral Dark theme). */
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
    ".cm-panels": { backgroundColor: "#073642", color: "#839496" },
    ".cm-panels.cm-panels-top": { borderBottom: "1px solid #586e75" },
    ".cm-panel.cm-search": {
      display: "flex",
      alignItems: "center",
      gap: "4px",
      padding: "4px 8px",
      fontFamily: FONT_MONO,
      fontSize: "12px",
    },
    ".cm-panel.cm-search label": { display: "flex", alignItems: "center", gap: "2px" },
    ".cm-panel.cm-search input, .cm-textfield": {
      backgroundColor: "#002b36",
      color: "#839496",
      border: "1px solid #586e75",
      borderRadius: "3px",
      padding: "2px 6px",
    },
    ".cm-panel.cm-search button, .cm-button": {
      backgroundColor: "#073642",
      backgroundImage: "none",
      color: "#839496",
      border: "1px solid #586e75",
      borderRadius: "3px",
      cursor: "pointer",
    },
    ".cm-panel.cm-search button:hover, .cm-button:hover": { backgroundColor: "#586e75" },
    ".cm-searchMatch": { backgroundColor: "rgba(181,137,0,0.4)" },
    ".cm-searchMatch-selected": { backgroundColor: "rgba(203,75,22,0.6)" },
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

/** Light editor chrome (covers light + solarized-light). Uses Light palette tokens. */
export const lightTheme = EditorView.theme(
  {
    "&": {
      backgroundColor: "#ffffff",
      color: "#24292f",
      fontSize: "13px",
      height: "100%",
    },
    ".cm-content": {
      fontFamily: FONT_MONO,
      caretColor: "#24292f",
      padding: "12px 0",
    },
    ".cm-cursor, .cm-dropCursor": { borderLeftColor: "#24292f" },
    ".cm-gutters": {
      backgroundColor: "#ffffff",
      color: "#6b7280",
      border: "none",
      borderRight: "1px solid #f3f4f6",
      fontFamily: FONT_MONO,
    },
    ".cm-lineNumbers .cm-gutterElement": {
      padding: "0 12px 0 8px",
    },
    ".cm-activeLine": { backgroundColor: "rgba(0,0,0,0.04)" },
    ".cm-activeLineGutter": { backgroundColor: "transparent" },
    ".cm-selectionBackground, ::selection": { backgroundColor: "rgba(9,105,218,0.22)" },
    "&.cm-focused .cm-selectionBackground, &.cm-focused ::selection": {
      backgroundColor: "rgba(9,105,218,0.35)",
    },
    ".cm-scroller": { fontFamily: "inherit" },
    ".cm-line": { padding: "0 12px 0 16px" },
    ".cm-panels": { backgroundColor: "#f3f4f6", color: "#24292f" },
    ".cm-panels.cm-panels-top": { borderBottom: "1px solid #6b7280" },
    ".cm-panel.cm-search": {
      display: "flex",
      alignItems: "center",
      gap: "4px",
      padding: "4px 8px",
      fontFamily: FONT_MONO,
      fontSize: "12px",
    },
    ".cm-panel.cm-search label": { display: "flex", alignItems: "center", gap: "2px" },
    ".cm-panel.cm-search input, .cm-textfield": {
      backgroundColor: "#ffffff",
      color: "#24292f",
      border: "1px solid #6b7280",
      borderRadius: "3px",
      padding: "2px 6px",
    },
    ".cm-panel.cm-search button, .cm-button": {
      backgroundColor: "#f3f4f6",
      backgroundImage: "none",
      color: "#24292f",
      border: "1px solid #6b7280",
      borderRadius: "3px",
      cursor: "pointer",
    },
    ".cm-panel.cm-search button:hover, .cm-button:hover": { backgroundColor: "#e5e7eb" },
    ".cm-searchMatch": { backgroundColor: "rgba(154,103,0,0.28)" },
    ".cm-searchMatch-selected": { backgroundColor: "rgba(188,76,0,0.45)" },
  },
  { dark: false },
);

const lightHighlight = HighlightStyle.define([
  { tag: [t.keyword, t.controlKeyword, t.modifier], color: "#1a7f37" },
  { tag: [t.string, t.character, t.regexp], color: "#1b7c83" },
  { tag: [t.comment, t.lineComment, t.blockComment, t.docComment], color: "#6b7280", fontStyle: "italic" },
  { tag: [t.number, t.bool, t.null, t.atom], color: "#bf3989" },
  { tag: [t.typeName, t.className, t.namespace, t.definition(t.typeName)], color: "#9a6700" },
  { tag: [t.function(t.variableName), t.function(t.propertyName), t.definition(t.function(t.variableName))], color: "#0969da" },
  { tag: [t.variableName, t.propertyName, t.attributeName], color: "#24292f" },
  { tag: [t.heading, t.heading1, t.heading2, t.heading3, t.heading4, t.heading5, t.heading6], color: "#bc4c00", fontWeight: "bold" },
  { tag: [t.link, t.url], color: "#0969da", textDecoration: "underline" },
  { tag: t.invalid, color: "#cf222e" },
  { tag: [t.meta, t.processingInstruction], color: "#8250df" },
  { tag: [t.operator, t.punctuation, t.bracket, t.separator], color: "#57606a" },
  { tag: [t.tagName], color: "#0969da" },
  { tag: [t.escape, t.special(t.string)], color: "#bc4c00" },
  { tag: [t.emphasis], fontStyle: "italic" },
  { tag: [t.strong], fontWeight: "bold" },
  { tag: [t.strikethrough], textDecoration: "line-through" },
  { tag: [t.quote], color: "#6b7280", fontStyle: "italic" },
]);

export const lightSyntaxHighlight: Extension = syntaxHighlighting(lightHighlight);

/** Pick CodeMirror chrome + syntax extensions by darkness. */
export function getCodeEditorThemeExtensions(dark: boolean): Extension[] {
  return dark
    ? [solarizedDarkSyntaxHighlight, solarizedDarkTheme]
    : [lightSyntaxHighlight, lightTheme];
}
