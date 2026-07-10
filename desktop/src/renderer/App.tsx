import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { QuickPrompts } from './QuickPrompts';

export function App() {
  const [selection, setSelection] = useState('');
  const [instruction, setInstruction] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState('');
  const [hasResult, setHasResult] = useState(false);
  const [edited, setEdited] = useState(false);
  const [quickPromptsResetToken, setQuickPromptsResetToken] = useState(0);

  const inputRef = useRef<HTMLInputElement>(null);
  const resultRef = useRef<HTMLTextAreaElement>(null);

  // Measure the total content height and ask main to resize the window.
  // Main caps at half the screen height.
  const fitWindow = useCallback(() => {
    void document.body.offsetHeight;
    const h = document.documentElement.scrollHeight || document.body.scrollHeight;
    window.api.resize(h);
  }, []);

  // Resize the result textarea to fit its content; overflow:auto kicks in
  // once the window-half cap is reached.
  const autosizeResult = useCallback(() => {
    const el = resultRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight}px`;
  }, []);

  // Reset everything whenever the popup is re-shown.
  useEffect(() => {
    window.api.onInit(({ selection: sel }) => {
      setSelection(sel || '');
      setInstruction('');
      setBusy(false);
      setError(null);
      setResult('');
      setHasResult(false);
      setEdited(false);
      setQuickPromptsResetToken((n) => n + 1);
      requestAnimationFrame(() => {
        inputRef.current?.focus();
        fitWindow();
      });
    });
  }, [fitWindow]);

  // Global Esc dismiss.
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

  // Re-fit on any visible state change.
  useLayoutEffect(() => {
    requestAnimationFrame(fitWindow);
  }, [hasResult, error, busy, fitWindow]);

  // Autosize the result textarea once it appears and after content updates.
  useLayoutEffect(() => {
    if (!hasResult) return;
    autosizeResult();
    requestAnimationFrame(() => {
      autosizeResult();
      fitWindow();
    });
  }, [hasResult, result, autosizeResult, fitWindow]);

  // Shared by Enter (free-form input) and quick-prompt pill clicks so both
  // paths run the exact same request/response handling.
  const submitInstruction = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    setInstruction(text);
    setBusy(true);
    setError(null);
    const res = await window.api.submit(trimmed);
    setBusy(false);
    if (res && res.ok) {
      const resultText = res.result || '';
      setResult(resultText);
      window.api.copy(resultText);
      setEdited(false);
      setHasResult(true);
    } else {
      setError((res && res.error) || 'request failed');
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  };

  const handleSubmit = () => submitInstruction(instruction);

  const onResultChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setResult(e.target.value);
    setEdited(true);
    requestAnimationFrame(() => {
      autosizeResult();
      fitWindow();
    });
  };

  return (
    <>
      <div className="grip" title="Drag to move">• • •</div>
      <div className="wrap">
        <Section label="Selection">
          {selection ? (
            <div className="preview">{selection}</div>
          ) : (
            <div className="preview empty">(no selection — instruction only)</div>
          )}
        </Section>

        <QuickPrompts
          busy={busy}
          onRun={(prompt) => void submitInstruction(prompt)}
          onLayoutChange={fitWindow}
          resetToken={quickPromptsResetToken}
        />

        <Section label={hasResult ? 'Prompt · Enter to re-run' : 'Prompt · Enter to run'}>
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
        </Section>

        {hasResult && (
          <Section label="Response">
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
          </Section>
        )}
      </div>
    </>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="section">
      <div className="section-label">{label}</div>
      {children}
    </div>
  );
}
