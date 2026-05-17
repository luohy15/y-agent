import { describe, expect, it } from "vitest";
import { pickImageSrc } from "./MessageBubble";

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
