export const INPUT_DEVICE_KEY = "y.voice.audioinput";

export interface AudioInput {
  deviceId: string;
  label: string;
}

type DeviceStore = {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
};

const PSEUDO_INPUT_IDS = new Set(["default", "communications"]);

export function listAudioInputs(devices: Array<{ kind: string; deviceId: string; label: string }>): AudioInput[] {
  const seen = new Set<string>();
  const inputs: AudioInput[] = [];
  for (const device of devices) {
    if (device.kind !== "audioinput" || !device.deviceId || PSEUDO_INPUT_IDS.has(device.deviceId) || seen.has(device.deviceId)) continue;
    seen.add(device.deviceId);
    inputs.push({ deviceId: device.deviceId, label: device.label.trim() || `Microphone ${inputs.length + 1}` });
  }
  return inputs;
}

export function readInputDeviceId(storage: Pick<DeviceStore, "getItem">): string {
  try {
    return storage.getItem(INPUT_DEVICE_KEY)?.trim() ?? "";
  } catch {
    return "";
  }
}

export function writeInputDeviceId(storage: Pick<DeviceStore, "setItem" | "removeItem">, deviceId: string): void {
  try {
    if (deviceId) storage.setItem(INPUT_DEVICE_KEY, deviceId);
    else storage.removeItem(INPUT_DEVICE_KEY);
  } catch {
    // private mode
  }
}
