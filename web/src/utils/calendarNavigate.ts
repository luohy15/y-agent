// Host-side navigation into the Calendar module's focused day (shared by the
// `calendar.focusDate` host command, tag calendar_event dispatch, and
// TraceView's associated-event click). Extracted so the three call sites stay
// one implementation (todo 3179 H1 review nit).
import { artifactTabKey } from "../host/artifacts";
import { setArtifactIntent } from "../host/intents";

/** Focus the calendar artifact on `date` and open `ui:calendar`. */
export function openCalendarFocusDate(
  date: string,
  handleOpenFile: (path: string) => void,
): void {
  setArtifactIntent("calendar", { kind: "focus-date", date, nonce: Date.now() });
  handleOpenFile(artifactTabKey("calendar"));
}
