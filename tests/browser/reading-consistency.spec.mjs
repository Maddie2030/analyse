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
const userPassword = process.env.MREADER_BROWSER_USER_PASSWORD || 'MReaderTest123!';

async function ensureAdmin(api, db) {
  await db.query('DELETE FROM users WHERE username=$1 OR email=$2', [adminUsername, adminEmail]);
  const registered = await api.post('/api/auth/register', { data: { username: adminUsername, email: adminEmail, password: adminPassword, turnstile_token: '' } });
  expect(registered.status()).toBe(201);
  await db.query("UPDATE users SET role='admin', updated_at=NOW() WHERE username=$1", [adminUsername]);
  await api.post('/api/auth/logout');
  const login = await api.post('/api/auth/login', { data: { username_or_email: adminUsername, password: adminPassword, turnstile_token: '' } });
  expect(login.status()).toBe(200);
}

async function createReaderFixture(admin, suffix) {
  const slug = `reading-consistency-${suffix}`;
  const created = await admin.post('/api/catalog/series', { data: {
    title: `Reading Consistency ${suffix}`, slug, description: 'Disposable P03.2 browser reading fixture',
    status: 'ongoing', genre_ids: [], tag_names: ['P03-BROWSER'],
  } });
  expect(created.status()).toBe(201);
  const seriesId = (await created.json()).id;
  const upload = await admin.post(`/api/upload/upload/${slug}/ch-1`, { multipart: {
    file: { name: 'reading-consistency.zip', mimeType: 'application/zip', buffer: makeReaderLongChapterZip() },
    chapter_number: '1', title: 'P03 Browser Reading Chapter',
  }, timeout: 120_000 });
  if (upload.status() !== 201) throw new Error(`reader fixture upload failed (${upload.status()}): ${await upload.text()}`);
  expect((await upload.json()).page_count).toBe(10);
  return { slug, seriesId };
}

async function registerReader(page, suffix) {
  const response = await page.request.post(`${baseURL}/api/auth/register`, { data: {
    username: `reader_${suffix}`, email: `reader.${suffix}@gmail.com`, password: userPassword, turnstile_token: '',
  } });
  if (response.status() !== 201) throw new Error(`reader registration failed (${response.status()}): ${await response.text()}`);
  return response.json();
}

async function openReader(page, slug) {
  await page.goto(`${baseURL}/read/${slug}/ch-1`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  await expect(page.locator('[data-page-index="0"]')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole('status')).not.toContainText('Preparing reading sync', { timeout: 30_000 });
}

async function scrollToReaderPage(page, index) {
  const wrapper = page.locator(`[data-page-index="${index}"]`);
  await wrapper.scrollIntoViewIfNeeded();
  await wrapper.evaluate((node) => node.scrollIntoView({ block: 'center', behavior: 'instant' }));
  await expect(page.getByText(new RegExp(`Page ${index + 1} / 10`))).toBeVisible({ timeout: 20_000 });
  await page.evaluate(() => window.dispatchEvent(new Event('pagehide')));
}

async function getProgress(page, userId, slug) {
  const response = await page.request.get(`${baseURL}/api/progress/${slug}/ch-1`, { headers: { 'X-MReader-Account-ID': userId } });
  expect(response.status()).toBe(200);
  return response.json();
}

async function waitForServerPage(page, userId, slug, minimum) {
  await expect.poll(async () => Number((await getProgress(page, userId, slug)).last_page || 0), {
    timeout: 30_000, intervals: [100, 250, 500, 1000],
  }).toBeGreaterThanOrEqual(minimum);
}

async function readDurableReadingState(page, userId) {
  return page.evaluate(async (id) => {
    const scope = JSON.stringify([window.location.origin, id]);
    return new Promise((resolve, reject) => {
      const open = indexedDB.open('mreader-reading-v1', 1);
      open.onerror = () => reject(open.error);
      open.onsuccess = () => {
        const db = open.result;
        const request = db.transaction('accounts', 'readonly').objectStore('accounts').get(scope);
        request.onerror = () => { db.close(); reject(request.error); };
        request.onsuccess = () => { const value = request.result; db.close(); resolve(value || null); };
      };
    });
  }, userId);
}

async function setup(page) {
  const admin = await playwrightRequest.newContext({ baseURL: adminBaseURL });
  const db = new Client({ connectionString: databaseURL });
  await db.connect();
  const suffix = crypto.randomBytes(6).toString('hex');
  await ensureAdmin(admin, db);
  const fixture = await createReaderFixture(admin, suffix);
  const user = await registerReader(page, suffix);
  return { admin, db, suffix, user, ...fixture };
}

async function cleanup({ admin, db, seriesId, user }) {
  if (seriesId) { try { await admin.delete(`/api/catalog/series/${seriesId}`); } catch {} }
  if (user?.id) { try { await db.query('DELETE FROM users WHERE id=$1::uuid', [user.id]); } catch {} }
  await admin.dispose();
  await db.end();
}

test('two tabs preserve a shared durable checkpoint when one tab cannot sync', async ({ page, context }) => {
  const env = await setup(page);
  const second = await context.newPage();
  try {
    await openReader(page, env.slug);
    await expect(page.getByRole('status')).toContainText('Reading synced', { timeout: 30_000 });
    await openReader(second, env.slug);
    await expect(second.getByRole('status')).toContainText('Reading synced', { timeout: 30_000 });

    await second.route(/\/api\/progress\/.*\/commit$/, (route) => route.abort('failed'));
    await scrollToReaderPage(second, 6);
    await expect.poll(async () => {
      const state = await readDurableReadingState(page, env.user.id);
      return Object.values(state?.records || {}).some((record) => record.position?.last_page >= 7 && record.dirty);
    }, { timeout: 10_000 }).toBe(true);

    await second.unroute(/\/api\/progress\/.*\/commit$/);
    await second.evaluate(() => window.dispatchEvent(new Event('online')));
    await waitForServerPage(second, env.user.id, env.slug, 7);
  } finally {
    await second.close();
    await cleanup(env);
  }
});

test('quota failure keeps unsaved reading visible and prevents transport', async ({ page }) => {
  const env = await setup(page);
  const progressPosts = [];
  try {
    await page.addInitScript(() => {
      const originalPut = IDBObjectStore.prototype.put;
      IDBObjectStore.prototype.put = function patchedPut(value, key) {
        if (this.name === 'accounts') throw new DOMException('Synthetic quota exhaustion', 'QuotaExceededError');
        return originalPut.call(this, value, key);
      };
    });
    page.on('request', (request) => {
      if (request.method() === 'POST' && /\/api\/progress\/.+\/(open|commit)$/.test(new URL(request.url()).pathname)) {
        progressPosts.push(request.url());
      }
    });

    await openReader(page, env.slug);
    await scrollToReaderPage(page, 4);
    await expect(page.getByRole('status')).toContainText('Local saving unavailable', { timeout: 10_000 });
    await page.waitForTimeout(1_500);
    expect(progressPosts).toEqual([]);
  } finally {
    await cleanup(env);
  }
});

test('offline refresh preserves a pending checkpoint until connectivity returns', async ({ page, context }) => {
  const env = await setup(page);
  try {
    await openReader(page, env.slug);
    await expect(page.getByRole('status')).toContainText('Reading synced', { timeout: 30_000 });
    await context.setOffline(true);
    await scrollToReaderPage(page, 5);

    const before = await readDurableReadingState(page, env.user.id);
    expect(Object.values(before?.records || {}).some((record) => record.position?.last_page >= 6)).toBe(true);

    await page.reload({ waitUntil: 'commit', timeout: 10_000 }).catch(() => null);
    await context.setOffline(false);
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 60_000 });
    await expect(page.locator('[data-page-index="0"]')).toBeVisible({ timeout: 30_000 });
    await expect.poll(async () => {
      const state = await readDurableReadingState(page, env.user.id);
      return Object.values(state?.records || {}).some((record) => record.position?.last_page >= 6);
    }, { timeout: 10_000 }).toBe(true);
    await page.evaluate(() => window.dispatchEvent(new Event('online')));
    await waitForServerPage(page, env.user.id, env.slug, 6);
  } finally {
    await context.setOffline(false);
    await cleanup(env);
  }
});

test('reader IndexedDB checkpoint reaches server progress and Smart Library UI', async ({ page }) => {
  const env = await setup(page);
  try {
    await openReader(page, env.slug);
    await expect(page.getByRole('status')).toContainText('Reading synced', { timeout: 30_000 });
    await scrollToReaderPage(page, 3);

    await expect.poll(async () => {
      const state = await readDurableReadingState(page, env.user.id);
      return Object.values(state?.records || {}).some((record) => record.position?.last_page >= 4);
    }, { timeout: 10_000, intervals: [100, 250, 500] }).toBe(true);

    await waitForServerPage(page, env.user.id, env.slug, 4);

    await expect.poll(async () => {
      const result = await env.db.query(
        'SELECT last_page FROM reading_progress WHERE user_id=$1::uuid AND series_id=$2::uuid',
        [env.user.id, env.seriesId],
      );
      return Number(result.rows[0]?.last_page || 0);
    }, { timeout: 20_000, intervals: [100, 250, 500, 1000] }).toBeGreaterThanOrEqual(4);

    await expect.poll(async () => {
      const result = await env.db.query(
        'SELECT COUNT(*)::int AS count FROM reading_history WHERE user_id=$1::uuid AND series_id=$2::uuid',
        [env.user.id, env.seriesId],
      );
      return Number(result.rows[0]?.count || 0);
    }, { timeout: 20_000, intervals: [100, 250, 500, 1000] }).toBeGreaterThan(0);

    const libraryResponse = await page.request.get(`${baseURL}/api/social/library?scope=history`, {
      headers: { 'X-MReader-Account-ID': env.user.id },
    });
    expect(libraryResponse.status()).toBe(200);
    const library = await libraryResponse.json();
    expect(library.items.some((item) => item.series_id === env.seriesId)).toBe(true);

    await page.goto(`${baseURL}/library`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    await page.getByRole('button', { name: 'History' }).click();
    await expect(page.getByText(`Reading Consistency ${env.suffix}`).first()).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText('Recently opened')).toBeVisible({ timeout: 20_000 });
  } finally {
    await cleanup(env);
  }
});

test('late acknowledgement cannot erase a newer checkpoint produced during transport', async ({ page }) => {
  const env = await setup(page);
  let releaseFirstCommit;
  let firstCommitBody = null;
  let announceCommit;
  const firstCommitStarted = new Promise((resolve) => { announceCommit = resolve; });
  const release = new Promise((resolve) => { releaseFirstCommit = resolve; });
  let held = false;
  try {
    await openReader(page, env.slug);
    await expect(page.getByRole('status')).toContainText('Reading synced', { timeout: 30_000 });

    await page.route(/\/api\/progress\/.*\/commit$/, async (route) => {
      if (held) { await route.continue(); return; }
      held = true;
      firstCommitBody = route.request().postDataJSON();
      announceCommit();
      await release;
      await route.continue();
    });

    await scrollToReaderPage(page, 2);
    await firstCommitStarted;
    expect(Number(firstCommitBody.last_page)).toBeLessThan(8);
    await scrollToReaderPage(page, 7);
    releaseFirstCommit();
    await page.waitForTimeout(500);
    await page.evaluate(() => window.dispatchEvent(new Event('online')));
    await waitForServerPage(page, env.user.id, env.slug, 8);
  } finally {
    releaseFirstCommit?.();
    await page.unroute(/\/api\/progress\/.*\/commit$/).catch(() => {});
    await cleanup(env);
  }
});

test('media failure does not fabricate completion when a protected page never loads', async ({ page }) => {
  const env = await setup(page);
  let failedPath = '';
  try {
    await page.route('**/images/**', async (route) => {
      const pathname = new URL(route.request().url()).pathname;
      if (!failedPath) failedPath = pathname;
      if (pathname === failedPath) { await route.abort('failed'); return; }
      await route.continue();
    });

    await openReader(page, env.slug);
    for (let index = 0; index < 10; index += 1) await scrollToReaderPage(page, index);
    await page.evaluate(() => window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'instant' }));
    await page.waitForTimeout(1_000);
    await page.evaluate(() => window.dispatchEvent(new Event('pagehide')));
    await expect.poll(() => failedPath, { timeout: 10_000 }).not.toBe('');
    await expect.poll(async () => Boolean((await getProgress(page, env.user.id, env.slug)).updated_at), {
      timeout: 30_000, intervals: [100, 250, 500, 1000],
    }).toBe(true);
    const progress = await getProgress(page, env.user.id, env.slug);
    expect(progress.completed).not.toBe(true);
    expect(Number(progress.completed_page || 0)).toBe(0);
  } finally {
    await page.unroute('**/images/**').catch(() => {});
    await cleanup(env);
  }
});
