import { useEffect, useMemo, useRef, useState } from 'react';
import { type Page } from '../api/client';
import { decodeProtectedPage, type DecodedProtectedPage } from './codec';
import { protectedAssetUrl, runtimeConfig } from '../config/runtime';
import {
  evictProtectedAssetCacheEntry,
  readProtectedAssetCache,
  writeProtectedAssetCache,
} from './protectedAssetCache';

type Props = {
  page: Page;
  chapterToken: string;
  refreshChapterToken: () => Promise<string>;
  fetchEnabled: boolean;
  retainDecoded: boolean;
  alt: string;
  onLoaded?: (page: number) => void;
};

export default function ProtectedPage({
  page,
  chapterToken,
  refreshChapterToken,
  fetchEnabled,
  retainDecoded,
  alt,
  onLoaded,
}: Props) {
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const [preferResponsive, setPreferResponsive] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const decodedKeyRef = useRef<string | null>(null);

  useEffect(() => {
    const media = window.matchMedia('(max-width: 820px)');
    const update = () => {
      // Prefer the 720px derivative only when it is still close to the device's
      // physical-pixel demand. High-DPR phones keep the 1080px primary asset so
      // text/line-art quality is not traded away merely because the CSS viewport
      // is narrow. The 15% tolerance avoids needless 1080px downloads around the
      // common 360-412 CSS-pixel / DPR=2 range.
      const responsiveWidth = Number(page.responsive_width || 0);
      const devicePixels = window.innerWidth * Math.max(1, window.devicePixelRatio || 1);
      setPreferResponsive(
        media.matches &&
        responsiveWidth > 0 &&
        devicePixels <= responsiveWidth * 1.15
      );
    };
    update();
    media.addEventListener?.('change', update);
    window.addEventListener('resize', update, { passive: true });
    return () => {
      media.removeEventListener?.('change', update);
      window.removeEventListener('resize', update);
    };
  }, [page.responsive_width]);

  const selectedAsset = useMemo(() => {
    if (preferResponsive && page.responsive_image_path && page.responsive_width && page.responsive_height) {
      return {
        path: page.responsive_image_path,
        width: page.responsive_width,
        height: page.responsive_height,
      };
    }
    return { path: page.image_path, width: page.width, height: page.height };
  }, [page, preferResponsive]);

  const encoding = useMemo(() => {
    if (
      page.encoding_version !== 4 ||
      !selectedAsset.width ||
      !selectedAsset.height ||
      !page.encoding_rows ||
      !page.encoding_columns ||
      !page.encoding_seed
    ) return null;
    return {
      version: page.encoding_version,
      width: selectedAsset.width,
      height: selectedAsset.height,
      rows: page.encoding_rows,
      columns: page.encoding_columns,
      seed: page.encoding_seed,
      pageNumber: page.page_number,
    };
  }, [page, selectedAsset]);

  useEffect(() => {
    if (retainDecoded) return;
    decodedKeyRef.current = null;
    setReady(false);
    setError(null);
    const canvas = canvasRef.current;
    if (canvas) {
      canvas.width = 1;
      canvas.height = 1;
    }
  }, [retainDecoded]);

  useEffect(() => {
    if (!fetchEnabled || !retainDecoded) return;
    if (!encoding) {
      setError('Protected page metadata is incomplete.');
      return;
    }
    // A chapter-token refresh must not re-download pages already decoded in
    // the retention window. Only an asset/path change or explicit retry does.
    const decodeKey = `${selectedAsset.path}:${retryKey}`;
    if (decodedKeyRef.current === decodeKey) return;

    const controller = new AbortController();
    let cancelled = false;

    const run = async () => {
      setReady(false);
      setError(null);
      try {
        let activeToken = chapterToken;
        const persistentCacheEnabled = page.encoding_version === 4 && Boolean(activeToken);
        let servedFromPersistentCache = false;

        const requestAsset = async (token: string): Promise<Response> => {
          // The manifest/current chapter grant is still mandatory. Once that
          // authorization exists, immutable encoded bytes may be reused from a
          // token-independent browser cache across grant rotation/reloads.
          if (persistentCacheEnabled && token) {
            const cached = await readProtectedAssetCache(selectedAsset.path);
            if (cached) {
              servedFromPersistentCache = true;
              return cached;
            }
          }

          const assetUrl = protectedAssetUrl(selectedAsset.path, token);
          const absolute = new URL(assetUrl, window.location.href);
          return fetch(assetUrl, {
            // A dedicated Gcore/other image hostname cannot rely on the website's
            // host-only cookie. The signed chapter grant remains mandatory on a
            // persistent-cache miss. image-edge also validates the grant before
            // serving its own token-independent shared-cache hit.
            credentials: runtimeConfig.imageCdnSendCredentials || absolute.origin === window.location.origin ? 'include' : 'omit',
            cache: page.encoding_version === 4 ? 'default' : 'no-store',
            signal: controller.signal,
          });
        };
        let response = await requestAsset(activeToken);

        if (response.status === 403 && !servedFromPersistentCache) {
          activeToken = await refreshChapterToken();
          response = await requestAsset(activeToken);
        }
        if (!response.ok) throw new Error(`Protected page request failed (${response.status}).`);

        const contentLength = Number(response.headers.get('content-length') || 0);
        if (Number.isFinite(contentLength) && contentLength > 32 * 1024 * 1024) {
          if (servedFromPersistentCache) await evictProtectedAssetCacheEntry(selectedAsset.path);
          throw new Error('Protected page payload exceeds the browser safety limit.');
        }

        const scrambled = await response.blob();
        if (scrambled.size <= 0) {
          if (servedFromPersistentCache) await evictProtectedAssetCacheEntry(selectedAsset.path);
          throw new Error('Protected page response was empty.');
        }
        if (scrambled.size > 32 * 1024 * 1024) {
          if (servedFromPersistentCache) await evictProtectedAssetCacheEntry(selectedAsset.path);
          throw new Error('Protected page payload exceeds the browser safety limit.');
        }

        if (persistentCacheEnabled && !servedFromPersistentCache) {
          // Store only after the transport payload has passed the browser safety
          // checks. CacheStorage is best-effort; this write never blocks reading.
          void writeProtectedAssetCache(selectedAsset.path, scrambled, response.headers);
        }

        let decoded: DecodedProtectedPage;
        try {
          decoded = await decodeProtectedPage(scrambled, encoding);
        } catch (decodeError) {
          // If browser storage ever contains a truncated/corrupt entry (quota or
          // crash edge case), make Retry force the normal authorized network path.
          if (servedFromPersistentCache) await evictProtectedAssetCacheEntry(selectedAsset.path);
          throw decodeError;
        }
        if (cancelled) {
          decoded.bitmap.close();
          return;
        }

        const target = canvasRef.current;
        if (!target) {
          decoded.bitmap.close();
          return;
        }
        target.width = decoded.width;
        target.height = decoded.height;

        const bitmapCtx = target.getContext('bitmaprenderer');
        if (bitmapCtx) {
          bitmapCtx.transferFromImageBitmap(decoded.bitmap);
        } else {
          const ctx = target.getContext('2d', { alpha: false });
          if (!ctx) {
            decoded.bitmap.close();
            throw new Error('Could not create reader canvas.');
          }
          ctx.imageSmoothingEnabled = false;
          ctx.drawImage(decoded.bitmap, 0, 0);
          decoded.bitmap.close();
        }
        decodedKeyRef.current = decodeKey;
        setReady(true);
        onLoaded?.(page.page_number);
      } catch (cause) {
        if (cancelled || (cause instanceof DOMException && cause.name === 'AbortError')) return;
        console.error('Protected page load failed', cause);
        setError('Could not load this page.');
      }
    };

    void run();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [fetchEnabled, retainDecoded, encoding, selectedAsset.path, page.page_number, page.encoding_version, chapterToken, refreshChapterToken, retryKey, onLoaded]);

  const ratio = page.width && page.height ? `${page.width}/${page.height}` : undefined;

  return (
    <div
      className="relative w-full flex items-center justify-center bg-ink-950 overflow-hidden"
      style={ratio ? { aspectRatio: ratio } : { minHeight: 400 }}
      aria-label={alt}
    >
      <canvas
        ref={canvasRef}
        role="img"
        aria-label={alt}
        className={`block w-full h-auto select-none ${ready ? 'visible' : 'invisible'}`}
      />
      {!ready && error ? (
        <div className="absolute inset-0 px-4 py-10 text-center text-sm text-ink-400 flex flex-col items-center justify-center">
          <p>{error}</p>
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              setRetryKey((value) => value + 1);
            }}
            className="mt-3 rounded-lg bg-ink-800 px-3 py-2 text-ink-100 hover:bg-ink-700"
          >
            Retry page
          </button>
        </div>
      ) : !ready ? (
        <div className="absolute inset-0 skeleton w-full h-full min-h-[180px] flex items-center justify-center">
          {fetchEnabled ? `Loading page ${page.page_number}…` : `Page ${page.page_number}`}
        </div>
      ) : null}
    </div>
  );
}
