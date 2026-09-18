declare global {
  interface Window {
    __MREADER_CONFIG__?: {
      imageCdnUrl?: string;
      imageCdnSendCredentials?: boolean;
      readerPreloadBehind?: number;
      readerPreloadAhead?: number;
      readerFetchBehind?: number;
      readerFetchAhead?: number;
      readerRetainBehind?: number;
      readerRetainAhead?: number;
      adminPlane?: boolean;
    };
  }
}

function boolValue(value: unknown, fallback = false): boolean {
  if (typeof value === 'boolean') return value;
  const text = String(value ?? '').trim().toLowerCase();
  if (['1', 'true', 'yes', 'on'].includes(text)) return true;
  if (['0', 'false', 'no', 'off'].includes(text)) return false;
  return fallback;
}

function nonNegativeInt(value: unknown, fallback: number): number {
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) && n >= 0 ? Math.floor(n) : fallback;
}

const raw = window.__MREADER_CONFIG__ ?? {};

const legacyBehind = nonNegativeInt(raw.readerPreloadBehind, 2);
const legacyAhead = nonNegativeInt(raw.readerPreloadAhead, 4);

export const runtimeConfig = {
  imageCdnUrl: String(raw.imageCdnUrl ?? '').replace(/\/+$/, ''),
  imageCdnSendCredentials: boolValue(raw.imageCdnSendCredentials, false),
  // Network fetches are intentionally much tighter than decoded-page retention.
  // This prevents a chapter open from downloading many pages the user never reads.
  readerFetchBehind: nonNegativeInt(raw.readerFetchBehind, 1),
  readerFetchAhead: nonNegativeInt(raw.readerFetchAhead, 2),
  readerRetainBehind: nonNegativeInt(raw.readerRetainBehind, legacyBehind),
  readerRetainAhead: nonNegativeInt(raw.readerRetainAhead, legacyAhead),
  adminPlane: boolValue(raw.adminPlane, false),
};

export function protectedAssetCacheIdentity(path: string): string {
  const relative = `/images/${path.replace(/^\/+/, '')}`;
  return runtimeConfig.imageCdnUrl ? `${runtimeConfig.imageCdnUrl}${relative}` : relative;
}

export function protectedAssetUrl(path: string, token: string): string {
  return `${protectedAssetCacheIdentity(path)}?token=${encodeURIComponent(token)}`;
}
