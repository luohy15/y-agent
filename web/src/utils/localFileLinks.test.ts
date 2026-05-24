import { describe, expect, it } from "vitest";
import { localFilePathFromMarkdownHref, parseLocalFileReference } from "./localFileLinks";

describe("localFilePathFromMarkdownHref", () => {
  it("accepts absolute local markdown file links", () => {
    expect(localFilePathFromMarkdownHref("/Users/roy/luohy15/pages/x-profile.md"))
      .toBe("/Users/roy/luohy15/pages/x-profile.md");
  });

  it("accepts relative file links for chat workdir resolution", () => {
    expect(localFilePathFromMarkdownHref("pages/x-profile.md")).toBe("pages/x-profile.md");
    expect(localFilePathFromMarkdownHref("./docs/getting-started.md")).toBe("./docs/getting-started.md");
  });

  it("can leave relative links to a file-relative resolver", () => {
    expect(localFilePathFromMarkdownHref("child.md", { allowRelative: false })).toBeNull();
    expect(localFilePathFromMarkdownHref("./child.md", { allowRelative: false })).toBeNull();
    expect(localFilePathFromMarkdownHref("docs/child.md", { allowRelative: false })).toBeNull();
    expect(localFilePathFromMarkdownHref("/Users/roy/luohy15/pages/child.md", { allowRelative: false }))
      .toBe("/Users/roy/luohy15/pages/child.md");
  });

  it("ignores external and non-file navigation hrefs", () => {
    expect(localFilePathFromMarkdownHref("https://example.com/a.md")).toBeNull();
    expect(localFilePathFromMarkdownHref("mailto:test@example.com")).toBeNull();
    expect(localFilePathFromMarkdownHref("#section")).toBeNull();
    expect(localFilePathFromMarkdownHref("/trace/2083")).toBeNull();
  });

  it("rejects unsafe path shapes", () => {
    expect(localFilePathFromMarkdownHref("../secret.md")).toBeNull();
    expect(localFilePathFromMarkdownHref("/Users/roy/../secret.md")).toBeNull();
    expect(localFilePathFromMarkdownHref("//example.com/file.md")).toBeNull();
  });
});

describe("parseLocalFileReference", () => {
  it("parses absolute file references with line suffixes", () => {
    expect(parseLocalFileReference("/Users/roy/luohy15/pages/x-profile.md:42"))
      .toEqual({ path: "/Users/roy/luohy15/pages/x-profile.md", line: 42 });
    expect(parseLocalFileReference("/Users/roy/luohy15/pages/x-profile.md:42:5"))
      .toEqual({ path: "/Users/roy/luohy15/pages/x-profile.md", line: 42, column: 5 });
  });

  it("parses relative file references with line suffixes", () => {
    expect(parseLocalFileReference("web/src/App.tsx:10"))
      .toEqual({ path: "web/src/App.tsx", line: 10 });
    expect(parseLocalFileReference("./web/src/App.tsx:10:2"))
      .toEqual({ path: "./web/src/App.tsx", line: 10, column: 2 });
  });

  it("leaves non-numeric colon suffixes in the path", () => {
    expect(parseLocalFileReference("web/src/App.tsx:abc"))
      .toEqual({ path: "web/src/App.tsx:abc" });
  });

  it("rejects zero line or column suffixes", () => {
    expect(parseLocalFileReference("web/src/App.tsx:0")).toBeNull();
    expect(parseLocalFileReference("web/src/App.tsx:10:0")).toBeNull();
  });

  it("rejects line suffixes stripped from non-file paths", () => {
    expect(parseLocalFileReference("docs/guide:1")).toBeNull();
  });
});
