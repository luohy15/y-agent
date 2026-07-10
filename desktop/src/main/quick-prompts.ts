import { authenticatedJsonRequest } from './api-client';

export interface QuickPrompt {
  id: string;
  label: string;
  prompt: string;
}

export const QUICK_PROMPTS_PREFERENCE_KEY = 'desktopQuickPrompts';

export const DEFAULT_QUICK_PROMPTS: QuickPrompt[] = [
  {
    id: 'grammar-refine',
    label: 'Grammar refine',
    prompt: 'Refine the grammar and wording while preserving the original meaning.',
  },
];

interface PreferenceResponse {
  key: string;
  value: unknown;
  updated_at: string | null;
}

// IPC boundary guard: a save payload must be an array (an intentional
// empty [] is valid) — anything else (undefined, an object, a string, …)
// is rejected outright rather than silently coerced, since coercing to []
// would wipe the user's saved list on a malformed call.
export function isQuickPromptsPayload(value: unknown): value is unknown[] {
  return Array.isArray(value);
}

// Accept only objects with non-empty trimmed id/label/prompt; drop anything
// else. Returns null when `value` itself is absent (no preference saved yet)
// so callers can distinguish "never configured" from "deliberately emptied".
export function normalizeQuickPrompts(value: unknown): QuickPrompt[] | null {
  if (value === null || value === undefined) return null;
  if (!Array.isArray(value)) return [];
  const out: QuickPrompt[] = [];
  for (const item of value) {
    if (!item || typeof item !== 'object') continue;
    const raw = item as Record<string, unknown>;
    const id = typeof raw.id === 'string' ? raw.id.trim() : '';
    const label = typeof raw.label === 'string' ? raw.label.trim() : '';
    const prompt = typeof raw.prompt === 'string' ? raw.prompt.trim() : '';
    if (!id || !label || !prompt) continue;
    out.push({ id, label, prompt });
  }
  return out;
}

export async function loadQuickPrompts(): Promise<QuickPrompt[]> {
  const res = await authenticatedJsonRequest<PreferenceResponse>(
    'GET',
    `/api/user-preference?key=${encodeURIComponent(QUICK_PROMPTS_PREFERENCE_KEY)}`,
  );
  const normalized = normalizeQuickPrompts(res?.value);
  if (normalized === null) {
    // Never configured — seed and persist the default list once.
    return saveQuickPrompts(DEFAULT_QUICK_PROMPTS);
  }
  return normalized;
}

export async function saveQuickPrompts(prompts: unknown[]): Promise<QuickPrompt[]> {
  const normalized = normalizeQuickPrompts(prompts) ?? [];
  await authenticatedJsonRequest('PUT', '/api/user-preference', {
    key: QUICK_PROMPTS_PREFERENCE_KEY,
    value: normalized,
  });
  return normalized;
}
