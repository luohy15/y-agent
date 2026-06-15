import { describe, expect, it } from "vitest";
import { formatResetCountdown, parseClaudeResetAt } from "./ClaudeUsageWidget";

describe("ClaudeUsageWidget reset helpers", () => {
  it("parses same-day UTC reset times", () => {
    const now = new Date("2026-06-15T04:00:00Z");
    expect(parseClaudeResetAt("4:59am (UTC)", now)?.toISOString()).toBe("2026-06-15T04:59:00.000Z");
  });

  it("rolls same-day UTC reset times to tomorrow when already past", () => {
    const now = new Date("2026-06-15T05:00:00Z");
    expect(parseClaudeResetAt("4:59am (UTC)", now)?.toISOString()).toBe("2026-06-16T04:59:00.000Z");
  });

  it("parses dated weekly UTC reset strings", () => {
    const now = new Date("2026-06-15T04:00:00Z");
    expect(parseClaudeResetAt("Jun 17, 8:59am (UTC)", now)?.toISOString()).toBe("2026-06-17T08:59:00.000Z");
  });

  it("rolls dated reset strings across the year boundary", () => {
    const now = new Date("2026-12-31T20:00:00Z");
    expect(parseClaudeResetAt("Jan 1, 8am (UTC)", now)?.toISOString()).toBe("2027-01-01T08:00:00.000Z");
  });

  it("formats short reset countdowns", () => {
    const now = new Date("2026-06-15T04:00:00Z");
    expect(formatResetCountdown("4:59am (UTC)", now)).toBe("in 59m");
  });

  it("formats multi-day reset countdowns compactly", () => {
    const now = new Date("2026-06-15T04:00:00Z");
    expect(formatResetCountdown("Jun 17, 8:59am (UTC)", now)).toBe("in 2d 4h");
  });
});
