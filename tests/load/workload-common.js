import http from 'k6/http';
import ws from 'k6/ws';
import { check } from 'k6';

export const USER = (__ENV.TEST_USER_BASE_URL || 'http://host.docker.internal:8080').replace(/\/$/, '');
export const ADMIN = (__ENV.TEST_ADMIN_BASE_URL || 'http://host.docker.internal:8081').replace(/\/$/, '');
export const SERIES = __ENV.K6_TEST_SERIES_SLUG || 'mreader-k6-load-series';
export const USERNAME = __ENV.K6_TEST_USERNAME || 'mreader_k6_user';
export const PASSWORD = __ENV.K6_TEST_PASSWORD || 'MReaderK6Test123!';
export const ADMIN_USERNAME = __ENV.K6_TEST_ADMIN_USERNAME || 'mreader_k6_admin';
export const ADMIN_PASSWORD = __ENV.K6_TEST_ADMIN_PASSWORD || 'MReaderK6Admin123!';
export const LOGIN_USERNAME = __ENV.K6_TEST_LOGIN_USERNAME || 'mreader_k6_login_user';
export const LOGIN_PASSWORD = __ENV.K6_TEST_LOGIN_PASSWORD || 'MReaderK6Login123!';

const SERIES_WORKLOADS = new Set([
  'catalog_detail', 'catalog_chapter_search', 'reader_manifest', 'reader_image',
  'progress_get', 'progress_put', 'progress_series_state',
  'social_viewer_state', 'social_comments',
]);
const USER_AUTH_WORKLOADS = new Set([
  'auth_profile', 'reader_manifest', 'reader_image',
  'progress_get', 'progress_put', 'progress_series_state',
  'social_viewer_state', 'social_comments', 'realtime_ws',
]);

function cookieHeader(res) {
  const parts = [];
  for (const [name, cookies] of Object.entries(res.cookies || {})) {
    if (cookies && cookies.length && cookies[0].value) parts.push(`${name}=${cookies[0].value}`);
  }
  return parts.join('; ');
}

function login(base, username, password) {
  const res = http.post(`${base}/api/auth/login`, JSON.stringify({
    username_or_email: username,
    password,
    turnstile_token: '',
  }), {
    headers: { 'Content-Type': 'application/json' },
    tags: { setup: 'login' },
    responseCallback: http.expectedStatuses(200),
  });
  if (res.status !== 200) throw new Error(`setup login failed for ${username}: ${res.status} ${String(res.body).slice(0, 300)}`);
  const cookie = cookieHeader(res);
  if (!cookie) throw new Error(`setup login for ${username} returned no session cookie`);
  return cookie;
}

function headers(cookie, json = false) {
  const h = {};
  if (cookie) h.Cookie = cookie;
  if (json) h['Content-Type'] = 'application/json';
  return h;
}

export function isConnectionWorkload(workload) {
  return workload === 'realtime_ws';
}

export function setupWorkload(workload) {
  let seriesId = '';
  if (SERIES_WORKLOADS.has(workload)) {
    const detail = http.get(`${USER}/api/catalog/series/${SERIES}`, { responseCallback: http.expectedStatuses(200) });
    if (detail.status !== 200) throw new Error(`seeded series unavailable for ${workload}: ${detail.status}`);
    const seriesBody = detail.json();
    seriesId = seriesBody.id;
    if (!seriesId) throw new Error('seeded series detail has no id');
  }

  let userCookie = '';
  let adminCookie = '';
  if (USER_AUTH_WORKLOADS.has(workload)) userCookie = login(USER, USERNAME, PASSWORD);
  if (workload === 'admin_scraper_operations') adminCookie = login(ADMIN, ADMIN_USERNAME, ADMIN_PASSWORD);

  let imagePath = '';
  let imageToken = '';
  if (workload === 'reader_image') {
    const manifest = http.get(`${USER}/api/reader/${SERIES}/ch-1`, {
      headers: userCookie ? { Cookie: userCookie } : {},
      responseCallback: http.expectedStatuses(200),
    });
    if (manifest.status !== 200) throw new Error(`reader image setup manifest failed: ${manifest.status}`);
    const body = manifest.json();
    const page = body.pages && body.pages[0];
    imagePath = page && page.image_path;
    imageToken = body.chapter_token;
    if (!imagePath || !imageToken) throw new Error('reader image setup did not return image_path/chapter_token');
  }
  return { seriesId, userCookie, adminCookie, imagePath, imageToken };
}

function requestExpected(workload, res, statuses, observe, phase) {
  const ok = statuses.includes(res.status);
  observe({ workload, phase, type: 'http', res, ok, status: res.status });
  check(res, { [`${workload} ${phase} expected status`]: () => ok });
}

export function runWorkload(workload, data, observe, phase = 'main', holdSeconds = 5) {
  switch (workload) {
    case 'gateway_health': {
      const res = http.get(`${USER}/healthz`, { tags: { name: workload, phase }, responseCallback: http.expectedStatuses(200) });
      requestExpected(workload, res, [200], observe, phase); return;
    }
    case 'auth_login': {
      const res = http.post(`${USER}/api/auth/login`, JSON.stringify({ username_or_email: LOGIN_USERNAME, password: LOGIN_PASSWORD, turnstile_token: '' }), {
        headers: { 'Content-Type': 'application/json' }, tags: { name: workload, phase }, responseCallback: http.expectedStatuses(200),
      });
      requestExpected(workload, res, [200], observe, phase); return;
    }
    case 'auth_profile': {
      const res = http.get(`${USER}/api/auth/profile`, { headers: headers(data.userCookie), tags: { name: workload, phase }, responseCallback: http.expectedStatuses(200) });
      requestExpected(workload, res, [200], observe, phase); return;
    }
    case 'catalog_discover': case 'catalog_list': case 'catalog_detail': case 'catalog_chapter_search': {
      const path = workload === 'catalog_discover' ? '/api/catalog/discover' : workload === 'catalog_list' ? '/api/catalog/series?limit=20' : workload === 'catalog_detail' ? `/api/catalog/series/${SERIES}` : `/api/catalog/series/${SERIES}?chapter_search=3&chapter_limit=20`;
      const res = http.get(`${USER}${path}`, { tags: { name: workload, phase }, responseCallback: http.expectedStatuses(200) });
      requestExpected(workload, res, [200], observe, phase); return;
    }
    case 'reader_manifest': {
      const res = http.get(`${USER}/api/reader/${SERIES}/ch-1`, { headers: headers(data.userCookie), tags: { name: workload, phase }, responseCallback: http.expectedStatuses(200) });
      requestExpected(workload, res, [200], observe, phase); return;
    }
    case 'reader_image': {
      const res = http.get(`${USER}/images/${data.imagePath}?token=${encodeURIComponent(data.imageToken)}`, { headers: headers(data.userCookie), tags: { name: workload, phase }, responseCallback: http.expectedStatuses(200) });
      requestExpected(workload, res, [200], observe, phase); return;
    }
    case 'progress_get': {
      const res = http.get(`${USER}/api/progress/${SERIES}/ch-1`, { headers: headers(data.userCookie), tags: { name: workload, phase }, responseCallback: http.expectedStatuses(200, 404) });
      requestExpected(workload, res, [200, 404], observe, phase); return;
    }
    case 'progress_commit': {
      const res = http.post(`${USER}/api/progress/${SERIES}/ch-1/commit`, JSON.stringify({ last_page: 2, scroll_position: 0.5 }), { headers: headers(data.userCookie, true), tags: { name: workload, phase }, responseCallback: http.expectedStatuses(200) });
      requestExpected(workload, res, [200], observe, phase); return;
    }
    case 'progress_series_state': {
      const res = http.get(`${USER}/api/progress/series/${SERIES}/state`, { headers: headers(data.userCookie), tags: { name: workload, phase }, responseCallback: http.expectedStatuses(200) });
      requestExpected(workload, res, [200], observe, phase); return;
    }
    case 'social_viewer_state': {
      const res = http.get(`${USER}/api/social/series/${data.seriesId}/viewer-state`, { headers: headers(data.userCookie), tags: { name: workload, phase }, responseCallback: http.expectedStatuses(200) });
      requestExpected(workload, res, [200], observe, phase); return;
    }
    case 'social_comments': {
      const res = http.get(`${USER}/api/social/comments?seriesId=${encodeURIComponent(data.seriesId)}&limit=20`, { headers: headers(data.userCookie), tags: { name: workload, phase }, responseCallback: http.expectedStatuses(200) });
      requestExpected(workload, res, [200], observe, phase); return;
    }
    case 'admin_scraper_operations': {
      const res = http.get(`${ADMIN}/api/scraper/operations?state=all&limit=10`, { headers: headers(data.adminCookie), tags: { name: workload, phase }, responseCallback: http.expectedStatuses(200) });
      requestExpected(workload, res, [200], observe, phase); return;
    }
    case 'realtime_ws': {
      const wsUrl = USER.replace(/^http/, 'ws') + '/api/realtime/ws';
      const started = Date.now(); let opened = false;
      const res = ws.connect(wsUrl, { headers: headers(data.userCookie), tags: { name: workload, phase } }, (socket) => {
        socket.on('open', () => { opened = true; });
        socket.setTimeout(() => socket.close(), Math.max(2, holdSeconds) * 1000);
      });
      const ok = opened && res && res.status === 101;
      observe({ workload, phase, type: 'ws', res, ok, status: res && res.status, duration: Date.now() - started });
      check(res, { [`${workload} ${phase} websocket established`]: () => ok }); return;
    }
    default: throw new Error(`unknown workload=${workload}`);
  }
}
