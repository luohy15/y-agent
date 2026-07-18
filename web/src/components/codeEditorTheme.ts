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

const COLORS = {
  background: "var(--color-sol-base03)",
  surface: "var(--color-sol-base02)",
  border: "var(--color-sol-base01)",
  secondary: "var(--color-sol-base00)",
  text: "var(--color-sol-base0)",
  yellow: "var(--color-sol-yellow)",
  orange: "var(--color-sol-orange)",
  red: "var(--color-sol-red)",
  magenta: "var(--color-sol-magenta)",
  violet: "var(--color-sol-violet)",
  blue: "var(--color-sol-blue)",
  cyan: "var(--color-sol-cyan)",
  green: "var(--color-sol-green)",
} as const;

/** Dark editor behavior for dark + solarized-dark; colors follow active tokens. */
export const solarizedDarkTheme = EditorView.theme(
  {
    "&": {
      backgroundColor: COLORS.background,
      color: COLORS.text,
      fontSize: "13px",
      height: "100%",
    },
    ".cm-content": {
      fontFamily: FONT_MONO,
      caretColor: COLORS.text,
      padding: "12px 0",
    },
    ".cm-cursor, .cm-dropCursor": { borderLeftColor: COLORS.text },
    ".cm-gutters": {
      backgroundColor: COLORS.background,
      color: COLORS.border,
      border: "none",
      borderRight: `1px solid ${COLORS.surface}`,
      fontFamily: FONT_MONO,
    },
    ".cm-lineNumbers .cm-gutterElement": {
      padding: "0 12px 0 8px",
    },
    ".cm-activeLine": { backgroundColor: `color-mix(in srgb, ${COLORS.text} 5%, transparent)` },
    ".cm-activeLineGutter": { backgroundColor: "transparent" },
    ".cm-selectionBackground, ::selection": { backgroundColor: `color-mix(in srgb, ${COLORS.blue} 30%, transparent)` },
    "&.cm-focused .cm-selectionBackground, &.cm-focused ::selection": {
      backgroundColor: `color-mix(in srgb, ${COLORS.blue} 45%, transparent)`,
    },
    ".cm-scroller": { fontFamily: "inherit" },
    ".cm-line": { padding: "0 12px 0 16px" },
    ".cm-panels": { backgroundColor: COLORS.surface, color: COLORS.text },
    ".cm-panels.cm-panels-top": { borderBottom: `1px solid ${COLORS.border}` },
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
      backgroundColor: COLORS.background,
      color: COLORS.text,
      border: `1px solid ${COLORS.border}`,
      borderRadius: "3px",
      padding: "2px 6px",
    },
    ".cm-panel.cm-search button, .cm-button": {
      backgroundColor: COLORS.surface,
      backgroundImage: "none",
      color: COLORS.text,
      border: `1px solid ${COLORS.border}`,
      borderRadius: "3px",
      cursor: "pointer",
    },
    ".cm-panel.cm-search button:hover, .cm-button:hover": { backgroundColor: COLORS.border },
    ".cm-searchMatch": { backgroundColor: `color-mix(in srgb, ${COLORS.yellow} 40%, transparent)` },
    ".cm-searchMatch-selected": { backgroundColor: `color-mix(in srgb, ${COLORS.orange} 60%, transparent)` },
  },
  { dark: true },
);

const solarizedDarkHighlight = HighlightStyle.define([
  { tag: [t.keyword, t.controlKeyword, t.modifier], color: COLORS.green },
  { tag: [t.string, t.character, t.regexp], color: COLORS.cyan },
  { tag: [t.comment, t.lineComment, t.blockComment, t.docComment], color: COLORS.border, fontStyle: "italic" },
  { tag: [t.number, t.bool, t.null, t.atom], color: COLORS.magenta },
  { tag: [t.typeName, t.className, t.namespace, t.definition(t.typeName)], color: COLORS.yellow },
  { tag: [t.function(t.variableName), t.function(t.propertyName), t.definition(t.function(t.variableName))], color: COLORS.blue },
  { tag: [t.variableName, t.propertyName, t.attributeName], color: COLORS.text },
  { tag: [t.heading, t.heading1, t.heading2, t.heading3, t.heading4, t.heading5, t.heading6], color: COLORS.orange, fontWeight: "bold" },
  { tag: [t.link, t.url], color: COLORS.blue, textDecoration: "underline" },
  { tag: t.invalid, color: COLORS.red },
  { tag: [t.meta, t.processingInstruction], color: COLORS.violet },
  { tag: [t.operator, t.punctuation, t.bracket, t.separator], color: COLORS.secondary },
  { tag: [t.tagName], color: COLORS.blue },
  { tag: [t.escape, t.special(t.string)], color: COLORS.orange },
  { tag: [t.emphasis], fontStyle: "italic" },
  { tag: [t.strong], fontWeight: "bold" },
  { tag: [t.strikethrough], textDecoration: "line-through" },
  { tag: [t.quote], color: COLORS.border, fontStyle: "italic" },
]);

export const solarizedDarkSyntaxHighlight: Extension = syntaxHighlighting(solarizedDarkHighlight);

/** Light editor behavior for light + solarized-light; colors follow active tokens. */
export const lightTheme = EditorView.theme(
  {
    "&": {
      backgroundColor: COLORS.background,
      color: COLORS.text,
      fontSize: "13px",
      height: "100%",
    },
    ".cm-content": {
      fontFamily: FONT_MONO,
      caretColor: COLORS.text,
      padding: "12px 0",
    },
    ".cm-cursor, .cm-dropCursor": { borderLeftColor: COLORS.text },
    ".cm-gutters": {
      backgroundColor: COLORS.background,
      color: COLORS.border,
      border: "none",
      borderRight: `1px solid ${COLORS.surface}`,
      fontFamily: FONT_MONO,
    },
    ".cm-lineNumbers .cm-gutterElement": {
      padding: "0 12px 0 8px",
    },
    ".cm-activeLine": { backgroundColor: `color-mix(in srgb, ${COLORS.text} 5%, transparent)` },
    ".cm-activeLineGutter": { backgroundColor: "transparent" },
    ".cm-selectionBackground, ::selection": { backgroundColor: `color-mix(in srgb, ${COLORS.blue} 22%, transparent)` },
    "&.cm-focused .cm-selectionBackground, &.cm-focused ::selection": {
      backgroundColor: `color-mix(in srgb, ${COLORS.blue} 35%, transparent)`,
    },
    ".cm-scroller": { fontFamily: "inherit" },
    ".cm-line": { padding: "0 12px 0 16px" },
    ".cm-panels": { backgroundColor: COLORS.surface, color: COLORS.text },
    ".cm-panels.cm-panels-top": { borderBottom: `1px solid ${COLORS.border}` },
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
      backgroundColor: COLORS.background,
      color: COLORS.text,
      border: `1px solid ${COLORS.border}`,
      borderRadius: "3px",
      padding: "2px 6px",
    },
    ".cm-panel.cm-search button, .cm-button": {
      backgroundColor: COLORS.surface,
      backgroundImage: "none",
      color: COLORS.text,
      border: `1px solid ${COLORS.border}`,
      borderRadius: "3px",
      cursor: "pointer",
    },
    ".cm-panel.cm-search button:hover, .cm-button:hover": { backgroundColor: COLORS.border },
    ".cm-searchMatch": { backgroundColor: `color-mix(in srgb, ${COLORS.yellow} 28%, transparent)` },
    ".cm-searchMatch-selected": { backgroundColor: `color-mix(in srgb, ${COLORS.orange} 45%, transparent)` },
  },
  { dark: false },
);

const lightHighlight = HighlightStyle.define([
  { tag: [t.keyword, t.controlKeyword, t.modifier], color: COLORS.green },
  { tag: [t.string, t.character, t.regexp], color: COLORS.cyan },
  { tag: [t.comment, t.lineComment, t.blockComment, t.docComment], color: COLORS.border, fontStyle: "italic" },
  { tag: [t.number, t.bool, t.null, t.atom], color: COLORS.magenta },
  { tag: [t.typeName, t.className, t.namespace, t.definition(t.typeName)], color: COLORS.yellow },
  { tag: [t.function(t.variableName), t.function(t.propertyName), t.definition(t.function(t.variableName))], color: COLORS.blue },
  { tag: [t.variableName, t.propertyName, t.attributeName], color: COLORS.text },
  { tag: [t.heading, t.heading1, t.heading2, t.heading3, t.heading4, t.heading5, t.heading6], color: COLORS.orange, fontWeight: "bold" },
  { tag: [t.link, t.url], color: COLORS.blue, textDecoration: "underline" },
  { tag: t.invalid, color: COLORS.red },
  { tag: [t.meta, t.processingInstruction], color: COLORS.violet },
  { tag: [t.operator, t.punctuation, t.bracket, t.separator], color: COLORS.secondary },
  { tag: [t.tagName], color: COLORS.blue },
  { tag: [t.escape, t.special(t.string)], color: COLORS.orange },
  { tag: [t.emphasis], fontStyle: "italic" },
  { tag: [t.strong], fontWeight: "bold" },
  { tag: [t.strikethrough], textDecoration: "line-through" },
  { tag: [t.quote], color: COLORS.border, fontStyle: "italic" },
]);

export const lightSyntaxHighlight: Extension = syntaxHighlighting(lightHighlight);

/** Pick CodeMirror chrome + syntax extensions by darkness. */
export function getCodeEditorThemeExtensions(dark: boolean): Extension[] {
  return dark
    ? [solarizedDarkSyntaxHighlight, solarizedDarkTheme]
    : [lightSyntaxHighlight, lightTheme];
}
