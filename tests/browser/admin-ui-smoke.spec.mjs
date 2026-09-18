import { test, expect, request as playwrightRequest } from '@playwright/test';
import pg from 'pg';

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

async function openAndAssertHeading(page, path, heading) {
  const response = await page.goto(`${adminBaseURL}${path}`, {
    waitUntil: 'domcontentloaded',
    timeout: 60_000,
  });
  expect(response?.status() ?? 200).toBeLessThan(500);
  await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(page).toHaveURL(`${adminBaseURL}${path}`);
}

test('admin frontend login and core routes render on the admin plane', async ({ page }) => {
  const adminApi = await playwrightRequest.newContext({ baseURL: adminBaseURL });
  const db = new Client({ connectionString: databaseURL });
  await db.connect();

  try {
    await ensureAdmin(adminApi, db);

    // Authenticate through the actual React login form so this test exercises
    // browser cookie/session handling instead of borrowing an API context.
    await page.goto(`${adminBaseURL}/login`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    await page.locator('form input[type="text"]').fill(adminUsername);
    await page.locator('form input[type="password"]').fill(adminPassword);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page).toHaveURL(`${adminBaseURL}/`, { timeout: 30_000 });

    const profile = await page.request.get(`${adminBaseURL}/api/auth/profile`);
    expect(profile.status()).toBe(200);
    expect((await profile.json()).role).toBe('admin');

    await openAndAssertHeading(page, '/admin', 'Admin Dashboard');
    await openAndAssertHeading(page, '/admin/upload', 'Upload Chapter');
    await openAndAssertHeading(page, '/admin/storage', 'Chapter Storage Exports');
    await openAndAssertHeading(page, '/admin/database', 'Database Protection');
    await expect(page.getByText('Local recovery storage', { exact: true })).toBeVisible();
    await expect(page.getByText('Recovery engine')).toBeVisible();
    await expect(page.getByText('Directory and filename details remain backend-only.')).toBeVisible();
    await expect(page.getByText(/recovery points indexed/)).toBeVisible();
    await openAndAssertHeading(page, '/admin/curation', 'Browse Curation');
    await openAndAssertHeading(page, '/admin/scraper', 'Scraper — Attach Chapter');
    await openAndAssertHeading(page, '/admin/scraper/new-series', 'Scrape New Series');
    await openAndAssertHeading(page, '/admin/scraper/operations', 'Scrape Operations');

    // The public/user plane must not accidentally expose the admin frontend.
    await page.goto(`${userBaseURL}/admin`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    await expect(page).toHaveURL(`${userBaseURL}/`);
    await expect(page.getByRole('heading', { name: 'Admin Dashboard', exact: true })).toHaveCount(0);
  } finally {
    await adminApi.dispose();
    await db.end();
  }
});

test('admin frontend redirects an authenticated non-admin user away from admin routes', async ({ page }) => {
  const api = await playwrightRequest.newContext({ baseURL: adminBaseURL });
  const db = new Client({ connectionString: databaseURL });
  await db.connect();
  const suffix = Math.random().toString(16).slice(2, 12);
  const username = `admin_guard_${suffix}`;
  const email = `admin.guard.${suffix}@gmail.com`;
  let userId = null;

  try {
    const registered = await api.post('/api/auth/register', {
      data: { username, email, password: adminPassword, turnstile_token: '' },
    });
    expect(registered.status()).toBe(201);
    userId = (await registered.json()).id;
    await api.post('/api/auth/logout');

    await page.goto(`${adminBaseURL}/login`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    await page.locator('form input[type="text"]').fill(username);
    await page.locator('form input[type="password"]').fill(adminPassword);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page).toHaveURL(`${adminBaseURL}/`, { timeout: 30_000 });

    await page.goto(`${adminBaseURL}/admin`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    await expect(page).toHaveURL(`${adminBaseURL}/`);
    await expect(page.getByRole('heading', { name: 'Admin Dashboard', exact: true })).toHaveCount(0);
  } finally {
    if (userId) {
      try { await db.query('DELETE FROM users WHERE id=$1::uuid', [userId]); } catch {}
    }
    await api.dispose();
    await db.end();
  }
});
