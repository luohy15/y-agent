import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import MessageBubble, { artifactTypeFromClassName, pickImageSrc, preprocessCitationLinks } from "./MessageBubble";

vi.mock("./ArtifactRenderer", () => ({
  default: ({ type, spec }: { type: string; spec: string }) => React.createElement("div", { "data-testid": "artifact-renderer", "data-type": type }, spec),
}));

describe("pickImageSrc", () => {
  it("passes through https image URLs", () => {
    expect(pickImageSrc("https://example.com/image.png")).toBe("https://example.com/image.png");
  });

  it("passes through http image URLs", () => {
    expect(pickImageSrc("http://example.com/image.png")).toBe("http://example.com/image.png");
  });

  it("maps luohy15 s3 images to the CDN", () => {
    expect(pickImageSrc("s3://luohy15/assets/images/cat.jpg")).toBe("https://cdn.luohy15.com/assets/images/cat.jpg");
  });

  it("returns null for local paths so they use the blob flow", () => {
    expect(pickImageSrc("/Users/roy/luohy15/assets/images/cat.jpg")).toBeNull();
  });
});

describe("preprocessCitationLinks", () => {
  const links = [{ url: "https://example.com/source" }];

  it("converts adjacent numeric citation runs into cite links", () => {
    expect(preprocessCitationLinks("Answer [1][2] text [3].", links)).toBe("Answer [cite](cite://1,2) text [cite](cite://3).");
  });

  it("leaves content unchanged when message has no links", () => {
    expect(preprocessCitationLinks("Answer [1][2].", [])).toBe("Answer [1][2].");
    expect(preprocessCitationLinks("Answer [1][2].", undefined)).toBe("Answer [1][2].");
  });
});

describe("artifactTypeFromClassName", () => {
  it("detects supported artifact fence languages", () => {
    expect(artifactTypeFromClassName("language-mermaid")).toBe("mermaid");
    expect(artifactTypeFromClassName("language-vega-lite")).toBe("vega-lite");
    expect(artifactTypeFromClassName("language-artifact-svg")).toBe("artifact-svg");
  });

  it("does not treat regular svg code blocks as artifacts", () => {
    expect(artifactTypeFromClassName("language-svg")).toBeNull();
  });
});

describe("artifact rendering", () => {
  it("renders mermaid fences through ArtifactView instead of raw code", () => {
    const spec = `flowchart TD
    A[Start] --> B{Is it X?}
    B -->|Yes| C[Do X]
    B -->|No| D[Try again]
    C --> E[End]
    D --> B`;
    const html = renderToStaticMarkup(
      React.createElement(MessageBubble, {
        role: "assistant",
        content: `\`\`\`mermaid\n${spec}\n\`\`\``,
        onOpenArtifact: () => {},
      }),
    );

    expect(html).toContain('data-testid="artifact-renderer"');
    expect(html).toContain('data-type="mermaid"');
    expect(html).toContain("Open in tab");
    expect(html).not.toContain("<pre>");
    expect(html).not.toContain('class="language-mermaid"');
  });
});


describe("citation chips", () => {
  it("renders a chip label for legacy string citation links", () => {
    const html = renderToStaticMarkup(
      React.createElement(MessageBubble, {
        role: "assistant",
        content: "Legacy source [1]",
        links: ["https://www.example.com/article"],
      }),
    );

    expect(html).toContain("example");
    expect(html).not.toContain("Legacy source [1]");
  });
});
