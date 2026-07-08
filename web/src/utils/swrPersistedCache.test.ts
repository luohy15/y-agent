import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { localStorageProvider, __test__ } from "./swrPersistedCache";

const { STORAGE_KEY, LEGACY_STORAGE_KEY, MAX_ENTRY_BYTES, SNAPSHOT_TTL_MS, loadEntries, flush } = __test__;

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("flush", () => {
  it("skips denylisted keys (e.g. /api/trace/chats)", () => {
    const map = new Map<string, unknown>([
      ["/api/trace/chats?trace_id=2676", { data: { big: "x" } }],
      ["/api/todo/list", { data: [{ id: "1" }] }],
    ]);
    flush(map);
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY)!);
    const keys = saved.entries.map(([key]: [string, unknown]) => key);
    expect(keys).toEqual(["/api/todo/list"]);
  });

  it("skips entries whose serialized form exceeds the per-entry cap", () => {
    const oversized = "x".repeat(MAX_ENTRY_BYTES);
    const map = new Map<string, unknown>([
      ["/api/big/thing", { data: oversized }],
      ["/api/todo/list", { data: [{ id: "1" }] }],
    ]);
    flush(map);
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY)!);
    const keys = saved.entries.map(([key]: [string, unknown]) => key);
    expect(keys).toEqual(["/api/todo/list"]);
  });

  it("skips entries with data === undefined", () => {
    const map = new Map<string, unknown>([
      ["/api/todo/list", { isLoading: true }],
      ["/api/todo/detail", { data: { id: "1" } }],
    ]);
    flush(map);
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY)!);
    const keys = saved.entries.map(([key]: [string, unknown]) => key);
    expect(keys).toEqual(["/api/todo/detail"]);
  });

  it("writes a savedAt timestamp alongside the entries", () => {
    const before = Date.now();
    flush(new Map([["/api/todo/list", { data: [1] }]]));
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY)!);
    expect(saved.savedAt).toBeGreaterThanOrEqual(before);
  });

  it("self-heals by removing the storage key when setItem still throws (quota exceeded)", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ savedAt: Date.now(), entries: [] }));
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("quota exceeded", "QuotaExceededError");
    });

    flush(new Map([["/api/todo/list", { data: [1] }]]));

    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    expect(warnSpy).toHaveBeenCalledOnce();
  });
});

describe("loadEntries", () => {
  it("seeds from a fresh snapshot", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ savedAt: Date.now(), entries: [["/api/todo/list", { data: [1] }]] }));
    expect(Array.from(loadEntries())).toEqual([["/api/todo/list", { data: [1] }]]);
  });

  it("discards a snapshot older than the TTL", () => {
    const savedAt = Date.now() - SNAPSHOT_TTL_MS - 1000;
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ savedAt, entries: [["/api/todo/list", { data: [1] }]] }));
    expect(Array.from(loadEntries())).toEqual([]);
  });

  it("falls back to empty on malformed payload", () => {
    localStorage.setItem(STORAGE_KEY, "not json");
    expect(Array.from(loadEntries())).toEqual([]);
  });

  it("falls back to empty on a legacy v1-shaped payload (no savedAt)", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([["/api/todo/list", { data: [1] }]]));
    expect(Array.from(loadEntries())).toEqual([]);
  });
});

describe("localStorageProvider", () => {
  it("removes the legacy v1 key on init", () => {
    localStorage.setItem(LEGACY_STORAGE_KEY, JSON.stringify([["/api/todo/list", { data: [1] }]]));
    localStorageProvider();
    expect(localStorage.getItem(LEGACY_STORAGE_KEY)).toBeNull();
  });
});
