export {};

type CodecRequest = {
  id: number;
  blob: Blob;
  version: number;
  width: number;
  height: number;
  rows: number;
  columns: number;
  seed: string;
  pageNumber: number;
};

const SALT_V4 = 'mreader-v4-overlap-tilepack';
const V4_MAGIC = [77, 82, 84, 73, 76, 69, 52, 0];
const V4_HEADER_BYTES = 28;

function hash32(input: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}
function mulberry32(seed: number) {
  return () => {
    let t = (seed += 0x6d2b79f5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function permutation(count: number, material: string): number[] {
  const out = Array.from({ length: count }, (_, i) => i);
  const rand = mulberry32(hash32(material));
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}
function permutationV4(count: number, seed: string, pageNumber: number) { return permutation(count, `${SALT_V4}:${seed}:page:${pageNumber}:${count}`); }
function bounds(total: number, count: number, index: number) {
  const p0 = Math.floor((index * total) / count);
  const p1 = Math.floor(((index + 1) * total) / count);
  return { p: p0, size: Math.max(1, p1 - p0) };
}

async function decodeV4(req: CodecRequest): Promise<OffscreenCanvas> {
  const buffer = await req.blob.arrayBuffer();
  if (buffer.byteLength < V4_HEADER_BYTES) throw new Error('Protected v4 tile-pack is truncated');
  const magic = new Uint8Array(buffer, 0, 8);
  if (!V4_MAGIC.every((value, index) => magic[index] === value)) throw new Error('Invalid protected v4 tile-pack magic');
  const view = new DataView(buffer);
  const rows = view.getUint16(8);
  const columns = view.getUint16(10);
  const overlap = view.getUint16(12);
  const width = view.getUint32(16);
  const height = view.getUint32(20);
  const total = view.getUint32(24);
  if (rows !== req.rows || columns !== req.columns || width !== req.width || height !== req.height || total !== rows * columns || total > 1024) {
    throw new Error('Protected v4 tile-pack metadata does not match chapter manifest');
  }
  let cursor = V4_HEADER_BYTES + total * 4;
  if (cursor > buffer.byteLength) throw new Error('Protected v4 length table is truncated');
  const lengths = Array.from({ length: total }, (_, i) => view.getUint32(V4_HEADER_BYTES + i * 4));
  const tileRanges: Array<{ start: number; end: number }> = [];
  for (const length of lengths) {
    if (length < 1 || cursor + length > buffer.byteLength) throw new Error('Protected v4 tile payload is truncated');
    tileRanges.push({ start: cursor, end: cursor + length });
    cursor += length;
  }
  if (cursor !== buffer.byteLength) throw new Error('Protected v4 tile-pack has trailing bytes');

  const out = new OffscreenCanvas(width, height);
  const ctx = out.getContext('2d', { alpha: false });
  if (!ctx) throw new Error('Could not create v4 worker canvas');
  ctx.imageSmoothingEnabled = false;
  const order = permutationV4(total, req.seed, req.pageNumber);

  // Default v4 is 4x4 (16 tiles); sequential decode prevents a low-memory phone
  // from materializing all compressed tiles and all ImageBitmaps simultaneously.
  for (let encodedIndex = 0; encodedIndex < total; encodedIndex++) {
    const range = tileRanges[encodedIndex];
    const tileBlob = req.blob.slice(range.start, range.end, 'image/webp');
    const bitmap = await createImageBitmap(tileBlob);
    try {
      const originalIndex = order[encodedIndex];
      const row = Math.floor(originalIndex / columns);
      const col = originalIndex % columns;
      const bx = bounds(width, columns, col);
      const by = bounds(height, rows, row);
      const left = Math.max(0, bx.p - overlap);
      const top = Math.max(0, by.p - overlap);
      const sx = bx.p - left;
      const sy = by.p - top;
      if (bitmap.width < sx + bx.size || bitmap.height < sy + by.size) throw new Error('Protected v4 tile dimensions are invalid');
      ctx.drawImage(bitmap, sx, sy, bx.size, by.size, bx.p, by.p, bx.size, by.size);
    } finally {
      bitmap.close();
    }
  }
  return out;
}

async function processRequest(req: CodecRequest): Promise<void> {
  try {
    if (req.version !== 4) throw new Error(`Unsupported protected-page codec v${req.version}; current MReader requires v4`);
    const out = await decodeV4(req);
    const decodedBitmap = out.transferToImageBitmap();
    self.postMessage({ id: req.id, ok: true, bitmap: decodedBitmap, width: req.width, height: req.height }, [decodedBitmap]);
  } catch (error) {
    self.postMessage({ id: req.id, ok: false, error: error instanceof Error ? error.message : String(error) });
  }
}

// A Web Worker can receive the next message while an async onmessage handler is
// awaiting createImageBitmap(). With 1080x8192 webtoon segments this previously
// allowed several large OffscreenCanvas instances to decode at once, producing
// memory spikes and seemingly random missing pages on constrained browsers.
// Keep one protected decode active at a time; network prefetch can still overlap.
const decodeQueue: CodecRequest[] = [];
let draining = false;

async function drainQueue(): Promise<void> {
  if (draining) return;
  draining = true;
  try {
    while (decodeQueue.length > 0) {
      const req = decodeQueue.shift();
      if (req) await processRequest(req);
    }
  } finally {
    draining = false;
  }
}

self.onmessage = (event: MessageEvent<CodecRequest>) => {
  decodeQueue.push(event.data);
  void drainQueue();
};
