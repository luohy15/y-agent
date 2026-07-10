import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { QuickPrompt } from './global';

type LoadStatus = 'loading' | 'loaded' | 'error';

interface QuickPromptsProps {
  busy: boolean;
  onRun: (prompt: string) => void;
  onLayoutChange: () => void;
  // Bumped whenever the popup is freshly re-shown (including a possible
  // account switch), so this remounts its data cleanly: no prior account's
  // prompts, no stale cache — always a fresh authenticated load.
  resetToken: number;
}

export function QuickPrompts({ busy, onRun, onLayoutChange, resetToken }: QuickPromptsProps) {
  // No local default/fallback list here — seeding an empty (`value === null`)
  // preference with the default is main's job (main/quick-prompts.ts). Until
  // a real load resolves, there is nothing runnable to show.
  const [status, setStatus] = useState<LoadStatus>('loading');
  const [prompts, setPrompts] = useState<QuickPrompt[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [managerOpen, setManagerOpen] = useState(false);
  const [draft, setDraft] = useState<QuickPrompt[]>([]);
  const [draftErrors, setDraftErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);

  // Monotonic request id so an out-of-order completion (an older in-flight
  // load resolving/rejecting after a newer one already landed — e.g. a fast
  // account-B load beating a slow account-A load triggered just before it)
  // can never overwrite the latest state. Bumped synchronously at the start
  // of every load() call, so by the time an older call's await resumes, a
  // newer call already moved the ref past it and its guard check fails.
  const requestIdRef = useRef(0);

  const load = useCallback(async () => {
    requestIdRef.current += 1;
    const requestId = requestIdRef.current;
    setStatus('loading');
    setLoadError(null);
    setPrompts([]);
    try {
      const res = await window.api.getQuickPrompts();
      if (requestIdRef.current !== requestId) return; // superseded — ignore
      if (res.ok && res.prompts) {
        setPrompts(res.prompts);
        setStatus('loaded');
      } else {
        setLoadError((res && res.error) || 'failed to load quick prompts');
        setStatus('error');
      }
    } catch (err) {
      if (requestIdRef.current !== requestId) return; // superseded — ignore
      setLoadError((err as Error).message || 'failed to load quick prompts');
      setStatus('error');
    }
  }, []);

  // Re-run on mount and on every popup re-show. A fresh load (not a cached
  // render of the previous state) is what guarantees a reset/account switch
  // never exposes a prior account's prompts.
  useEffect(() => {
    void load();
  }, [load, resetToken]);

  useEffect(() => {
    setManagerOpen(false);
  }, [resetToken]);

  useLayoutEffect(() => {
    requestAnimationFrame(onLayoutChange);
  }, [
    status,
    prompts,
    managerOpen,
    draft,
    draftErrors,
    loadError,
    saveError,
    savedFlash,
    onLayoutChange,
  ]);

  const openManager = () => {
    if (status !== 'loaded') return;
    setDraft(prompts.map((p) => ({ ...p })));
    setDraftErrors({});
    setSaveError(null);
    setSavedFlash(false);
    setManagerOpen(true);
  };

  const updateDraft = (id: string, field: 'label' | 'prompt', value: string) => {
    setDraft((cur) => cur.map((p) => (p.id === id ? { ...p, [field]: value } : p)));
  };

  const removeDraft = (id: string) => {
    setDraft((cur) => cur.filter((p) => p.id !== id));
    setDraftErrors((cur) => {
      if (!(id in cur)) return cur;
      const next = { ...cur };
      delete next[id];
      return next;
    });
  };

  const addDraft = () => {
    setDraft((cur) => [...cur, { id: crypto.randomUUID(), label: '', prompt: '' }]);
  };

  const handleSave = async () => {
    const errors: Record<string, string> = {};
    const cleaned: QuickPrompt[] = [];
    for (const p of draft) {
      const label = p.label.trim();
      const prompt = p.prompt.trim();
      if (!label || !prompt) {
        errors[p.id] = 'Label and prompt are both required';
        continue;
      }
      cleaned.push({ id: p.id, label, prompt });
    }
    setDraftErrors(errors);
    if (Object.keys(errors).length > 0) return;

    setSaving(true);
    setSaveError(null);
    const res = await window.api.saveQuickPrompts(cleaned);
    setSaving(false);
    if (res.ok && res.prompts) {
      setPrompts(res.prompts);
      setManagerOpen(false);
      setSavedFlash(true);
      window.setTimeout(() => setSavedFlash(false), 1500);
    } else {
      setSaveError((res && res.error) || 'failed to save quick prompts');
    }
  };

  return (
    <div className="section">
      <div className="section-label-row">
        <span className="section-label">Quick prompts</span>
        <button
          type="button"
          className={`manage-btn${managerOpen ? ' active' : ''}`}
          title={managerOpen ? 'Close quick-prompt manager' : 'Manage quick prompts'}
          onClick={() => (managerOpen ? setManagerOpen(false) : openManager())}
          disabled={status !== 'loaded'}
        >
          <span aria-hidden="true">⚙</span>
          {managerOpen ? 'Close' : 'Manage'}
        </button>
      </div>

      {!managerOpen && (
        <>
          {status === 'loading' && <div className="hint">Loading quick prompts…</div>}

          {status === 'loaded' && (
            <div className="pills">
              {prompts.length > 0 ? (
                prompts.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    className="pill"
                    disabled={busy}
                    onClick={() => onRun(p.prompt)}
                  >
                    {p.label}
                  </button>
                ))
              ) : (
                <span className="hint">No quick prompts yet</span>
              )}
            </div>
          )}

          {status === 'error' && (
            <div className="err">
              {loadError}{' '}
              <button type="button" className="link-btn" onClick={() => void load()}>
                Retry
              </button>
            </div>
          )}

          {savedFlash && <div className="saved-flash">✓ Saved</div>}
        </>
      )}

      {managerOpen && (
        <div className="manager">
          {draft.map((p) => (
            <div className="manager-row" key={p.id}>
              <input
                type="text"
                placeholder="Label"
                value={p.label}
                onChange={(e) => updateDraft(p.id, 'label', e.target.value)}
              />
              <input
                type="text"
                placeholder="Prompt"
                value={p.prompt}
                onChange={(e) => updateDraft(p.id, 'prompt', e.target.value)}
              />
              <div className="manager-row-footer">
                {draftErrors[p.id] && <span className="err small">{draftErrors[p.id]}</span>}
                <button
                  type="button"
                  className="link-btn danger"
                  onClick={() => removeDraft(p.id)}
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
          {draft.length === 0 && <div className="hint">No quick prompts — add one below.</div>}
          <div className="manager-actions">
            <button type="button" className="link-btn" onClick={addDraft}>
              + Add prompt
            </button>
            <div className="manager-actions-right">
              <button
                type="button"
                className="link-btn"
                onClick={() => setManagerOpen(false)}
                disabled={saving}
              >
                Cancel
              </button>
              <button
                type="button"
                className="save-btn"
                onClick={() => void handleSave()}
                disabled={saving}
              >
                {saving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
          {saveError && (
            <div className="err">
              {saveError}{' '}
              <button type="button" className="link-btn" onClick={() => void handleSave()}>
                Retry
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
