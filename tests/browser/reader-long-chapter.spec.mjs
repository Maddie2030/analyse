import { test, expect, request as playwrightRequest } from '@playwright/test';
import pg from 'pg';
import crypto from 'node:crypto';
import { makeReaderLongChapterZip } from './fixture-factory.mjs';

const { Client } = pg;
const baseURL = process.env.MREADER_BROWSER_BASE_URL || 'http://gateway';
const adminBaseURL = process.env.MREADER_BROWSER_ADMIN_BASE_URL || 'http://admin-gateway';
const databaseURL = (process.env.MREADER_BROWSER_DATABASE_URL || 'postgresql://manhwa:manhwa@db:5432/manhwa')
  .replace(/^postgresql\+[^:]+:\/\//, 'postgresql://');
const adminUsername = process.env.MREADER_BROWSER_ADMIN_USERNAME || 'mreader_test_admin';
const adminEmail = process.env.MREADER_BROWSER_ADMIN_EMAIL || 'mreader.diagnostics.admin@gmail.com';
const adminPassword = process.env.MREADER_BROWSER_ADMIN_PASSWORD || 'MReaderTest123!';

async function ensureAdmin(api, db) {
  await db.query('DELETE FROM users WHERE username=$1 OR email=$2', [adminUsername, adminEmail]);
  const registered = await api.post('/api/auth/register', {
    data: {
      username: adminUsername,
      email: adminEmail,
      password: adminPassword,
      turnstile_token: '',
    },
  });
  expect(registered.status()).toBe(201);
  await db.query("UPDATE users SET role='admin', updated_at=NOW() WHERE username=$1", [adminUsername]);
  await api.post('/api/auth/logout');
  const login = await api.post('/api/auth/login', {
    data: {
      username_or_email: adminUsername,
      password: adminPassword,
      turnstile_token: '',
    },
  });
  expect(login.status()).toBe(200);
  expect((await login.json()).role).toBe('admin');
}

async function waitForCanvas(page, pageIndex) {
  const wrapper = page.locator(`[data-page-index="${pageIndex}"]`);
  await wrapper.scrollIntoViewIfNeeded();
  await wrapper.evaluate((node) => node.scrollIntoView({ block: 'center', behavior: 'instant' }));
  const canvas = wrapper.locator('canvas');
  await expect.poll(async () => canvas.evaluate((el) => ({ w: el.width, h: el.height, visible: getComputedStyle(el).visibility })), {
    timeout: 30_000,
    intervals: [100, 250, 500, 1000],
  }).toMatchObject({ visible: 'visible' });
  const dimensions = await canvas.evaluate((el) => ({ width: el.width, height: el.height }));
  expect(dimensions.width).toBeGreaterThan(1);
  expect(dimensions.height).toBeGreaterThan(1);
  return dimensions;
}

test('published protected long chapter renders every page while scrolling forward and backward', async ({ page }) => {
  const api = await playwrightRequest.newContext({ baseURL: adminBaseURL });
  const db = new Client({ connectionString: databaseURL });
  await db.connect();
  const suffix = crypto.randomBytes(5).toString('hex');
  const slug = `browser-reader-${suffix}`;
  let seriesId = null;
  const badImageResponses = [];
  const pageErrors = [];
  const imageNetworkRequests = [];
  const chapterManifests = [];

  page.on('request', (request) => {
    if (request.url().includes('/images/')) imageNetworkRequests.push(request.url());
  });
  page.on('response', async (response) => {
    if (response.url().includes('/images/') && response.status() >= 400) {
      badImageResponses.push({ url: response.url(), status: response.status() });
    }
    try {
      const parsed = new URL(response.url());
      if (
        response.request().method() === 'GET' &&
        parsed.pathname === `/api/reader/${slug}/ch-1` &&
        response.status() === 200
      ) {
        chapterManifests.push(await response.json());
      }
    } catch {}
  });
  page.on('pageerror', (error) => pageErrors.push(String(error)));

  try {
    await ensureAdmin(api, db);
    const created = await api.post('/api/catalog/series', {
      data: {
        title: `Browser Reader Regression ${suffix}`,
        slug,
        description: 'Disposable Playwright long-chapter fixture',
        status: 'ongoing',
        genre_ids: [],
        tag_names: ['BROWSER-REGRESSION'],
      },
    });
    expect(created.status()).toBe(201);
    seriesId = (await created.json()).id;

    const upload = await api.post(`/api/upload/upload/${slug}/ch-1`, {
      multipart: {
        file: {
          name: 'reader-long-chapter.zip',
          mimeType: 'application/zip',
          buffer: makeReaderLongChapterZip(),
        },
        chapter_number: '1',
        title: 'Long Browser Regression Chapter',
      },
      timeout: 120_000,
    });
    if (upload.status() !== 201) {
      throw new Error(`chapter upload failed (${upload.status()}): ${await upload.text()}`);
    }
    const uploadBody = await upload.json();
    expect(uploadBody.page_count).toBe(10);

    await page.goto(`${baseURL}/read/${slug}/ch-1`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    await expect(page.locator('[data-page-index="0"]')).toBeVisible({ timeout: 30_000 });

    const firstDimensions = await waitForCanvas(page, 0);
    for (let index = 1; index < 10; index += 1) {
      const dims = await waitForCanvas(page, index);
      expect(dims.width).toBeGreaterThan(1);
      expect(dims.height).toBeGreaterThan(1);
    }

    // Regression for decoded-page eviction/re-entry. The first canvas may have
    // been collapsed to 1x1 while far away, but revisiting it must reliably
    // rehydrate from the browser's encoded asset cache and become visible.
    const firstAgain = await waitForCanvas(page, 0);
    expect(firstAgain.width).toBe(firstDimensions.width);
    expect(firstAgain.height).toBe(firstDimensions.height);

    // Cross-session/token-rotation cache regression. The chapter manifest must
    // issue a fresh signed grant after reload, while the immutable encoded bytes
    // for page 1 remain reusable under a token-independent CacheStorage key.
    await expect.poll(() => chapterManifests.length, { timeout: 10_000 }).toBeGreaterThanOrEqual(1);
    const firstManifest = chapterManifests[0];
    const firstPage = firstManifest.pages[0];
    const physicalWidth = 390 * 2;
    const useResponsive = Boolean(
      firstPage.responsive_image_path &&
      firstPage.responsive_width &&
      physicalWidth <= Number(firstPage.responsive_width) * 1.15
    );
    const selectedPageOnePath = useResponsive ? firstPage.responsive_image_path : firstPage.image_path;
    const selectedPageOneUrl = new URL(`/images/${String(selectedPageOnePath).replace(/^\/+/, '')}`, baseURL);

    await expect.poll(
      () => page.evaluate(async (path) => {
        const relative = `/images/${String(path).replace(/^\/+/, '')}`;
        const identity = new URL(relative, window.location.href).href;
        if ('caches' in window) {
          try {
            const cache = await window.caches.open('mreader-protected-assets-v1');
            if (await cache.match(identity)) return true;
          } catch {}
        }
        if (!('indexedDB' in window)) return false;
        return new Promise((resolve) => {
          const open = window.indexedDB.open('mreader-protected-assets-v1', 1);
          open.onerror = () => resolve(false);
          open.onblocked = () => resolve(false);
          open.onupgradeneeded = () => {
            if (!open.result.objectStoreNames.contains('assets')) {
              open.result.createObjectStore('assets', { keyPath: 'key' });
            }
          };
          open.onsuccess = () => {
            const db = open.result;
            try {
              const request = db.transaction('assets', 'readonly').objectStore('assets').get(identity);
              request.onsuccess = () => { db.close(); resolve(Boolean(request.result)); };
              request.onerror = () => { db.close(); resolve(false); };
            } catch {
              db.close();
              resolve(false);
            }
          };
        });
      }, selectedPageOnePath),
      { timeout: 10_000 },
    ).toBe(true);

    const pageOneNetworkCountBeforeReload = imageNetworkRequests.filter((raw) => {
      const parsed = new URL(raw);
      return parsed.origin === selectedPageOneUrl.origin && parsed.pathname === selectedPageOneUrl.pathname;
    }).length;
    expect(pageOneNetworkCountBeforeReload).toBeGreaterThan(0);

    await page.reload({ waitUntil: 'domcontentloaded', timeout: 60_000 });
    await expect(page.locator('[data-page-index="0"]')).toBeVisible({ timeout: 30_000 });
    await expect.poll(() => chapterManifests.length, { timeout: 10_000 }).toBeGreaterThanOrEqual(2);
    expect(chapterManifests[1].chapter_token).toBeTruthy();
    expect(chapterManifests[1].chapter_token).not.toBe(chapterManifests[0].chapter_token);

    const firstAfterGrantRotation = await waitForCanvas(page, 0);
    expect(firstAfterGrantRotation.width).toBe(firstDimensions.width);
    expect(firstAfterGrantRotation.height).toBe(firstDimensions.height);

    const pageOneNetworkCountAfterReload = imageNetworkRequests.filter((raw) => {
      const parsed = new URL(raw);
      return parsed.origin === selectedPageOneUrl.origin && parsed.pathname === selectedPageOneUrl.pathname;
    }).length;
    expect(pageOneNetworkCountAfterReload).toBe(pageOneNetworkCountBeforeReload);

    expect(badImageResponses).toEqual([]);
    expect(pageErrors).toEqual([]);
  } finally {
    if (seriesId) {
      try { await api.delete(`/api/catalog/series/${seriesId}`); } catch {}
    }
    await api.dispose();
    await db.end();
  }
});
