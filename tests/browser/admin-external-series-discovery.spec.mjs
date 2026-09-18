import { test, expect, request as playwrightRequest } from '@playwright/test';
import pg from 'pg';

const { Client } = pg;
const adminBaseURL = process.env.MREADER_BROWSER_ADMIN_BASE_URL || 'http://admin-gateway';
const databaseURL = (process.env.MREADER_BROWSER_DATABASE_URL || 'postgresql://manhwa:manhwa@db:5432/manhwa')
  .replace(/^postgresql\+[^:]+:\/\//, 'postgresql://');
const adminUsername = process.env.MREADER_BROWSER_ADMIN_USERNAME || 'mreader_test_admin';
const adminEmail = process.env.MREADER_BROWSER_ADMIN_EMAIL || 'mreader.diagnostics.admin@gmail.com';
const adminPassword = process.env.MREADER_BROWSER_ADMIN_PASSWORD || 'MReaderTest123!';
const externalSeriesURL = process.env.MREADER_BROWSER_SCRAPER_SERIES_URL || '';

async function ensureAdmin(api, db) {
  await db.query('DELETE FROM users WHERE username=$1 OR email=$2', [adminUsername, adminEmail]);
  const registered = await api.post('/api/auth/register', {
    data: { username: adminUsername, email: adminEmail, password: adminPassword, turnstile_token: '' },
  });
  expect(registered.status()).toBe(201);
  await db.query("UPDATE users SET role='admin', updated_at=NOW() WHERE username=$1", [adminUsername]);
}

async function loginThroughUI(page) {
  await page.goto(`${adminBaseURL}/login`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  await page.locator('form input[type="text"]').fill(adminUsername);
  await page.locator('form input[type="password"]').fill(adminPassword);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(`${adminBaseURL}/`, { timeout: 30_000 });
}

test('admin new-series Analyze button discovers the supplied real series URL', async ({ page }) => {
  test.skip(!externalSeriesURL, 'Set MREADER_BROWSER_SCRAPER_SERIES_URL for live scraper UI qualification.');
  test.setTimeout(240_000);

  const adminApi = await playwrightRequest.newContext({ baseURL: adminBaseURL });
  const db = new Client({ connectionString: databaseURL });
  await db.connect();
  let draftId = null;

  try {
    await ensureAdmin(adminApi, db);
    await loginThroughUI(page);
    await page.goto(`${adminBaseURL}/admin/scraper/new-series`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    await expect(page.getByRole('heading', { name: 'Scrape New Series', exact: true })).toBeVisible();

    await page.getByPlaceholder('https://source.example/series/title').fill(externalSeriesURL);
    await page.getByRole('button', { name: 'Analyze', exact: true }).click();

    const metadataHeading = page.getByRole('heading', { name: '2. Edit series metadata', exact: true });
    await expect(metadataHeading).toBeVisible({ timeout: 180_000 });
    const metadataSection = page.locator('section').filter({ has: metadataHeading });
    await expect(metadataSection.locator('input').first()).not.toHaveValue('', { timeout: 30_000 });

    const current = new URL(page.url());
    draftId = current.searchParams.get('draft');
    expect(draftId).toBeTruthy();
    await expect(page.getByText(/chapter/i).first()).toBeVisible();
  } finally {
    if (draftId) {
      try { await db.query('DELETE FROM scraper_series_draft_chapters WHERE draft_id=$1::uuid', [draftId]); } catch {}
      try { await db.query('DELETE FROM scraper_series_drafts WHERE id=$1::uuid', [draftId]); } catch {}
    }
    await adminApi.dispose();
    await db.end();
  }
});
