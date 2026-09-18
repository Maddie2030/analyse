import { protectedAssetCacheIdentity } from '../config/runtime';

const PROTECTED_ASSET_CACHE_NAME = 'mreader-protected-assets-v1';
const PROTECTED_ASSET_DB_NAME = 'mreader-protected-assets-v1';
const PROTECTED_ASSET_DB_STORE = 'assets';
const PROTECTED_ASSET_CACHE_MAX_AGE_MS = 365 * 24 * 60 * 60 * 1000;
const CACHED_AT_HEADER = 'X-MReader-Cached-At';

type StoredAsset = {
  key: string;
  blob: Blob;
  cachedAt: number;
  contentType: string;
};

function stableIdentity(path: string): string {
  return new URL(protectedAssetCacheIdentity(path), window.location.href).href;
}

function cacheStorageAvailable(): boolean {
  return typeof window !== 'undefined' && 'caches' in window;
}

function indexedDbAvailable(): boolean {
  return typeof window !== 'undefined' && 'indexedDB' in window;
}

function cacheRequest(path: string): Request {
  return new Request(stableIdentity(path), {
    method: 'GET',
    credentials: 'omit',
  });
}

function responseFromStoredAsset(record: StoredAsset): Response {
  return new Response(record.blob, {
    status: 200,
    statusText: 'OK',
    headers: {
      'Content-Type': record.contentType || record.blob.type || 'application/octet-stream',
      'Cache-Control': 'public, max-age=31536000, immutable',
      [CACHED_AT_HEADER]: String(record.cachedAt),
    },
  });
}

function openAssetDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = window.indexedDB.open(PROTECTED_ASSET_DB_NAME, 1);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(PROTECTED_ASSET_DB_STORE)) {
        db.createObjectStore(PROTECTED_ASSET_DB_STORE, { keyPath: 'key' });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error('Protected asset IndexedDB open failed.'));
    request.onblocked = () => reject(new Error('Protected asset IndexedDB open was blocked.'));
  });
}

async function readIndexedDb(path: string): Promise<Response | null> {
  if (!indexedDbAvailable()) return null;
  const db = await openAssetDb();
  try {
    const key = stableIdentity(path);
    const record = await new Promise<StoredAsset | undefined>((resolve, reject) => {
      const tx = db.transaction(PROTECTED_ASSET_DB_STORE, 'readonly');
      const request = tx.objectStore(PROTECTED_ASSET_DB_STORE).get(key);
      request.onsuccess = () => resolve(request.result as StoredAsset | undefined);
      request.onerror = () => reject(request.error || new Error('Protected asset IndexedDB read failed.'));
    });
    if (!record) return null;
    if (
      !Number.isFinite(record.cachedAt) ||
      record.cachedAt <= 0 ||
      Date.now() - record.cachedAt > PROTECTED_ASSET_CACHE_MAX_AGE_MS
    ) {
      await deleteIndexedDb(path, db);
      return null;
    }
    return responseFromStoredAsset(record);
  } finally {
    db.close();
  }
}

async function writeIndexedDb(path: string, blob: Blob): Promise<void> {
  if (!indexedDbAvailable()) return;
  const db = await openAssetDb();
  try {
    const record: StoredAsset = {
      key: stableIdentity(path),
      blob,
      cachedAt: Date.now(),
      contentType: blob.type || 'application/octet-stream',
    };
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(PROTECTED_ASSET_DB_STORE, 'readwrite');
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error || new Error('Protected asset IndexedDB write failed.'));
      tx.onabort = () => reject(tx.error || new Error('Protected asset IndexedDB write aborted.'));
      tx.objectStore(PROTECTED_ASSET_DB_STORE).put(record);
    });
  } finally {
    db.close();
  }
}

async function deleteIndexedDb(path: string, existingDb?: IDBDatabase): Promise<void> {
  if (!indexedDbAvailable()) return;
  const db = existingDb || await openAssetDb();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(PROTECTED_ASSET_DB_STORE, 'readwrite');
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error || new Error('Protected asset IndexedDB delete failed.'));
      tx.onabort = () => reject(tx.error || new Error('Protected asset IndexedDB delete aborted.'));
      tx.objectStore(PROTECTED_ASSET_DB_STORE).delete(stableIdentity(path));
    });
  } finally {
    if (!existingDb) db.close();
  }
}

/**
 * Read an immutable encoded v4 page from persistent browser storage using a
 * token-independent identity. Callers must still possess a current chapter
 * grant before using this helper; the cache is an asset-byte optimization, not
 * an authorization mechanism.
 *
 * CacheStorage is preferred on secure origins. IndexedDB is the compatible
 * fallback for the Docker/Desktop HTTP development topology and browsers where
 * CacheStorage is unavailable by policy.
 */
export async function readProtectedAssetCache(path: string): Promise<Response | null> {
  if (cacheStorageAvailable()) {
    try {
      const cache = await window.caches.open(PROTECTED_ASSET_CACHE_NAME);
      const request = cacheRequest(path);
      const response = (await cache.match(request)) ?? null;
      if (response) {
        const cachedAt = Number(response.headers.get(CACHED_AT_HEADER) || 0);
        if (
          Number.isFinite(cachedAt) &&
          cachedAt > 0 &&
          Date.now() - cachedAt <= PROTECTED_ASSET_CACHE_MAX_AGE_MS
        ) {
          return response;
        }
        await cache.delete(request);
      }
    } catch {
      // Fall through to IndexedDB below.
    }
  }

  try {
    return await readIndexedDb(path);
  } catch {
    // Private browsing/storage pressure/browser policy can disable persistent
    // storage. The Reader remains fully functional via the protected network path.
    return null;
  }
}

/**
 * Persist a validated encoded page under its immutable path rather than the
 * short-lived ?token= URL. Browser storage is best-effort and may be evicted
 * early under device/origin storage pressure.
 */
export async function writeProtectedAssetCache(
  path: string,
  blob: Blob,
  sourceHeaders?: Headers,
): Promise<void> {
  if (blob.size <= 0) return;

  if (cacheStorageAvailable()) {
    try {
      // Rebuild only the headers needed by the local cache response. Copying
      // transport headers such as Vary/Content-Encoding can make Cache.put reject
      // an otherwise valid decoded response body.
      const headers = new Headers({
        'Content-Type': sourceHeaders?.get('Content-Type') || blob.type || 'application/octet-stream',
        'Cache-Control': 'public, max-age=31536000, immutable',
        [CACHED_AT_HEADER]: String(Date.now()),
      });

      const response = new Response(blob, {
        status: 200,
        statusText: 'OK',
        headers,
      });
      const cache = await window.caches.open(PROTECTED_ASSET_CACHE_NAME);
      await cache.put(cacheRequest(path), response);
      return;
    } catch {
      // Try IndexedDB below before giving up.
    }
  }

  try {
    await writeIndexedDb(path, blob);
  } catch {
    // Quota exhaustion or eviction races must never break reading. A later
    // revisit simply falls back to the protected network endpoint/edge cache.
  }
}

export async function evictProtectedAssetCacheEntry(path: string): Promise<void> {
  if (cacheStorageAvailable()) {
    try {
      const cache = await window.caches.open(PROTECTED_ASSET_CACHE_NAME);
      await cache.delete(cacheRequest(path));
    } catch {
      // Continue with IndexedDB cleanup.
    }
  }
  try {
    await deleteIndexedDb(path);
  } catch {
    // Best-effort cleanup only.
  }
}

/** Clear protected encoded bytes when the user explicitly signs out. */
export async function clearProtectedAssetCache(): Promise<void> {
  if (cacheStorageAvailable()) {
    try {
      await window.caches.delete(PROTECTED_ASSET_CACHE_NAME);
    } catch {
      // Continue with IndexedDB cleanup.
    }
  }

  if (indexedDbAvailable()) {
    try {
      await new Promise<void>((resolve, reject) => {
        const request = window.indexedDB.deleteDatabase(PROTECTED_ASSET_DB_NAME);
        request.onsuccess = () => resolve();
        request.onerror = () => reject(request.error || new Error('Protected asset IndexedDB cleanup failed.'));
        request.onblocked = () => resolve();
      });
    } catch {
      // Logout itself must not fail because browser storage cleanup failed.
    }
  }
}
