import { contextBridge, ipcRenderer } from 'electron';

export interface InitPayload {
  selection: string;
}

export interface SubmitResult {
  ok: boolean;
  result?: string;
  error?: string;
}

const api = {
  onInit: (cb: (payload: InitPayload) => void) =>
    ipcRenderer.on('prompt:init', (_e, payload: InitPayload) => cb(payload)),
  submit: (instruction: string): Promise<SubmitResult> =>
    ipcRenderer.invoke('prompt:submit', { instruction }),
  copy: (text: string) => ipcRenderer.send('prompt:copy', text),
  resize: (height: number) => ipcRenderer.send('prompt:resize', height),
  close: () => ipcRenderer.send('prompt:close'),
};

contextBridge.exposeInMainWorld('api', api);

export type Api = typeof api;
