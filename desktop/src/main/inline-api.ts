import { net } from 'electron';
import { state } from './state';
import { APP_URL } from './constants';

export interface InlineApiResponse {
  result: string;
}

// Read the JWT that the web app stores in localStorage on the main window. The
// prompt window is a separate BrowserWindow without access to that storage, so
// the main process pulls the token on demand via executeJavaScript.
export async function getJwtFromMainWindow(): Promise<string | null> {
  const { mainWindow } = state;
  if (!mainWindow || mainWindow.isDestroyed()) return null;
  try {
    return await mainWindow.webContents.executeJavaScript(
      'localStorage.getItem("jwt_token")',
    );
  } catch (err) {
    console.error('[inline] failed to read jwt_token:', (err as Error).message);
    return null;
  }
}

export async function callInlineApi(
  selection: string,
  instruction: string,
): Promise<InlineApiResponse> {
  const token = await getJwtFromMainWindow();
  if (!token) throw new Error('not signed in (no jwt_token on main window)');

  const body = JSON.stringify({ selection, instruction });
  return new Promise<InlineApiResponse>((resolve, reject) => {
    const req = net.request({ method: 'POST', url: `${APP_URL}/api/inline` });
    req.setHeader('Content-Type', 'application/json');
    req.setHeader('Authorization', `Bearer ${token}`);
    req.on('response', (resp) => {
      let raw = '';
      resp.on('data', (chunk) => {
        raw += chunk.toString();
      });
      resp.on('end', () => {
        const status = resp.statusCode ?? 0;
        if (status >= 200 && status < 300) {
          try {
            resolve(JSON.parse(raw));
          } catch {
            reject(new Error(`bad json: ${raw}`));
          }
        } else {
          reject(new Error(`HTTP ${status}: ${raw}`));
        }
      });
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}
