// Host-side navigation into the Email module's thread reader (todo 3270 A4).
// Additive only in deploy A: no call site switches yet (tag drill-down stays
// on the legacy panel until deploy B). Mirrors calendarNavigate.ts.
import { artifactTabKey } from "../host/artifacts";
import { setArtifactIntent } from "../host/intents";

/** Focus the email artifact on `threadId`/`account` and open `ui:email`. */
export function openEmailThread(
  threadId: string,
  account: string,
  handleOpenFile: (path: string) => void,
): void {
  setArtifactIntent("email", { kind: "thread", threadId, account, nonce: Date.now() });
  handleOpenFile(artifactTabKey("email"));
}
