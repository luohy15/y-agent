import { describe, expect, it } from "vitest";
import { wordDiff } from "./wordDiff";

describe("wordDiff", () => {
  it("returns a single same span for identical strings", () => {
    expect(wordDiff("hello world", "hello world")).toEqual([
      { type: "same", text: "hello world" },
    ]);
  });

  it("handles insert-only", () => {
    const spans = wordDiff("I finish", "I have finish");
    expect(spans).toEqual([
      { type: "same", text: "I " },
      { type: "ins", text: "have " },
      { type: "same", text: "finish" },
    ]);
  });

  it("handles delete-only", () => {
    const spans = wordDiff("I already finish it", "I finish it");
    expect(spans.map((s) => s.type)).toContain("del");
    const joined = spans.filter((s) => s.type !== "del").map((s) => s.text).join("");
    expect(joined).toBe("I finish it");
  });

  it("handles mixed insert and delete", () => {
    const spans = wordDiff(
      "I already finish the draft",
      "I have already finished the draft",
    );
    const types = spans.map((s) => s.type);
    expect(types).toContain("ins");
    expect(types).toContain("del");
    // Reconstruct original and corrected from spans
    const orig = spans
      .filter((s) => s.type !== "ins")
      .map((s) => s.text)
      .join("");
    const corr = spans
      .filter((s) => s.type !== "del")
      .map((s) => s.text)
      .join("");
    expect(orig).toBe("I already finish the draft");
    expect(corr).toBe("I have already finished the draft");
  });

  it("leaves CJK segments untouched when English around them changes", () => {
    const spans = wordDiff(
      "先修一下, then I will push the fix",
      "先修一下, then I push the fix",
    );
    const joined = spans.map((s) => s.text).join("");
    expect(joined).toContain("先修一下");
    const orig = spans.filter((s) => s.type !== "ins").map((s) => s.text).join("");
    const corr = spans.filter((s) => s.type !== "del").map((s) => s.text).join("");
    expect(orig).toBe("先修一下, then I will push the fix");
    expect(corr).toBe("先修一下, then I push the fix");
  });

  it("returns empty for empty identical inputs", () => {
    expect(wordDiff("", "")).toEqual([]);
  });
});
