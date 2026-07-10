import { net } from 'electron';
import { getJwtFromMainWindow } from './inline-api';
import { APP_URL } from './constants';

// Shared authenticated JSON request helper for main-process calls to
// yovy.app's REST API. Mirrors callInlineApi's net.request wiring but is
// generic over method/path/body so other API surfaces (e.g. user-preference)
// don't need to duplicate the JWT + net.request plumbing.
export async function authenticatedJsonRequest<T>(
  method: 'GET' | 'PUT' | 'DELETE',
  path: string,
  body?: unknown,
): Promise<T> {
  const token = await getJwtFromMainWindow();
  if (!token) throw new Error('not signed in (no jwt_token on main window)');

  return new Promise<T>((resolve, reject) => {
    const req = net.request({ method, url: `${APP_URL}${path}` });
    req.setHeader('Authorization', `Bearer ${token}`);
    if (body !== undefined) req.setHeader('Content-Type', 'application/json');
    req.on('response', (resp) => {
      let raw = '';
      resp.on('data', (chunk) => {
        raw += chunk.toString();
      });
      resp.on('end', () => {
        const status = resp.statusCode ?? 0;
        if (status >= 200 && status < 300) {
          try {
            resolve(raw ? JSON.parse(raw) : (undefined as T));
          } catch {
            reject(new Error(`bad json: ${raw}`));
          }
        } else {
          reject(new Error(`HTTP ${status}: ${raw}`));
        }
      });
    });
    req.on('error', reject);
    if (body !== undefined) req.write(JSON.stringify(body));
    req.end();
  });
}
