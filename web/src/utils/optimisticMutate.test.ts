import { describe, expect, it, vi } from "vitest";
import { applyItemPatch, optimisticListMutate, type SWRCacheHandle } from "./optimisticMutate";

interface Todo {
  todo_id: string;
  status: string;
}

describe("applyItemPatch", () => {
  it("patches the matching item across useSWRInfinite pages (T[][])", () => {
    const pages: Todo[][] = [
      [{ todo_id: "1", status: "pending" }, { todo_id: "2", status: "pending" }],
      [{ todo_id: "3", status: "active" }],
    ];
    const result = applyItemPatch<Todo>(pages, "todo_id", "2", { status: "active" });
    expect(result).toEqual([
      [{ todo_id: "1", status: "pending" }, { todo_id: "2", status: "active" }],
      [{ todo_id: "3", status: "active" }],
    ]);
  });

  it("patches the matching item in a plain array (T[])", () => {
    const list: Todo[] = [{ todo_id: "1", status: "pending" }, { todo_id: "2", status: "pending" }];
    const result = applyItemPatch<Todo>(list, "todo_id", "1", { status: "completed" });
    expect(result).toEqual([{ todo_id: "1", status: "completed" }, { todo_id: "2", status: "pending" }]);
  });

  it("patches a single detail object", () => {
    const detail: Todo = { todo_id: "1", status: "pending" };
    const result = applyItemPatch<Todo>(detail, "todo_id", "1", { status: "active" });
    expect(result).toEqual({ todo_id: "1", status: "active" });
  });

  it("leaves non-matching items and undefined data untouched", () => {
    const detail: Todo = { todo_id: "9", status: "pending" };
    expect(applyItemPatch<Todo>(detail, "todo_id", "1", { status: "active" })).toEqual(detail);
    expect(applyItemPatch<Todo>(undefined, "todo_id", "1", { status: "active" })).toBeUndefined();
  });
});

// Minimal fake matching SWR's Cache interface (keys/get/set/delete), enough
// to exercise optimisticListMutate's key enumeration + exact-key mutate calls
// without pulling in the real SWR cache/provider machinery.
function fakeSwr(initial: Record<string, unknown>): { swr: SWRCacheHandle; store: Map<string, unknown> } {
  const store = new Map<string, unknown>(Object.entries(initial));
  const mutate = vi.fn(async (key: string, data: unknown, opts?: { revalidate?: boolean }) => {
    if (typeof data === "function") {
      store.set(key, (data as (current: unknown) => unknown)(store.get(key)));
    } else if (data !== undefined) {
      store.set(key, data);
    }
    void opts;
    return store.get(key);
  });
  const cache: SWRCacheHandle["cache"] = {
    keys: () => store.keys(),
    get: (key: string) => store.get(key) as any,
    set: (key: string, value: any) => { store.set(key, value); },
    delete: (key: string) => { store.delete(key); },
  };
  return { swr: { cache, mutate: mutate as any }, store };
}

describe("optimisticListMutate", () => {
  it("patches useSWRInfinite (T[][]), plain array, and detail-object cache entries in one call", async () => {
    const { swr, store } = fakeSwr({
      "$inf$https://api/todo/list?status=pending": [[{ todo_id: "1", status: "pending" }]],
      "https://api/todo/list?status=active&limit=500": [{ todo_id: "1", status: "pending" }],
      "https://api/todo/detail?todo_id=1": { todo_id: "1", status: "pending" },
      "https://api/note/list": [{ note_id: "n1" }],
    });

    await optimisticListMutate<Todo>(swr, "/todo/", "todo_id", "1", { status: "active" }, async () => {});

    expect(store.get("$inf$https://api/todo/list?status=pending")).toEqual([[{ todo_id: "1", status: "active" }]]);
    expect(store.get("https://api/todo/list?status=active&limit=500")).toEqual([{ todo_id: "1", status: "active" }]);
    expect(store.get("https://api/todo/detail?todo_id=1")).toEqual({ todo_id: "1", status: "active" });
    expect(store.get("https://api/note/list")).toEqual([{ note_id: "n1" }]); // unmatched, untouched
  });

  it("applies the optimistic patch before the request settles, then revalidates the same keys", async () => {
    const calls: string[] = [];
    const { swr } = fakeSwr({ "https://api/todo/list": [{ todo_id: "1", status: "pending" }] });
    swr.mutate = vi.fn(async (_key: string, _data: unknown, opts?: { revalidate?: boolean }) => {
      calls.push(opts?.revalidate ? "revalidate" : "optimistic");
    }) as any;

    const request = vi.fn(async () => {
      calls.push("request");
    });

    await optimisticListMutate<Todo>(swr, "/todo/", "todo_id", "1", { status: "active" }, request);

    expect(calls).toEqual(["optimistic", "request", "revalidate"]);
  });

  it("still revalidates every matched key when the request rejects", async () => {
    const { swr } = fakeSwr({
      "https://api/todo/list": [{ todo_id: "1", status: "pending" }],
      "https://api/todo/detail?todo_id=1": { todo_id: "1", status: "pending" },
    });
    const revalidateKeys: string[] = [];
    const realMutate = swr.mutate;
    swr.mutate = vi.fn(async (key: string, data: unknown, opts?: { revalidate?: boolean }) => {
      if (opts?.revalidate) revalidateKeys.push(key);
      return realMutate(key, data, opts);
    }) as any;

    const request = vi.fn(async () => {
      throw new Error("network down");
    });

    await expect(
      optimisticListMutate<Todo>(swr, "/todo/", "todo_id", "1", { status: "active" }, request),
    ).rejects.toThrow("network down");

    expect(revalidateKeys.sort()).toEqual(["https://api/todo/detail?todo_id=1", "https://api/todo/list"]);
  });

  it("matches cache keys via string substring, regexp, and predicate", async () => {
    const { swr } = fakeSwr({
      "https://api/todo/list": [{ todo_id: "1", status: "pending" }],
      "https://api/note/list": [{ note_id: "n1" }],
    });

    await optimisticListMutate<Todo>(swr, "/todo/", "todo_id", "1", { status: "active" }, async () => {});
    await optimisticListMutate<Todo>(swr, /\/todo\//, "todo_id", "1", { status: "active" }, async () => {});
    await optimisticListMutate<Todo>(swr, (key) => key.includes("/todo/"), "todo_id", "1", { status: "active" }, async () => {});

    const matchedKeyCalls = (swr.mutate as ReturnType<typeof vi.fn>).mock.calls.map(([key]) => key as string);
    expect(matchedKeyCalls.every((key) => key.includes("/todo/"))).toBe(true);
    expect(matchedKeyCalls).not.toContain("https://api/note/list");
  });
});
