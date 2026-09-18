import { test, expect, request as playwrightRequest } from '@playwright/test';
import pg from 'pg';
import crypto from 'node:crypto';

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
  const registered = await api.post('/api/auth/register', { data: { username: adminUsername, email: adminEmail, password: adminPassword, turnstile_token: '' } });
  expect(registered.status()).toBe(201);
  await db.query("UPDATE users SET role='admin', updated_at=NOW() WHERE username=$1", [adminUsername]);
  await api.post('/api/auth/logout');
  const login = await api.post('/api/auth/login', { data: { username_or_email: adminUsername, password: adminPassword, turnstile_token: '' } });
  expect(login.status()).toBe(200);
}

test('browser user journey covers register, login state, series actions, comments and library', async ({ page }) => {
  const admin = await playwrightRequest.newContext({ baseURL: adminBaseURL });
  const db = new Client({ connectionString: databaseURL });
  await db.connect();
  const suffix = crypto.randomBytes(5).toString('hex');
  const slug = `journey-${suffix}`;
  const username = `journey_${suffix}`;
  const email = `journey.${suffix}@gmail.com`;
  const password = 'JourneyTest123!';
  let seriesId = null;
  let userId = null;
  try {
    await ensureAdmin(admin, db);
    const created = await admin.post('/api/catalog/series', { data: { title: `Journey Series ${suffix}`, slug, description: 'Browser user journey fixture', status: 'ongoing', genre_ids: [], tag_names: ['JOURNEY'] } });
    expect(created.status()).toBe(201);
    seriesId = (await created.json()).id;

    await page.goto(`${userBaseURL}/register`, { waitUntil: 'domcontentloaded' });
    await page.locator('form input[type="text"]').fill(username);
    await page.locator('form input[type="email"]').fill(email);
    await page.locator('form input[type="password"]').fill(password);
    await page.getByRole('button', { name: 'Create account' }).click();
    await expect(page).toHaveURL(`${userBaseURL}/`);
    const profile = await page.request.get(`${userBaseURL}/api/auth/profile`);
    expect(profile.status()).toBe(200);
    userId = (await profile.json()).id;

    await page.goto(`${userBaseURL}/series/${slug}`, { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: `Journey Series ${suffix}` })).toBeVisible();
    const bookmark = page.getByRole('button', { name: /^Bookmark$/ });
    await expect(bookmark).toBeVisible();
    await bookmark.click();
    await expect(page.getByRole('button', { name: 'Bookmarked' })).toBeVisible();
    await page.getByRole('button', { name: /^Subscribe$/ }).click();
    await expect(page.getByRole('button', { name: 'Subscribed' })).toBeVisible();
    await page.getByRole('button', { name: 'Rate 4 stars' }).click();
    await expect(page.getByText('Your rating: 4/5')).toBeVisible();

    const comment = `Browser journey comment ${suffix}`;
    await page.getByPlaceholder('Share your thoughts...').fill(comment);
    await page.getByRole('button', { name: /Post$/ }).click();
    await expect(page.getByText(comment)).toBeVisible({ timeout: 20_000 });

    await page.goto(`${userBaseURL}/library`, { waitUntil: 'domcontentloaded' });
    await expect(page.getByText(`Journey Series ${suffix}`).first()).toBeVisible({ timeout: 20_000 });

    // Exercise the actual Logout UI and actual Login form rather than only API sessions.
    const logout = page.getByRole('button', { name: /Logout/ }).first();
    if (await logout.isVisible()) await logout.click();
    else {
      await page.getByRole('button', { name: 'Open menu' }).click();
      await page.getByRole('button', { name: /Logout/ }).click();
    }
    await page.goto(`${userBaseURL}/login`, { waitUntil: 'domcontentloaded' });
    await page.locator('form input[type="text"]').fill(username);
    await page.locator('form input[type="password"]').fill(password);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page).toHaveURL(`${userBaseURL}/`);
    await page.goto(`${userBaseURL}/profile`, { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'Profile' })).toBeVisible();
    await expect(page.locator('input[type="text"][readonly]')).toHaveValue(username);
    await expect(page.locator('input[type="email"][readonly]')).toHaveValue(email);
  } finally {
    if (seriesId) { try { await admin.delete(`/api/catalog/series/${seriesId}`); } catch {} }
    if (userId) { try { await db.query('DELETE FROM users WHERE id=$1::uuid', [userId]); } catch {} }
    await admin.dispose();
    await db.end();
  }
});
