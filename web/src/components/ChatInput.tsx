import { type ReactNode, useRef, useCallback, useEffect, useImperativeHandle, forwardRef, useState } from "react";

export interface ImageUploadPayload {
  filename: string;
  content_base64: string;
}

interface ChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (imageUploads?: ImageUploadPayload[]) => void | Promise<void>;
  onClear?: () => void;
  sending?: boolean;
  autoFocus?: boolean;
  extraButtons?: ReactNode;
  placeholder?: string;
}

export interface ChatInputHandle {
  focus: () => void;
}

interface AttachedImage {
  id: string;
  file: File;
  previewUrl: string;
}

function fileToImageUpload(file: File): Promise<ImageUploadPayload> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || "");
      const commaIndex = result.indexOf(",");
      resolve({ filename: file.name || "image.png", content_base64: commaIndex >= 0 ? result.slice(commaIndex + 1) : result });
    };
    reader.onerror = () => reject(reader.error || new Error("failed to read image"));
    reader.readAsDataURL(file);
  });
}

const ChatInput = forwardRef<ChatInputHandle, ChatInputProps>(
  ({ value, onChange, onSubmit, onClear, sending, autoFocus, extraButtons, placeholder }, ref) => {
    const inputRef = useRef<HTMLTextAreaElement | null>(null);
    const fileInputRef = useRef<HTMLInputElement | null>(null);
    const [cursorPos, setCursorPos] = useState<number>(0);
    const [attachedImages, setAttachedImages] = useState<AttachedImage[]>([]);

    const updateCursor = useCallback(() => {
      const el = inputRef.current;
      if (el) setCursorPos(el.selectionStart ?? el.value.length);
    }, []);

    useImperativeHandle(ref, () => ({ focus: () => inputRef.current?.focus() }));

    const addFiles = useCallback((files: File[]) => {
      const images = files.filter((file) => file.type.startsWith("image/"));
      if (!images.length) return;
      setAttachedImages((prev) => [
        ...prev,
        ...images.map((file) => ({ id: `${file.name}-${file.size}-${file.lastModified}-${crypto.randomUUID()}`, file, previewUrl: URL.createObjectURL(file) })),
      ]);
    }, []);

    const clearAttachedImages = useCallback(() => {
      setAttachedImages((prev) => {
        prev.forEach((image) => URL.revokeObjectURL(image.previewUrl));
        return [];
      });
    }, []);

    const removeAttachedImage = useCallback((id: string) => {
      setAttachedImages((prev) => prev.filter((image) => {
        if (image.id === id) URL.revokeObjectURL(image.previewUrl);
        return image.id !== id;
      }));
    }, []);

    useEffect(() => () => clearAttachedImages(), [clearAttachedImages]);

    const handleSubmit = useCallback(async () => {
      const trimmed = value.trim();
      if (onClear && (trimmed === "/cl" || trimmed === "/cle" || trimmed === "/clear")) {
        onChange("");
        onClear();
        return;
      }
      if (!trimmed && attachedImages.length === 0) return;
      const imageUploads = await Promise.all(attachedImages.map((image) => fileToImageUpload(image.file)));
      await onSubmit(imageUploads.length ? imageUploads : undefined);
      clearAttachedImages();
    }, [value, attachedImages, onChange, onClear, onSubmit, clearAttachedImages]);

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
        if (e.key.length === 1 || e.key === "Backspace" || e.key === "Delete") {
          // Don't steal focus if user has text selected (e.g., to copy)
          const sel = window.getSelection();
          if (sel && sel.toString().length > 0) return;
          textarea.focus();
          // The native event will replay in the now-focused textarea
        }
      };
      document.addEventListener("keydown", handler);
      return () => document.removeEventListener("keydown", handler);
    }, [handleSubmit]);

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

    const handlePaste = useCallback((e: React.ClipboardEvent<HTMLTextAreaElement>) => {
      const files = Array.from(e.clipboardData.files || []).filter((file) => file.type.startsWith("image/"));
      if (!files.length) return;
      e.preventDefault();
      addFiles(files);
    }, [addFiles]);

    return (
      <div className="mx-4 border-t border-sol-base02 shrink-0">
        {attachedImages.length > 0 && (
          <div className="flex gap-2 px-2 pt-2 pb-1 border-b border-sol-base02 overflow-x-auto">
            {attachedImages.map((image) => (
              <div key={image.id} className="relative shrink-0">
                <img src={image.previewUrl} alt={image.file.name} className="h-16 w-16 object-cover rounded border border-sol-base02" />
                <button type="button" onClick={() => removeAttachedImage(image.id)} className="absolute -top-1 -right-1 h-5 w-5 rounded-full bg-sol-red text-sol-base3 text-xs leading-5">×</button>
              </div>
            ))}
          </div>
        )}
        <div className="flex items-start px-2 py-1.5 border-b border-sol-base02" onClick={() => inputRef.current?.focus()}>
          <span className="text-sm sm:text-[0.775rem] text-sol-base01 font-mono mr-2 select-none leading-[1.4]">&gt;</span>
          <div className="flex-1 min-w-0 relative">
            {/* Mobile: plain visible textarea so long-press paste works */}
            <textarea
              ref={inputRef}
              value={value}
              onChange={(e) => { onChange(e.target.value); updateCursor(); }}
              onPaste={handlePaste}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); handleSubmit(); }
                else handleBashKeys(e);
                requestAnimationFrame(updateCursor);
              }}
              onKeyUp={updateCursor}
              onClick={updateCursor}
              onSelect={updateCursor}
              autoFocus={autoFocus}
              placeholder={placeholder}
              rows={1}
              className="sm:absolute sm:inset-0 sm:w-full sm:h-full sm:opacity-0 w-full resize-none bg-transparent text-sm sm:text-[0.775rem] font-mono text-sol-base0 leading-[1.4] min-h-[1.4em] outline-none caret-sol-base1 overflow-hidden sm:overflow-auto placeholder:text-sol-base01"
            />
            {/* Desktop: custom cursor display */}
            <div className="hidden sm:block text-[0.775rem] font-mono text-sol-base0 whitespace-pre-wrap break-words leading-[1.4] min-h-[1.4em]">
              {value ? <>
                {value.slice(0, cursorPos)}
                <span className="bg-sol-base0 text-sol-base03">{value[cursorPos] ?? " "}</span>
                {value.slice(cursorPos + 1)}
              </> : <>
                <span className="bg-sol-base0 text-sol-base03">{placeholder ? placeholder[0] : " "}</span>
                {placeholder ? <span className="text-sol-base01">{placeholder.slice(1)}</span> : null}
              </>}
            </div>
          </div>
        </div>
        <div className="px-2 pt-1 pb-1 text-sm sm:text-xs select-none flex items-center gap-2">
          <input ref={fileInputRef} type="file" accept="image/*" multiple className="hidden" onChange={(e) => { addFiles(Array.from(e.target.files || [])); e.currentTarget.value = ""; }} />
          <button type="button" onClick={() => fileInputRef.current?.click()} className="text-sol-base01 hover:text-sol-base1 font-mono">attach</button>
          {sending && <span className="text-sol-base01">sending...</span>}
          {extraButtons}
        </div>
      </div>
    );
  }
);

export default ChatInput;
