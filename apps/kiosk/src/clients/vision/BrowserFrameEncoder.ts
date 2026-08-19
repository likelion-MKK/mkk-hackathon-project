import type {
  EphemeralVideoFrame,
  VisionFrameEncoder,
  VisionFrameEncoding,
} from "./RemoteVisionClient.ts";

const JPEG_QUALITY = 0.82;

function requireImageSource(frame: EphemeralVideoFrame): CanvasImageSource {
  if (!frame.source) {
    throw new Error("Ephemeral video frame does not expose a browser image source.");
  }
  return frame.source;
}

function requireContext(
  context: OffscreenCanvasRenderingContext2D | CanvasRenderingContext2D | null,
): OffscreenCanvasRenderingContext2D | CanvasRenderingContext2D {
  if (!context) throw new Error("Browser canvas 2D context is unavailable.");
  return context;
}

async function encodeWithOffscreenCanvas(
  frame: EphemeralVideoFrame,
  encoding: VisionFrameEncoding,
): Promise<Uint8Array> {
  const canvas = new globalThis.OffscreenCanvas(frame.width, frame.height);
  const context = requireContext(canvas.getContext("2d"));
  context.drawImage(requireImageSource(frame), 0, 0, frame.width, frame.height);
  const blob = await canvas.convertToBlob({ type: encoding, quality: JPEG_QUALITY });
  return new Uint8Array(await blob.arrayBuffer());
}

function canvasToBlob(
  canvas: HTMLCanvasElement,
  encoding: VisionFrameEncoding,
): Promise<Blob> {
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) resolve(blob);
        else reject(new Error("Browser canvas could not encode the video frame."));
      },
      encoding,
      JPEG_QUALITY,
    );
  });
}

async function encodeWithCanvas(
  frame: EphemeralVideoFrame,
  encoding: VisionFrameEncoding,
): Promise<Uint8Array> {
  const canvas = document.createElement("canvas");
  canvas.width = frame.width;
  canvas.height = frame.height;
  const context = requireContext(canvas.getContext("2d"));
  context.drawImage(requireImageSource(frame), 0, 0, frame.width, frame.height);
  const blob = await canvasToBlob(canvas, encoding);
  return new Uint8Array(await blob.arrayBuffer());
}

export const browserFrameEncoder: VisionFrameEncoder = async (frame, encoding) => {
  const bytes =
    typeof globalThis.OffscreenCanvas === "function"
      ? await encodeWithOffscreenCanvas(frame, encoding)
      : await encodeWithCanvas(frame, encoding);
  if (bytes.byteLength === 0) throw new Error("Browser frame encoding produced no bytes.");
  return bytes;
};
