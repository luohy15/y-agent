import { describe, expect, it } from "vitest";
import { isPersistableTab } from "./artifacts";

describe("isPersistableTab", () => {
  it("persists ui: artifact tabs", () => {
    expect(isPersistableTab("ui:finance")).toBe(true);
  });

  it("persists ordinary file tabs", () => {
    expect(isPersistableTab("notes/x.md")).toBe(true);
  });

  it("excludes artifact: inline chart tabs", () => {
    expect(isPersistableTab("artifact:ab12.mermaid")).toBe(false);
  });
});
