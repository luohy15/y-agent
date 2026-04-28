import { useEffect, useMemo, useRef, useState } from "react";
import CodeMirror from "@uiw/react-codemirror";
import type { Extension } from "@codemirror/state";
import { EditorState } from "@codemirror/state";
import { EditorView, lineNumbers, highlightActiveLine, highlightActiveLineGutter, keymap } from "@codemirror/view";
import { history, defaultKeymap, historyKeymap } from "@codemirror/commands";
import { solarizedDarkTheme, solarizedDarkSyntaxHighlight } from "./codeEditorTheme";
import { loadLanguage, getCachedLanguage, resolveLangKey } from "./codeEditorLangs";

interface CodeEditorProps {
  value: string;
  onChange: (value: string) => void;
  filePath: string;
  onSave?: (filePath: string) => void;
  readOnly?: boolean;
  className?: string;
}

export default function CodeEditor({
  value,
  onChange,
  filePath,
  onSave,
  readOnly = false,
  className,
}: CodeEditorProps) {
  const langKey = useMemo(() => resolveLangKey(filePath), [filePath]);
  const [langExtension, setLangExtension] = useState<Extension | null>(
    () => getCachedLanguage(langKey) ?? null,
  );

  const onSaveRef = useRef(onSave);
  useEffect(() => {
    onSaveRef.current = onSave;
  }, [onSave]);

  useEffect(() => {
    let cancelled = false;
    const cached = getCachedLanguage(langKey);
    if (cached) {
      setLangExtension(cached);
      return;
    }
    setLangExtension(null);
    loadLanguage(langKey)
      .then((ext) => {
        if (!cancelled) setLangExtension(ext);
      })
      .catch(() => {
        if (!cancelled) setLangExtension(null);
      });
    return () => {
      cancelled = true;
    };
  }, [langKey]);

  const extensions = useMemo<Extension[]>(() => {
    const exts: Extension[] = [
      lineNumbers(),
      highlightActiveLine(),
      highlightActiveLineGutter(),
      history(),
      EditorView.lineWrapping,
      keymap.of([
        {
          key: "Mod-s",
          preventDefault: true,
          run: () => {
            onSaveRef.current?.(filePath);
            return true;
          },
        },
        ...defaultKeymap,
        ...historyKeymap,
      ]),
      EditorState.readOnly.of(readOnly),
      solarizedDarkSyntaxHighlight,
      solarizedDarkTheme,
    ];
    if (langExtension) exts.push(langExtension);
    return exts;
  }, [filePath, readOnly, langExtension]);

  return (
    <CodeMirror
      value={value}
      onChange={onChange}
      extensions={extensions}
      basicSetup={false}
      theme="none"
      className={className}
      height="100%"
      style={{ height: "100%", overflow: "hidden" }}
      indentWithTab={false}
    />
  );
}
