import { type ReactNode, useRef, useCallback, useEffect, useImperativeHandle, forwardRef, useState } from "react";

interface ChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onClear?: () => void;
  autoApprove: boolean;
  onToggleAutoApprove: () => void;
  sending?: boolean;
  autoFocus?: boolean;
  extraButtons?: ReactNode;
}

export interface ChatInputHandle {
  focus: () => void;
}

const ChatInput = forwardRef<ChatInputHandle, ChatInputProps>(
  ({ value, onChange, onSubmit, onClear, autoApprove, onToggleAutoApprove, sending, autoFocus, extraButtons }, ref) => {
    const inputRef = useRef<HTMLTextAreaElement | null>(null);
    const [cursorPos, setCursorPos] = useState<number>(0);

    const updateCursor = useCallback(() => {
      const el = inputRef.current;
      if (el) setCursorPos(el.selectionStart ?? el.value.length);
    }, []);

    useImperativeHandle(ref, () => ({ focus: () => inputRef.current?.focus() }));

    const handleSubmit = useCallback(() => {
      const trimmed = value.trim();
      if (onClear && (trimmed === "/cl" || trimmed === "/clear")) {
        onChange("");
        onClear();
        return;
      }
      onSubmit();
    }, [value, onChange, onClear, onSubmit]);

    // Capture keyboard events globally and redirect to textarea
    useEffect(() => {
      const handler = (e: KeyboardEvent) => {
        const el = document.activeElement;
        // Skip if already in an editable element
        if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement || (el as HTMLElement)?.isContentEditable) return;
        const textarea = inputRef.current;
        if (!textarea) return;
        // Redirect printable keys, Enter, Backspace, and ctrl shortcuts
        if (e.key === "Enter" && !e.shiftKey && !(e as KeyboardEvent).isComposing) {
          e.preventDefault();
          handleSubmit();
          return;
        }
        if (e.key === "Tab" && e.shiftKey) {
          e.preventDefault();
          onToggleAutoApprove();
          return;
        }
        if (e.key.length === 1 || e.key === "Backspace" || e.key === "Delete") {
          textarea.focus();
          // The native event will replay in the now-focused textarea
        }
      };
      document.addEventListener("keydown", handler);
      return () => document.removeEventListener("keydown", handler);
    }, [handleSubmit, onToggleAutoApprove]);

    // Auto-resize textarea on mobile
    const autoResize = useCallback(() => {
      const textarea = inputRef.current;
      if (!textarea) return;
      textarea.style.height = "auto";
      textarea.style.height = textarea.scrollHeight + "px";
    }, []);

    useEffect(() => {
      autoResize();
    }, [value, autoResize]);

    const handleBashKeys = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (!e.ctrlKey) return;
      const input = e.currentTarget;
      const pos = input.selectionStart ?? 0;
      const val = input.value;
      const setValue = (v: string, newPos: number) => {
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
        nativeInputValueSetter.call(input, v);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        requestAnimationFrame(() => input.setSelectionRange(newPos, newPos));
      };
      switch (e.key) {
        case "u": {
          e.preventDefault();
          const lineStart = val.lastIndexOf("\n", pos - 1) + 1;
          setValue(val.slice(0, lineStart) + val.slice(pos), lineStart);
        }
          break;
        case "w": {
          e.preventDefault();
          let start = pos;
          while (start > 0 && /\s/.test(val[start - 1])) start--;
          while (start > 0 && !/\s/.test(val[start - 1])) start--;
          setValue(val.slice(0, start) + val.slice(pos), start);
        }
          break;
      }
    }, []);

    return (
      <div className="mx-4 border-t border-sol-base02 shrink-0">
        <div className="flex items-start px-2 py-1.5 border-b border-sol-base02" onClick={() => inputRef.current?.focus()}>
          <span className="text-sm sm:text-[0.775rem] text-sol-base01 font-mono mr-2 select-none leading-[1.4]">&gt;</span>
          <div className="flex-1 min-w-0 relative">
            {/* Mobile: plain visible textarea so long-press paste works */}
            <textarea
              ref={inputRef}
              value={value}
              onChange={(e) => { onChange(e.target.value); updateCursor(); }}
              onKeyDown={(e) => {
                if (e.key === "Tab" && e.shiftKey) { e.preventDefault(); onToggleAutoApprove(); }
                else if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); handleSubmit(); }
                else handleBashKeys(e);
                requestAnimationFrame(updateCursor);
              }}
              onKeyUp={updateCursor}
              onClick={updateCursor}
              onSelect={updateCursor}
              autoFocus={autoFocus}
              rows={1}
              className="sm:absolute sm:inset-0 sm:w-full sm:h-full sm:opacity-0 w-full resize-none bg-transparent text-sm sm:text-[0.775rem] font-mono text-sol-base0 leading-[1.4] min-h-[1.4em] outline-none caret-sol-base1 overflow-hidden sm:overflow-auto"
            />
            {/* Desktop: custom cursor display */}
            <div className="hidden sm:block text-[0.775rem] font-mono text-sol-base0 whitespace-pre-wrap break-words leading-[1.4] min-h-[1.4em]">
              {value.slice(0, cursorPos)}
              <span className="bg-sol-base0 text-sol-base03">{value[cursorPos] ?? " "}</span>
              {value.slice(cursorPos + 1)}
            </div>
          </div>
        </div>
        <div className="px-2 pt-1 pb-1 text-sm sm:text-xs select-none flex items-center gap-2">
          <button onClick={onToggleAutoApprove} className={`sm:hidden font-mono cursor-pointer px-3 py-1 sm:px-2 sm:py-0.5 rounded text-sm sm:text-xs font-semibold ${autoApprove ? "bg-sol-violet text-sol-base3" : "bg-sol-base02 text-sol-base01"}`}>{autoApprove ? "auto approve on" : "auto approve off"}</button><span className="hidden sm:inline"><span className="font-mono">&gt;&gt;</span> <span className={autoApprove ? "text-sol-violet" : "text-sol-base01"}>{autoApprove ? "auto approve on" : "auto approve off"}</span> <span className="text-sol-base01">(shift+tab to cycle)</span></span>{sending && " · sending..."}
          {extraButtons}
        </div>
      </div>
    );
  }
);

export default ChatInput;
