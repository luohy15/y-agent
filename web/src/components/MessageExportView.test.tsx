import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import MessageExportView from "./MessageExportView";
import type { Message } from "./MessageList";

vi.mock("./ArtifactRenderer", () => ({
  default: ({ type }: { type: string }) => React.createElement("div", { "data-type": type }),
}));

describe("MessageExportView", () => {
  const messages: Message[] = [
    { role: "user", content: "what is the answer" },
    { role: "assistant", content: "the answer is 42" },
  ];

  it("renders each selected message and the export chrome", () => {
    const html = renderToStaticMarkup(
      React.createElement(MessageExportView, { messages }),
    );
    expect(html).toContain("what is the answer");
    expect(html).toContain("the answer is 42");
    expect(html).toContain("y-agent");
  });

  it("applies the fixed export width for the long-image layout", () => {
    const html = renderToStaticMarkup(
      React.createElement(MessageExportView, { messages, width: 390 }),
    );
    expect(html).toContain("width:390px");
  });
});
