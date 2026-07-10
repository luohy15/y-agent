export interface InitPayload {
  selection: string;
}

export interface SubmitResult {
  ok: boolean;
  result?: string;
  error?: string;
}

export interface QuickPrompt {
  id: string;
  label: string;
  prompt: string;
}

export interface QuickPromptsResult {
  ok: boolean;
  prompts?: QuickPrompt[];
  error?: string;
}

export interface YovyApi {
  onInit: (cb: (payload: InitPayload) => void) => void;
  submit: (instruction: string) => Promise<SubmitResult>;
  copy: (text: string) => void;
  resize: (height: number) => void;
  close: () => void;
  getQuickPrompts: () => Promise<QuickPromptsResult>;
  saveQuickPrompts: (prompts: QuickPrompt[]) => Promise<QuickPromptsResult>;
}

declare global {
  interface Window {
    api: YovyApi;
  }
}
