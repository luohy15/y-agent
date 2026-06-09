import { describe, expect, it } from "vitest";
import { toggleSelection, selectMessagesByIndices, buildExportFilename, pickImageDelivery } from "./messageExport";
import type { Message } from "../components/MessageList";

describe("toggleSelection", () => {
  it("adds an index that is not present", () => {
    const next = toggleSelection(new Set([1]), 2);
    expect(Array.from(next).sort()).toEqual([1, 2]);
  });

  it("removes an index that is present", () => {
    const next = toggleSelection(new Set([1, 2]), 2);
    expect(Array.from(next)).toEqual([1]);
  });

  it("returns a new set without mutating the input", () => {
    const input = new Set([1]);
    const next = toggleSelection(input, 2);
    expect(input).not.toBe(next);
    expect(Array.from(input)).toEqual([1]);
  });
});

describe("selectMessagesByIndices", () => {
  const messages: Message[] = [
    { role: "user", content: "a" },
    { role: "assistant", content: "b" },
    { role: "user", content: "c" },
    { role: "assistant", content: "d" },
  ];

  it("maps indices to messages in document order regardless of selection order", () => {
    const out = selectMessagesByIndices(messages, [3, 0, 1]);
    expect(out.map((m) => m.content)).toEqual(["a", "b", "d"]);
  });

  it("dedupes repeated indices", () => {
    const out = selectMessagesByIndices(messages, [1, 1, 2]);
    expect(out.map((m) => m.content)).toEqual(["b", "c"]);
  });

  it("drops out-of-range indices", () => {
    const out = selectMessagesByIndices(messages, [-1, 0, 99]);
    expect(out.map((m) => m.content)).toEqual(["a"]);
  });

  it("returns an empty array for an empty selection", () => {
    expect(selectMessagesByIndices(messages, [])).toEqual([]);
  });
});

describe("buildExportFilename", () => {
  it("formats the timestamp into a png filename", () => {
    const date = new Date(2026, 5, 9, 19, 45, 12); // 2026-06-09 19:45:12 local
    expect(buildExportFilename(date)).toBe("chat-export-20260609-194512.png");
  });

  it("zero-pads single-digit components", () => {
    const date = new Date(2026, 0, 3, 4, 5, 6); // 2026-01-03 04:05:06 local
    expect(buildExportFilename(date)).toBe("chat-export-20260103-040506.png");
  });
});

describe("pickImageDelivery", () => {
  it("shares on a touch device that can share files (mobile)", () => {
    expect(pickImageDelivery({ canShareFiles: true, isTouch: true })).toBe("share");
  });

  it("downloads on desktop (no touch) even when file-share is available", () => {
    expect(pickImageDelivery({ canShareFiles: true, isTouch: false })).toBe("download");
  });

  it("downloads on a touch device that cannot share files", () => {
    expect(pickImageDelivery({ canShareFiles: false, isTouch: true })).toBe("download");
  });

  it("downloads when neither signal is present", () => {
    expect(pickImageDelivery({ canShareFiles: false, isTouch: false })).toBe("download");
  });
});
