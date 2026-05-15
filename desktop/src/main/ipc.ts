import { app, clipboard, ipcMain, screen } from 'electron';
import { state } from './state';
import { callInlineApi } from './inline-api';

export function registerIpcHandlers(): void {
  ipcMain.handle(
    'prompt:submit',
    async (_e, payload: { instruction?: string } | undefined) => {
      const instruction = (payload && payload.instruction) || '';
      try {
        const { result } = await callInlineApi(state.lastSelection, instruction);
        const text = typeof result === 'string' ? result : String(result ?? '');
        return { ok: true, result: text };
      } catch (err) {
        const message = (err as Error).message;
        console.error('[inline] request failed:', message);
        return { ok: false, error: message };
      }
    },
  );

  ipcMain.on('prompt:copy', (_e, text: unknown) => {
    if (typeof text === 'string') clipboard.writeText(text);
  });

  ipcMain.on('prompt:resize', (_e, height: unknown) => {
    const { promptWindow } = state;
    if (!promptWindow || promptWindow.isDestroyed()) return;
    // Cap at half the work area of whichever display the popup is currently on.
    // The renderer measures content; we just enforce screen bounds here.
    const display =
      screen.getDisplayMatching(promptWindow.getBounds()) || screen.getPrimaryDisplay();
    const maxH = Math.floor((display.workAreaSize.height || 800) / 2);
    const h = Math.max(60, Math.min(maxH, Math.ceil(Number(height) || 0)));
    const [w] = promptWindow.getSize();
    promptWindow.setSize(w, h, false);
  });

  ipcMain.on('prompt:close', () => {
    const { promptWindow } = state;
    if (promptWindow && !promptWindow.isDestroyed()) promptWindow.hide();
    // Submitting reads the JWT from the main window's webContents, which
    // promotes Yovy to the active app on macOS. If Yovy wasn't already in
    // front when the popup was triggered, hand focus back to the previous
    // app so dismissing the panel doesn't surface the main window.
    if (process.platform === 'darwin' && !state.yovyWasFront) app.hide();
  });
}
