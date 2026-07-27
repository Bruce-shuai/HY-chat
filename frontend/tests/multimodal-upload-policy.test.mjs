import assert from "node:assert/strict";
import test from "node:test";

import {
  buildUploadAttachmentAccept,
  isImageContentBlock,
  isSupportedUploadFile,
} from "../src/lib/multimodal-utils.ts";

const image = { name: "camera.jpg", type: "image/jpeg" };
const pdf = { name: "report.pdf", type: "application/pdf" };

test("text-only models exclude and reject image attachments", () => {
  const accept = buildUploadAttachmentAccept(false);

  assert.equal(accept.includes("image/jpeg"), false);
  assert.equal(isSupportedUploadFile(image, false), false);
  assert.equal(isSupportedUploadFile(pdf, false), true);
});

test("verified vision models can accept supported image attachments", () => {
  const accept = buildUploadAttachmentAccept(true);

  assert.equal(accept.includes("image/jpeg"), true);
  assert.equal(isSupportedUploadFile(image, true), true);
  assert.equal(
    isSupportedUploadFile(
      { name: "unsupported.heic", type: "image/heic" },
      true,
    ),
    false,
  );
});

test("image MIME types cannot masquerade as text files", () => {
  assert.equal(
    isSupportedUploadFile({ name: "renamed.txt", type: "image/jpeg" }, false),
    false,
  );
  assert.equal(
    isSupportedUploadFile({ name: "camera.jpg", type: "" }, false),
    false,
  );
  assert.equal(
    isSupportedUploadFile({ name: "camera.jpg", type: "text/plain" }, false),
    false,
  );
});

test("image block detection covers current and legacy provider formats", () => {
  for (const block of [
    { type: "image", mimeType: "image/jpeg" },
    { type: "image_url", image_url: { url: "data:image/png;base64,abc" } },
    { type: "input_image", image_url: "data:image/png;base64,abc" },
    { type: "media", media_type: "image/webp" },
    { type: "file", content_type: "image/png" },
    { type: "media", source: { media_type: "image/png" } },
    {
      type: "file",
      file: { file_data: "data:IMAGE/PNG;base64,abc" },
    },
    { type: "media", media_type: " IMAGE/PNG " },
  ]) {
    assert.equal(isImageContentBlock(block), true);
  }

  assert.equal(isImageContentBlock({ type: "text", text: "hello" }), false);
  assert.equal(
    isImageContentBlock({
      type: "text",
      text: "business metadata",
      image_url: null,
    }),
    false,
  );
  assert.equal(
    isImageContentBlock({ type: "file", mimeType: "application/pdf" }),
    false,
  );
});
