import { describe, expect, it } from "vitest";
import { citationDomain, citationHostname } from "./citationDomain";

describe("citationDomain", () => {
  it("returns the first non-www hostname label", () => {
    expect(citationDomain("https://www.cnbc.com/foo")).toBe("cnbc");
    expect(citationDomain("https://finance.yahoo.com/x")).toBe("finance");
  });

  it("falls back to the raw URL when parsing fails", () => {
    expect(citationDomain("not a url")).toBe("not a url");
  });
});

describe("citationHostname", () => {
  it("removes www from parsed hostnames", () => {
    expect(citationHostname("https://www.cnbc.com/foo")).toBe("cnbc.com");
  });
});
