import { describe, expect, it } from "vitest";
import { localFilePathFromMarkdownHref } from "./localFileLinks";

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
