import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';

type Phase = 'input' | 'result';

export function App() {
  const [phase, setPhase] = useState<Phase>('input');
  const [selection, setSelection] = useState('');
  const [instruction, setInstruction] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState('');
  const [edited, setEdited] = useState(false);

  const inputRef = useRef<HTMLInputElement>(null);
  const resultRef = useRef<HTMLTextAreaElement>(null);

  // Measure the total content height (grip + active phase + bottom padding)
  // and ask main to resize the window. Main caps at half the screen height.
  const fitWindow = useCallback(() => {
    // Force layout flush so scrollHeight is accurate after recent DOM edits.
    void document.body.offsetHeight;
    const h = document.documentElement.scrollHeight || document.body.scrollHeight;
    window.api.resize(h);
  }, []);

  // Resize the textarea to fit its content (the window-half cap is enforced
  // by the main process when we call api.resize). overflow:auto kicks in if
  // we're already at the cap and the text is still longer.
  const autosizeTextarea = useCallback(() => {
    const el = resultRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight}px`;
  }, []);

  // Subscribe to prompt:init from main on mount. Resets everything to a fresh
  // input phase whenever the popup is shown again.
  useEffect(() => {
    window.api.onInit(({ selection: sel }) => {
      setSelection(sel || '');
      setInstruction('');
      setBusy(false);
      setError(null);
      setResult('');
      setEdited(false);
      setPhase('input');
      requestAnimationFrame(() => {
        inputRef.current?.focus();
        fitWindow();
      });
    });
  }, [fitWindow]);

  // Global Esc — works in both phases.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        window.api.close();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  // Re-fit any time the visible phase or error changes so the window stays snug.
  useLayoutEffect(() => {
    requestAnimationFrame(fitWindow);
  }, [phase, error, fitWindow]);

  // After switching to result phase, autosize the textarea once it's in the DOM,
  // then fit the window and focus/select for ⌘C convenience.
  useLayoutEffect(() => {
    if (phase !== 'result') return;
    autosizeTextarea();
    requestAnimationFrame(() => {
      autosizeTextarea();
      fitWindow();
      resultRef.current?.focus();
      resultRef.current?.select();
    });
  }, [phase, autosizeTextarea, fitWindow]);

  const handleSubmit = async () => {
    const trimmed = instruction.trim();
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    const res = await window.api.submit(trimmed);
    if (res && res.ok) {
      const text = res.result || '';
      setResult(text);
      window.api.copy(text);
      setEdited(false);
      setPhase('result');
    } else {
      setError((res && res.error) || 'request failed');
      setBusy(false);
      requestAnimationFrame(() => {
        inputRef.current?.focus();
      });
    }
  };

  const onResultChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setResult(e.target.value);
    setEdited(true);
    requestAnimationFrame(() => {
      autosizeTextarea();
      fitWindow();
    });
  };

  return (
    <>
      <div className="grip" title="Drag to move">• • •</div>
      <div className="wrap">
        {phase === 'input' ? (
          <div>
            <Preview selection={selection} />
            <input
              ref={inputRef}
              type="text"
              placeholder="Instruction · Enter to run · Esc to dismiss"
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  void handleSubmit();
                }
              }}
              disabled={busy}
              autoFocus
            />
            {error && <div className="err">{error}</div>}
          </div>
        ) : (
          <div>
            <Preview selection={selection} />
            <textarea
              ref={resultRef}
              spellCheck={false}
              value={result}
              onChange={onResultChange}
            />
            <div className="footer">
              <span className={`status${edited ? ' faded' : ''}`}>
                {edited ? 'Edited · ⌘C to copy' : '✓ Copied to clipboard'}
              </span>
              <span className="hint">⌘C copy · Esc close</span>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

function Preview({ selection }: { selection: string }) {
  if (!selection) {
    return <div className="preview empty">(no selection — instruction only)</div>;
  }
  return <div className="preview">{selection}</div>;
}
