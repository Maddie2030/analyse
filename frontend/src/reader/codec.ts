export type ProtectedPageEncoding = {
  version: number;
  width: number;
  height: number;
  rows: number;
  columns: number;
  seed: string;
  pageNumber: number;
};

export type DecodedProtectedPage = {
  bitmap: ImageBitmap;
  width: number;
  height: number;
};

const SALT_V4 = 'mreader-v4-overlap-tilepack';
const V4_MAGIC = [77, 82, 84, 73, 76, 69, 52, 0]; // MRTILE4\0
const V4_HEADER_BYTES = 28;

let workerAvailable = typeof Worker !== 'undefined' && typeof OffscreenCanvas !== 'undefined' && typeof createImageBitmap === 'function';
const worker = workerAvailable
  ? new Worker(new URL('./codec.worker.ts', import.meta.url), { type: 'module' })
  : null;
let sequence = 0;
const pending = new Map<number, { resolve: (page: DecodedProtectedPage) => void; reject: (error: Error) => void }>();

if (worker) {
  worker.onmessage = (event) => {
    const { id, ok, bitmap, width, height, error } = event.data as {
      id: number; ok: boolean; bitmap?: ImageBitmap; width?: number; height?: number; error?: string;
    };
    const task = pending.get(id);
    if (!task) {
      bitmap?.close();
      return;
    }
    pending.delete(id);
    if (ok && bitmap && width && height) task.resolve({ bitmap, width, height });
    else task.reject(new Error(error || 'Protected page decode failed'));
  };
  worker.onerror = () => {
    workerAvailable = false;
    for (const [, task] of pending) task.reject(new Error('Protected page worker failed'));
    pending.clear();
  };
}

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

function permutationV4(count: number, seed: string, pageNumber: number): number[] {
  return permutation(count, `${SALT_V4}:${seed}:page:${pageNumber}:${count}`);
}

function bounds(total: number, count: number, index: number) {
  const p0 = Math.floor((index * total) / count);
  const p1 = Math.floor(((index + 1) * total) / count);
  return { p: p0, size: Math.max(1, p1 - p0) };
}

type V4Pack = { rows: number; columns: number; overlap: number; width: number; height: number; tiles: Blob[] };
async function parseV4(blob: Blob): Promise<V4Pack> {
  const buffer = await blob.arrayBuffer();
  if (buffer.byteLength < V4_HEADER_BYTES) throw new Error('Protected v4 tile-pack is truncated.');
  const bytes = new Uint8Array(buffer, 0, 8);
  if (!V4_MAGIC.every((value, index) => bytes[index] === value)) throw new Error('Invalid protected v4 tile-pack magic.');
  const view = new DataView(buffer);
  const rows = view.getUint16(8);
  const columns = view.getUint16(10);
  const overlap = view.getUint16(12);
  const width = view.getUint32(16);
  const height = view.getUint32(20);
  const total = view.getUint32(24);
  if (rows < 1 || columns < 1 || total !== rows * columns || total > 1024 || width < 1 || height < 1) {
    throw new Error('Invalid protected v4 tile-pack header.');
  }
  let cursor = V4_HEADER_BYTES + total * 4;
  if (cursor > buffer.byteLength) throw new Error('Protected v4 length table is truncated.');
  const lengths: number[] = [];
  for (let i = 0; i < total; i++) lengths.push(view.getUint32(V4_HEADER_BYTES + i * 4));
  const tiles: Blob[] = [];
  for (const length of lengths) {
    if (length < 1 || cursor + length > buffer.byteLength) throw new Error('Protected v4 tile payload is truncated.');
    tiles.push(blob.slice(cursor, cursor + length, 'image/webp'));
    cursor += length;
  }
  if (cursor !== buffer.byteLength) throw new Error('Protected v4 tile-pack has trailing bytes.');
  return { rows, columns, overlap, width, height, tiles };
}

type DecodedSource = { source: CanvasImageSource; width: number; height: number; close: () => void };
async function decodeImageSource(blob: Blob): Promise<DecodedSource> {
  if (typeof createImageBitmap === 'function') {
    const bitmap = await createImageBitmap(blob);
    return { source: bitmap, width: bitmap.width, height: bitmap.height, close: () => bitmap.close() };
  }
  const url = URL.createObjectURL(blob);
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const candidate = new Image();
      candidate.onload = () => resolve(candidate);
      candidate.onerror = () => reject(new Error('Browser rejected protected page image'));
      candidate.src = url;
    });
    return { source: image, width: image.naturalWidth, height: image.naturalHeight, close: () => URL.revokeObjectURL(url) };
  } catch (error) {
    URL.revokeObjectURL(url);
    throw error;
  }
}

async function decodeWithWorker(blob: Blob, encoding: ProtectedPageEncoding): Promise<DecodedProtectedPage> {
  if (!worker || !workerAvailable) throw new Error('Worker unavailable');
  const id = ++sequence;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    worker.postMessage({ id, blob, ...encoding });
  });
}

async function decodeV4OnMainThread(blob: Blob, encoding: ProtectedPageEncoding): Promise<DecodedProtectedPage> {
  const pack = await parseV4(blob);
  if (pack.width !== encoding.width || pack.height !== encoding.height || pack.rows !== encoding.rows || pack.columns !== encoding.columns) {
    throw new Error('Protected v4 tile-pack metadata does not match the chapter manifest.');
  }
  const canvas = document.createElement('canvas');
  canvas.width = pack.width;
  canvas.height = pack.height;
  const ctx = canvas.getContext('2d', { alpha: false });
  if (!ctx) throw new Error('Could not create protected v4 page canvas.');
  ctx.imageSmoothingEnabled = false;
  const order = permutationV4(pack.tiles.length, encoding.seed, encoding.pageNumber);
  for (let encodedIndex = 0; encodedIndex < pack.tiles.length; encodedIndex++) {
    const originalIndex = order[encodedIndex];
    const row = Math.floor(originalIndex / pack.columns);
    const col = originalIndex % pack.columns;
    const bx = bounds(pack.width, pack.columns, col);
    const by = bounds(pack.height, pack.rows, row);
    const left = Math.max(0, bx.p - pack.overlap);
    const top = Math.max(0, by.p - pack.overlap);
    const decoded = await decodeImageSource(pack.tiles[encodedIndex]);
    try {
      const sx = bx.p - left;
      const sy = by.p - top;
      if (decoded.width < sx + bx.size || decoded.height < sy + by.size) throw new Error('Protected v4 tile dimensions are invalid.');
      ctx.drawImage(decoded.source, sx, sy, bx.size, by.size, bx.p, by.p, bx.size, by.size);
    } finally {
      decoded.close();
    }
  }
  const bitmap = await createImageBitmap(canvas);
  canvas.width = 1;
  canvas.height = 1;
  return { bitmap, width: pack.width, height: pack.height };
}

async function decodeOnMainThread(blob: Blob, encoding: ProtectedPageEncoding): Promise<DecodedProtectedPage> {
  if (encoding.version !== 4) throw new Error(`Unsupported protected-page codec v${encoding.version}; current MReader requires v4.`);
  return decodeV4OnMainThread(blob, encoding);
}

export async function decodeProtectedPage(blob: Blob, encoding: ProtectedPageEncoding): Promise<DecodedProtectedPage> {
  if (encoding.version !== 4) throw new Error(`Unsupported protected-page codec v${encoding.version}; current MReader requires v4.`);
  if (worker && workerAvailable) {
    try {
      return await decodeWithWorker(blob, encoding);
    } catch (error) {
      console.warn('Protected page worker decode failed; using main thread fallback.', error);
    }
  }
  return decodeOnMainThread(blob, encoding);
}
