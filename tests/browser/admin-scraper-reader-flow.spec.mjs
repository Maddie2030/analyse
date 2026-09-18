import { test, expect, request as playwrightRequest } from '@playwright/test';
import pg from 'pg';
import crypto from 'node:crypto';
import { makePng } from './fixture-factory.mjs';

const { Client } = pg;
const userBaseURL = process.env.MREADER_BROWSER_BASE_URL || 'http://gateway';
const adminBaseURL = process.env.MREADER_BROWSER_ADMIN_BASE_URL || 'http://admin-gateway';
const databaseURL = (process.env.MREADER_BROWSER_DATABASE_URL || 'postgresql://manhwa:manhwa@db:5432/manhwa')
  .replace(/^postgresql\+[^:]+:\/\//, 'postgresql://');
const adminUsername = process.env.MREADER_BROWSER_ADMIN_USERNAME || 'mreader_test_admin';
const adminEmail = process.env.MREADER_BROWSER_ADMIN_EMAIL || 'mreader.diagnostics.admin@gmail.com';
const adminPassword = process.env.MREADER_BROWSER_ADMIN_PASSWORD || 'MReaderTest123!';

async function ensureAdmin(api, db) {
  await db.query('DELETE FROM users WHERE username=$1 OR email=$2', [adminUsername, adminEmail]);
  const registered = await api.post('/api/auth/register', {
    data: { username: adminUsername, email: adminEmail, password: adminPassword, turnstile_token: '' },
  });
  expect(registered.status()).toBe(201);
  await db.query("UPDATE users SET role='admin', updated_at=NOW() WHERE username=$1", [adminUsername]);
  await api.post('/api/auth/logout');
  const login = await api.post('/api/auth/login', {
    data: { username_or_email: adminUsername, password: adminPassword, turnstile_token: '' },
  });
  expect(login.status()).toBe(200);
  expect((await login.json()).role).toBe('admin');
}

async function waitForBatch(api, batchId) {
  const deadline = Date.now() + 180_000;
  while (Date.now() < deadline) {
    const response = await api.get(`/api/scraper/batches/${batchId}`);
    expect(response.status()).toBe(200);
    const body = await response.json();
    const item = body.items?.[0];
    if (item && ['completed', 'failed_error', 'failed_conflict'].includes(item.status)) return { body, item };
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`batch ${batchId} did not finish within 180s`);
}

test('admin batch staging publishes a chapter that is immediately readable through the user plane', async ({ page }) => {
  const admin = await playwrightRequest.newContext({ baseURL: adminBaseURL });
  const db = new Client({ connectionString: databaseURL });
  await db.connect();
  const suffix = crypto.randomBytes(5).toString('hex');
  const slug = `e2e-batch-${suffix}`;
  let seriesId = null;

  try {
    await ensureAdmin(admin, db);
    const created = await admin.post('/api/catalog/series', {
      data: {
        title: `E2E Batch ${suffix}`,
        slug,
        description: 'Disposable admin -> scraper -> worker -> reader browser fixture',
        status: 'ongoing',
        genre_ids: [],
        tag_names: ['E2E'],
      },
    });
    expect(created.status()).toBe(201);
    seriesId = (await created.json()).id;

    const batch = await admin.post('/api/scraper/batches', {
      multipart: {
        series_id: seriesId,
        files: { name: '001.png', mimeType: 'image/png', buffer: makePng(640, 960, 1) },
        relative_paths: 'ch-1/001.png',
      },
      timeout: 60_000,
    });
    expect(batch.status()).toBe(200);
    const batchBody = await batch.json();
    expect(batchBody.items).toHaveLength(1);
    expect(batchBody.items[0].status).toBe('queued');

    const finished = await waitForBatch(admin, batchBody.id);
    expect(finished.item.status).toBe('completed');
    expect(finished.item.published_chapter_id).toBeTruthy();

    const catalog = await page.request.get(`${userBaseURL}/api/catalog/series/${slug}`);
    expect(catalog.status()).toBe(200);
    expect((await catalog.json()).chapters.some((chapter) => chapter.slug === 'ch-1')).toBe(true);

    await page.goto(`${userBaseURL}/read/${slug}/ch-1`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    const wrapper = page.locator('[data-page-index="0"]');
    await expect(wrapper).toBeVisible({ timeout: 30_000 });
    const canvas = wrapper.locator('canvas');
    await expect.poll(async () => canvas.evaluate((node) => ({ width: node.width, height: node.height })), {
      timeout: 30_000,
      intervals: [100, 250, 500, 1000],
    }).toMatchObject({ width: expect.any(Number), height: expect.any(Number) });
    const dimensions = await canvas.evaluate((node) => ({ width: node.width, height: node.height }));
    expect(dimensions.width).toBeGreaterThan(1);
    expect(dimensions.height).toBeGreaterThan(1);
  } finally {
    if (seriesId) {
      try { await admin.delete(`/api/catalog/series/${seriesId}`); } catch {}
    }
    await admin.dispose();
    await db.end();
  }
});
