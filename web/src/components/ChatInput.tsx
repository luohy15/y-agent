import { useState, useRef, useCallback, useImperativeHandle, forwardRef } from "react";

interface ChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  autoApprove: boolean;
  onToggleAutoApprove: () => void;
  sending?: boolean;
  autoFocus?: boolean;
}

export interface ChatInputHandle {
  focus: () => void;
}

const ChatInput = forwardRef<ChatInputHandle, ChatInputProps>(
  ({ value, onChange, onSubmit, autoApprove, onToggleAutoApprove, sending, autoFocus }, ref) => {
    const inputRef = useRef<HTMLTextAreaElement | null>(null);
    const [inputFocused, setInputFocused] = useState(false);

    useImperativeHandle(ref, () => ({ focus: () => inputRef.current?.focus() }));

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
          <span className="text-[0.775rem] text-sol-base01 font-mono mr-2 select-none leading-[1.4]">&gt;</span>
          <div className="flex-1 min-w-0 relative">
            <textarea
              ref={inputRef}
              value={value}
              onChange={(e) => onChange(e.target.value)}
              onFocus={() => setInputFocused(true)}
              onBlur={() => setInputFocused(false)}
              onKeyDown={(e) => {
                if (e.key === "Tab" && e.shiftKey) { e.preventDefault(); onToggleAutoApprove(); }
                else if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSubmit(); }
                else handleBashKeys(e);
              }}
              autoFocus={autoFocus}
              rows={1}
              className="absolute inset-0 w-full h-full opacity-0 resize-none"
            />
            <div className="text-[0.775rem] font-mono text-sol-base0 whitespace-pre-wrap break-words leading-[1.4] min-h-[1.4em]">
              {value}
              {inputFocused && <span className="inline-block w-[0.6em] h-[1em] bg-sol-base1 align-text-bottom" />}
            </div>
          </div>
        </div>
        <div className="px-2 pt-1 pb-1 text-xs select-none">
          <span className="font-mono">&gt;&gt;</span> <span className={autoApprove ? "text-sol-violet" : "text-sol-base01"}>{autoApprove ? "auto approve on" : "auto approve off"}</span> <span className="text-sol-base01">(shift+tab to cycle)</span>{sending && " · sending..."}
        </div>
      </div>
    );
  }
);

export default ChatInput;
