import { test, expect } from '@playwright/test';
import pg from 'pg';
import crypto from 'node:crypto';

const { Client } = pg;
const baseURL = process.env.MREADER_BROWSER_BASE_URL || 'http://gateway';
const databaseURL = (process.env.MREADER_BROWSER_DATABASE_URL || 'postgresql://manhwa:manhwa@db:5432/manhwa')
  .replace(/^postgresql\+[^:]+:\/\//, 'postgresql://');
const password = process.env.MREADER_BROWSER_USER_PASSWORD || 'MReaderTest123!';

async function registerBrowserUser(page, suffix) {
  const username = `realtime_${suffix}`;
  const email = `mreader.realtime+${suffix}@gmail.com`;
  const response = await page.request.post(`${baseURL}/api/auth/register`, {
    data: { username, email, password, turnstile_token: '' },
  });
  if (response.status() !== 201) {
    throw new Error(`realtime test registration failed (${response.status()}): ${await response.text()}`);
  }
  const user = await response.json();
  const login = await page.request.post(`${baseURL}/api/auth/login`, {
    data: { username_or_email: username, password, turnstile_token: '' },
  });
  if (login.status() !== 200) {
    throw new Error(`realtime test login failed (${login.status()}): ${await login.text()}`);
  }
  return user;
}

async function enqueueChapterPublished(db, { seriesId, chapterId, seriesSlug, chapterSlug, publishedAt }) {
  const payload = {
    chapter_id: chapterId,
    series_id: seriesId,
    chapter_number: 1,
    chapter_slug: chapterSlug,
    series_slug: seriesSlug,
    title: 'Realtime Chapter',
    page_count: 0,
    published_at: publishedAt.toISOString(),
  };
  const result = await db.query(
    `SELECT enqueue_event_outbox_v1(
       'chapter.published', 'chapter.published', 1,
       'chapter', $1, $2, 'browser-realtime-regression',
       $3::jsonb, NULL, NULL,
       '{"source":"browser-realtime-regression"}'::jsonb,
       $4::timestamptz
     )::text AS event_id`,
    [chapterId, seriesId, JSON.stringify(payload), publishedAt.toISOString()],
  );
  return result.rows[0].event_id;
}


async function enqueueNotificationRequested(db, { userId, message, dedupeKey, requestedAt }) {
  const payload = {
    recipient_user_id: userId,
    kind: 'system.regression',
    message,
    series_id: null,
    chapter_id: null,
    dedupe_key: dedupeKey,
    requested_at: requestedAt.toISOString(),
  };
  const result = await db.query(
    `SELECT enqueue_event_outbox_v1(
       'notification.requested', 'notification.requested', 1,
       'user', $1, $1, 'browser-realtime-regression',
       $2::jsonb, NULL, NULL,
       '{"source":"browser-realtime-regression"}'::jsonb,
       $3::timestamptz
     )::text AS event_id`,
    [userId, JSON.stringify(payload), requestedAt.toISOString()],
  );
  return result.rows[0].event_id;
}

async function scalar(db, sql, params = []) {
  const result = await db.query(sql, params);
  return Number(result.rows[0].value);
}

test('RabbitMQ chapter publication creates one durable notification and pushes it over WebSocket', async ({ page }) => {
  const db = new Client({ connectionString: databaseURL });
  await db.connect();
  const suffix = crypto.randomBytes(6).toString('hex');
  const seriesSlug = `realtime-series-${suffix}`;
  const chapterSlug = 'ch-1';
  let userId = null;
  let seriesId = null;
  let chapterId = null;
  const eventIds = [];

  try {
    const user = await registerBrowserUser(page, suffix);
    userId = user.id;

    const series = await db.query(
      `INSERT INTO series(title,slug,status) VALUES ($1,$2,'ongoing') RETURNING id::text`,
      [`Realtime Regression ${suffix}`, seriesSlug],
    );
    seriesId = series.rows[0].id;
    const chapter = await db.query(
      `INSERT INTO chapters(series_id,chapter_number,title,slug,status,page_count)
       VALUES ($1::uuid,1,'Realtime Chapter',$2,'published',0)
       RETURNING id::text`,
      [seriesId, chapterSlug],
    );
    chapterId = chapter.rows[0].id;

    const publishedAt = new Date(Date.now() - 2_000);
    await db.query(
      `INSERT INTO subscriptions(user_id,series_id,created_at)
       VALUES ($1::uuid,$2::uuid,$3::timestamptz)`,
      [userId, seriesId, new Date(publishedAt.getTime() - 1_000).toISOString()],
    );

    // Load the real application so the registration cookie belongs to this
    // browser origin, then open an independently observed WS connection through Caddy.
    await page.goto(`${baseURL}/notifications`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    await page.evaluate(() => {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const state = { ready: false, messages: [], closed: false, closeCode: null, error: false, socket: null };
      const ws = new WebSocket(`${protocol}//${window.location.host}/api/realtime/ws`);
      state.socket = ws;
      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(String(event.data));
          state.messages.push(message);
          if (message.type === 'ready') state.ready = Boolean(message.authenticated);
        } catch {}
      };
      ws.onerror = () => { state.error = true; };
      ws.onclose = (event) => { state.closed = true; state.closeCode = event.code; };
      window.__mreaderRealtimeRegression = state;
    });

    await expect.poll(
      () => page.evaluate(() => Boolean(window.__mreaderRealtimeRegression?.ready)),
      { timeout: 20_000, intervals: [100, 250, 500, 1000] },
    ).toBe(true);

    const eventOne = await enqueueChapterPublished(db, { seriesId, chapterId, seriesSlug, chapterSlug, publishedAt });
    eventIds.push(eventOne);

    await expect.poll(
      () => scalar(db, `SELECT COUNT(*)::int AS value FROM notification_event_receipts WHERE event_id=$1::uuid`, [eventOne]),
      { timeout: 30_000, intervals: [100, 250, 500, 1000] },
    ).toBe(1);
    await expect.poll(
      () => scalar(db, `SELECT COUNT(*)::int AS value FROM notifications WHERE user_id=$1::uuid AND chapter_id=$2::uuid`, [userId, chapterId]),
      { timeout: 30_000, intervals: [100, 250, 500, 1000] },
    ).toBe(1);

    await expect.poll(
      () => page.evaluate(() => (window.__mreaderRealtimeRegression?.messages || []).filter((m) => m.type === 'notification.created').length),
      { timeout: 30_000, intervals: [100, 250, 500, 1000] },
    ).toBe(1);

    const signal = await page.evaluate(() => (
      (window.__mreaderRealtimeRegression?.messages || []).find((m) => m.type === 'notification.created')
    ));
    expect(signal.notification.chapter_id).toBe(chapterId);
    expect(signal.notification.series_id).toBe(seriesId);
    expect(signal.notification.kind).toBe('chapter.published');
    expect(signal.unread_count).toBe(1);

    // A logically equivalent event with a different event_id must be receipted,
    // but the per-user chapter dedupe key must suppress a second notification and
    // therefore suppress a second realtime batch.
    const eventTwo = await enqueueChapterPublished(db, { seriesId, chapterId, seriesSlug, chapterSlug, publishedAt });
    eventIds.push(eventTwo);
    await expect.poll(
      () => scalar(
        db,
        `SELECT COUNT(*)::int AS value FROM notification_event_receipts WHERE event_id = ANY($1::uuid[])`,
        [eventIds],
      ),
      { timeout: 30_000, intervals: [100, 250, 500, 1000] },
    ).toBe(2);
    await expect.poll(
      () => scalar(db, `SELECT COUNT(*)::int AS value FROM notifications WHERE user_id=$1::uuid AND chapter_id=$2::uuid`, [userId, chapterId]),
      { timeout: 10_000, intervals: [100, 250, 500] },
    ).toBe(1);
    await page.waitForTimeout(1_000);
    expect(await page.evaluate(() => (
      (window.__mreaderRealtimeRegression?.messages || []).filter((m) => m.type === 'notification.created').length
    ))).toBe(1);

    expect(await scalar(
      db,
      `SELECT COUNT(*)::int AS value
         FROM event_outbox
        WHERE event_type='notification.batch.created'
          AND causation_id = ANY($1::uuid[])`,
      [eventIds],
    )).toBe(1);


    // Generic notification.requested events are also supported. They may have
    // no series/chapter relation, but must still be visible in the inbox instead
    // of inflating the unread badge while being filtered out of the list.
    const genericMessage = `Realtime system notification ${suffix}`;
    const genericEvent = await enqueueNotificationRequested(db, {
      userId,
      message: genericMessage,
      dedupeKey: `browser-realtime:${suffix}`,
      requestedAt: new Date(),
    });
    eventIds.push(genericEvent);
    await expect.poll(
      () => scalar(db, `SELECT COUNT(*)::int AS value FROM notification_event_receipts WHERE event_id=$1::uuid`, [genericEvent]),
      { timeout: 30_000, intervals: [100, 250, 500, 1000] },
    ).toBe(1);
    await expect.poll(
      () => scalar(db, `SELECT COUNT(*)::int AS value FROM notifications WHERE user_id=$1::uuid AND kind='system.regression'`, [userId]),
      { timeout: 30_000, intervals: [100, 250, 500, 1000] },
    ).toBe(1);
    await expect.poll(
      () => page.evaluate(() => (window.__mreaderRealtimeRegression?.messages || []).filter((m) => m.type === 'notification.created').length),
      { timeout: 30_000, intervals: [100, 250, 500, 1000] },
    ).toBe(2);
    const genericSignal = await page.evaluate(() => (
      (window.__mreaderRealtimeRegression?.messages || []).filter((m) => m.type === 'notification.created').at(-1)
    ));
    expect(genericSignal.notification.kind).toBe('system.regression');
    expect(genericSignal.notification.series_id).toBeNull();
    expect(genericSignal.notification.chapter_id).toBeNull();
    expect(genericSignal.unread_count).toBe(2);
    await expect(page.getByText(genericMessage)).toBeVisible({ timeout: 30_000 });

    // Revoking the Redis-backed login must invalidate an already-open private
    // WebSocket. The diagnostics runner shortens the production 60s recheck
    // interval so this remains a fast deterministic regression.
    const logout = await page.request.post(`${baseURL}/api/auth/logout`);
    expect(logout.status()).toBe(200);
    await expect.poll(
      () => page.evaluate(() => window.__mreaderRealtimeRegression?.closeCode),
      { timeout: 15_000, intervals: [100, 250, 500, 1000] },
    ).toBe(4001);
    await expect.poll(
      () => page.request.get(`${baseURL}/api/auth/profile`).then((response) => response.status()),
      { timeout: 10_000, intervals: [100, 250, 500] },
    ).toBe(401);
  } finally {
    try {
      await page.evaluate(() => {
        try { window.__mreaderRealtimeRegression?.socket?.close(); } catch {}
      });
    } catch {}
    if (eventIds.length) {
      try {
        await db.query(
          `DELETE FROM event_outbox WHERE event_id = ANY($1::uuid[]) OR causation_id = ANY($1::uuid[])`,
          [eventIds],
        );
        await db.query(`DELETE FROM notification_event_receipts WHERE event_id = ANY($1::uuid[])`, [eventIds]);
      } catch {}
    }
    if (seriesId) {
      try { await db.query('DELETE FROM series WHERE id=$1::uuid', [seriesId]); } catch {}
    }
    if (userId) {
      try { await db.query('DELETE FROM users WHERE id=$1::uuid', [userId]); } catch {}
    }
    await db.end();
  }
});
