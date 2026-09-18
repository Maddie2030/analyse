import { readingTransport } from '../reading/transport';
import type { CanonicalReading } from '../reading/model';
const BASE = '';

const READER_VISITOR_KEY = 'mreader_reader_visitor_v1';

function getReaderVisitorId(): string {
  try {
    const existing = window.localStorage.getItem(READER_VISITOR_KEY) || '';
    if (/^[A-Za-z0-9_-]{16,64}$/.test(existing)) return existing;
    const created = globalThis.crypto?.randomUUID?.() || '';
    if (created) window.localStorage.setItem(READER_VISITOR_KEY, created);
    return created;
  } catch {
    return '';
  }
}

export interface BackupManifestItem {
  id: string;
  kind: 'logical_dump' | 'physical_snapshot';
  type: 'automatic' | 'manual' | 'snapshot' | 'pre-upgrade' | 'pre-restore' | string;
  timestamp_utc: string;
  timestamp_local?: string;
  timezone?: string;
  mreader_version?: string;
  postgres_major?: number;
  size_bytes?: number;
  sha256?: string;
  verified?: boolean;
}

export interface DatabaseOperationItem {
  id: string;
  operation_type: 'backup' | 'restore_drill' | 'restore' | string;
  status: 'queued' | 'running' | 'verified' | 'completed' | 'failed' | 'cancelled' | string;
  phase: string;
  backup_id: string | null;
  requested_by_username: string | null;
  requested_at: string;
  started_at: string | null;
  completed_at: string | null;
  message: string;
}

export interface DatabaseProtectionStatus {
  storage: {
    status: string;
    healthy: boolean;
    local_storage_ready: boolean;
    backup_count: number;
    message: string;
    operator_action?: string | null;
  };
  runtime: {
    available: boolean;
    status: 'ready' | 'degraded' | 'offline' | string;
    last_heartbeat_at?: string | null;
    capabilities: {
      local_storage_ready: boolean;
      logical_backup: boolean;
      physical_snapshot: boolean;
      restore_drill: boolean;
      restore: boolean;
    };
    restore_control: {
      installation_fingerprint: string | null;
      restore_generation: number | null;
    };
    message: string;
  };
  policy: {
    timezone: string;
    automatic_window_start: string;
    automatic_window_end: string;
    logical_retention_days: number;
    snapshot_retention_days: number;
  };
  operations: DatabaseOperationItem[];
  backups: BackupManifestItem[];
  backup_page: {
    next_cursor: string | null;
    total: number;
  };
}

export interface ApiError {
  detail?: string | unknown;
  message?: string;
  status?: number;
  code?: string;
  owner?: string;
  request_id?: string;
  operation_id?: string;
  revision?: number;
  retryable?: boolean;
}

function createRequestId(): string {
  return globalThis.crypto?.randomUUID?.() || `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function apiErrorFromResponse(response: Response, data: unknown, outboundRequestId = '', fallbackMessage?: string): ApiError {
  const body = data && typeof data === 'object' ? data as Record<string, unknown> : {};
  const stringField = (name: string): string | undefined => {
    const value = body[name];
    return typeof value === 'string' && value.trim() ? value : undefined;
  };
  const revisionValue = Number(body.revision);
  const retryableValue = body.retryable;
  const detail = body.detail;
  const message = stringField('message') || fallbackMessage;
  return {
    ...body,
    detail: typeof detail === 'string' || detail !== undefined ? detail : message,
    message,
    status: response.status,
    code: stringField('code'),
    owner: stringField('owner') || response.headers.get('X-MReader-Owner') || undefined,
    request_id: stringField('request_id') || response.headers.get('X-Request-ID') || outboundRequestId || undefined,
    operation_id: stringField('operation_id'),
    revision: Number.isFinite(revisionValue) ? revisionValue : undefined,
    retryable: typeof retryableValue === 'boolean' ? retryableValue : undefined,
  } as ApiError;
}

async function apiFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const headers = new Headers(options.headers || {});
  if (!headers.has('X-Request-ID')) {
    headers.set('X-Request-ID', createRequestId());
  }
  return fetch(url, {
    ...options,
    credentials: options.credentials ?? 'include',
    headers,
  });
}

export function apiErrorStatus(error: unknown): number | null {
  if (!error || typeof error !== 'object') return null;
  const status = Number((error as ApiError).status);
  return Number.isFinite(status) ? status : null;
}

export function apiErrorMessage(error: unknown, fallback: string): string {
  if (!error || typeof error !== 'object') return fallback;
  const value = error as ApiError;
  if (typeof value.detail === 'string' && value.detail.trim()) return value.detail;
  if (typeof value.message === 'string' && value.message.trim()) return value.message;
  return fallback;
}

const inflightGetRequests = new Map<string, Promise<unknown>>();
export function resetPersonalRequests() { inflightGetRequests.clear(); }

async function request<T = any>(url: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers || {});
  const hasBody = options.body !== undefined && options.body !== null;

  // Do not advertise JSON for bodyless requests. Fastify correctly treats an
  // empty `application/json` body as malformed JSON, while the API contract
  // for actions such as subscribe/bookmark/mark-read requires no payload.
  if (hasBody && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  if (!headers.has('X-Request-ID')) {
    headers.set('X-Request-ID', createRequestId());
  }
  const outboundRequestId = headers.get('X-Request-ID') || '';

  const method = String(options.method || 'GET').toUpperCase();
  const execute = async (): Promise<T> => {
    const res = await apiFetch(`${BASE}${url}`, {
      ...options,
      credentials: 'include',
      headers,
    });
    if (res.status === 204) return null as T;
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      // Preserve safe domain metadata plus the request correlation ID. This
      // lets callers distinguish authoritative domain failures without leaking
      // transport credentials, SQL details, or storage paths.
      const error = apiErrorFromResponse(res, data, outboundRequestId);
      if (!error.detail && !error.message) {
        error.message = `Request failed with HTTP ${res.status}`;
      }
      throw error;
    }
    return data as T;
  };

  // React development StrictMode and sibling components can issue the same GET
  // during the same render window. Share only the in-flight request; never keep
  // a stale response cache here.
  if (method === 'GET' && !hasBody) {
    const key = `${BASE}${url}:${headers.get('X-MReader-Account-ID') || ''}`;
    const existing = inflightGetRequests.get(key) as Promise<T> | undefined;
    if (existing) return existing;
    const pending = execute().finally(() => { if (inflightGetRequests.get(key) === pending) inflightGetRequests.delete(key); });
    inflightGetRequests.set(key, pending);
    return pending;
  }

  return execute();
}

export interface User {
  id: string;
  username: string;
  email: string;
  role: string;
  avatar_key: string;
  created_at: string;
}

export interface Tag {
  id: number;
  name: string;
}

export type SeriesStatus = 'ongoing' | 'hiatus' | 'completed' | 'cancelled';

export interface Series {
  id: string;
  title: string;
  slug: string;
  description: string | null;
  cover_image_path: string | null;
  status: SeriesStatus;
  created_at: string;
  updated_at: string;
  genres?: Genre[];
  tags?: Tag[];
  chapters?: Chapter[];
  chapter_offset?: number;
  chapter_limit?: number;
  chapter_has_more?: boolean;
  first_chapter?: { slug: string; chapter_number: number } | null;
}

export interface SeriesUpdateInput {
  title?: string;
  description?: string | null;
  cover_image_path?: string | null;
  status?: SeriesStatus;
  genre_ids?: number[];
  tag_ids?: number[];
  tag_names?: string[];
}

export interface LatestChapterSummary {
  chapter_number: number;
  title: string | null;
  slug: string;
  published_at: string;
}

export interface DiscoverySeries extends Series {
  latest_chapters: LatestChapterSummary[];
}

export interface DiscoveryResponse {
  popular: Series[];
  recent: DiscoverySeries[];
  new: Series[];
}


export type TrendingWindow = '24h' | '7d' | '30d';

export interface TrendingSeries extends Series {
  trend_score: number;
}

export interface TrendingResponse {
  window: TrendingWindow;
  generated_at: string;
  items: TrendingSeries[];
}

export type AnnouncementTone = 'info' | 'success' | 'warning' | 'critical';

export interface EditorPick {
  id: string;
  series: Series;
  label: string | null;
  note: string | null;
  position: number;
  is_active: boolean;
  starts_at: string | null;
  ends_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Announcement {
  id: string;
  title: string;
  body: string;
  link_url: string | null;
  link_label: string | null;
  tone: AnnouncementTone;
  dismissible: boolean;
  position: number;
  is_active: boolean;
  starts_at: string | null;
  ends_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CurationResponse {
  editor_picks: EditorPick[];
  announcements: Announcement[];
}

export interface EditorPickUpsert {
  series_id: string;
  label: string | null;
  note: string | null;
  position: number;
  is_active: boolean;
  starts_at: string | null;
  ends_at: string | null;
}

export interface AnnouncementUpsert {
  title: string;
  body: string;
  link_url: string | null;
  link_label: string | null;
  tone: AnnouncementTone;
  dismissible: boolean;
  position: number;
  is_active: boolean;
  starts_at: string | null;
  ends_at: string | null;
}

export interface Genre {
  id: number;
  name: string;
}

export interface Chapter {
  id: string;
  series_id: string;
  chapter_number: number;
  title: string | null;
  slug: string;
  status: string;
  page_count: number;
  created_at: string;
  updated_at: string;
}

export interface Page {
  page_number: number;
  image_path: string;
  token?: string;
  width: number | null;
  height: number | null;
  responsive_image_path?: string | null;
  responsive_width?: number | null;
  responsive_height?: number | null;
  encoding_version: number;
  encoding_rows: number | null;
  encoding_columns: number | null;
  encoding_seed: string | null;
}

export interface ReaderData {
  series_id: string;
  series_title: string;
  series_slug: string;
  chapter_id: string;
  chapter_number: number;
  chapter_title: string | null;
  chapter_slug: string;
  page_count: number;
  chapter_token?: string;
  chapter_encoding_seed?: string | null;
  pages: Page[];
  prev_chapter: { slug: string; chapter_number: number } | null;
  next_chapter: { slug: string; chapter_number: number } | null;
}

export interface Comment {
  id: string;
  user_id: string;
  author_username: string;
  series_id: string;
  chapter_id: string | null;
  parent_id: string | null;
  content: string;
  created_at: string;
  updated_at: string;
}

export interface CommentList {
  items: Comment[];
  total: number;
  offset: number;
  limit: number;
}

export interface Notification {
  id: string;
  kind: string;
  series_id: string | null;
  chapter_id: string | null;
  message: string;
  is_read: boolean;
  created_at: string;
  series_title: string | null;
  series_slug: string | null;
  chapter_number: number | null;
  chapter_slug: string | null;
}

export interface Bookmark {
  id: string;
  series_id: string;
  series_title: string;
  series_slug: string;
  series_cover: string | null;
  series_status: string;
  created_at: string;
}

export interface Subscription extends Bookmark {
  unread_count: number;
}

export type SmartLibraryScope = 'all' | 'bookmarks' | 'following' | 'history';
export type SmartLibraryState = 'all' | 'updates' | 'caught_up' | 'not_started';
export type SmartLibrarySort = 'activity' | 'updated' | 'unread' | 'title';
export type SmartLibraryReadState = Exclude<SmartLibraryState, 'all'>;

export interface SmartLibraryItem {
  reading_revision: number;
  reading_available: boolean;
  reading_action: { kind: 'start' | 'resume' | 'next'; chapter_id: string; chapter_slug: string } | null;
  series_id: string;
  series_title: string;
  series_slug: string;
  series_cover: string | null;
  series_status: string;
  bookmarked: boolean;
  followed: boolean;
  has_history: boolean;
  bookmark_created_at: string | null;
  followed_at: string | null;
  read_at: string | null;
  resume_chapter_id: string | null;
  resume_chapter_number: number | null;
  resume_chapter_title: string | null;
  resume_chapter_slug: string | null;
  furthest_chapter_id: string | null;
  furthest_chapter_number: number | null;
  furthest_chapter_title: string | null;
  furthest_chapter_slug: string | null;
  latest_chapter_id: string | null;
  latest_chapter_number: number | null;
  latest_chapter_title: string | null;
  latest_chapter_slug: string | null;
  latest_published_at: string | null;
  first_chapter_id: string | null;
  first_chapter_number: number | null;
  first_chapter_title: string | null;
  first_chapter_slug: string | null;
  next_chapter_id: string | null;
  next_chapter_number: number | null;
  next_chapter_title: string | null;
  next_chapter_slug: string | null;
  published_chapter_count: number;
  unread_chapter_count: number;
  read_state: SmartLibraryReadState;
  activity_at: string;
}

export interface SmartLibrarySummary {
  all: number;
  bookmarks: number;
  following: number;
  history: number;
  updates: number;
  caught_up: number;
  not_started: number;
}

export interface SmartLibraryResponse {
  contract_version: 1;
  generated_at: string;
  request_identity: { scope: SmartLibraryScope; state: SmartLibraryState; sort: SmartLibrarySort; offset: number; limit: number };
  recently_opened: { items: SmartLibraryItem[]; total: number };
  items: SmartLibraryItem[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
  summary: SmartLibrarySummary;
}

export interface SeriesSocialMetrics {
  series_id: string;
  bookmark_count: number;
  subscription_count: number;
  comment_count: number;
  rating_average: number | null;
  rating_count: number;
  user_rating: number | null;
}

export interface SeriesViewerState extends SeriesSocialMetrics {
  bookmarked: boolean;
  subscribed: boolean;
}

export type ReadingProgress = CanonicalReading;

export interface SeriesReadingState {
  series_id: string;
  resume_chapter_id: string | null;
  resume_chapter_slug: string | null;
  resume_chapter_number: number | null;
  furthest_chapter_id: string | null;
  furthest_chapter_number: number | null;
  last_page: number | null;
  scroll_position: number | null;
  updated_at: string | null;
  revision: number;
  read_chapter_ids: string[];
  completed_chapter_ids: string[];
}




export interface CatalogDeletionResult {
  catalog_removed: boolean;
  storage_cleanup: 'queued' | 'processing' | 'retry' | 'completed' | 'failed' | string;
  job_id: string;
}

export interface ScraperSeriesDraftPage {
  id: string;
  order: number;
  source_url: string | null;
  staging_path: string;
  content_type: string;
}

export interface ScraperSeriesDraftChapter {
  id: string;
  draft_id: string;
  chapter_number: string | number;
  chapter_slug: string;
  chapter_title: string | null;
  source_url: string;
  selected: boolean;
  stage_status:
    | 'discovered'
    | 'queued'
    | 'staging'
    | 'ready'
    | 'error'
    | 'published';
  pages: ScraperSeriesDraftPage[];
  error_message: string | null;
  stage_progress: {
    phase: string;
    percent: number;
    message: string;
    pages_total?: number;
    pages_completed?: number;
    [key: string]: unknown;
  };
  stage_started_at: string | null;
  stage_finished_at: string | null;
  stage_worker_heartbeat_at: string | null;
  publish_status:
    | 'pending'
    | 'publishing'
    | 'published'
    | 'failed'
    | 'skipped'
    | 'cancelled'
    | string;
  publish_error: string | null;
  publish_progress: {
    phase: string;
    percent: number;
    message: string;
    source_pages_total?: number;
    source_pages_completed?: number;
    final_pages_written?: number;
    [key: string]: unknown;
  };
  publish_attempt: number;
  publish_started_at: string | null;
  publish_finished_at: string | null;
  published_chapter_id: string | null;
}

export interface ScraperDiscoveryProgress {
  phase: string;
  percent: number;
  message: string;
  chapters_found?: number;
  source_strategy?: string;
  [key: string]: unknown;
}

export interface ScraperPublishProgress {
  phase:
    | 'not_started'
    | 'queued'
    | 'queue_failed'
    | 'starting'
    | 'processing_cover'
    | 'processing_pages'
    | 'saving_database'
    | 'invalidating_cache'
    | 'verifying_catalog'
    | 'verifying_reader'
    | 'completed'
    | 'completed_with_warnings'
    | 'failed'
    | string;
  percent: number;
  message: string;
  total_chapters: number;
  chapters_completed: number;
  chapters_processed?: number;
  chapters_published?: number;
  chapters_failed?: number;
  chapters_skipped?: number;
  chapters_cancelled?: number;
  chapters_deferred?: number;
  chapters_staging?: number;
  chapters_publishing?: number;
  chapters_ready_pending?: number;
  total_source_pages: number;
  source_pages_completed: number;
  final_pages_written: number;
  current_chapter_slug?: string | null;
  current_chapter_number?: string | number | null;
  current_page?: number;
  database_committed?: boolean;
  published_series_id?: string | null;
  catalog_verified: boolean;
  catalog_verified_chapters: number;
  reader_verified_chapters: number;
  reader_verified_images: number;
  verification_errors: string[];
  cleanup_warning?: string | null;
  updated_at?: string;
}

export interface ScraperOperationEvent {
  id: number;
  operation_id: string;
  chapter_id: string | null;
  request_id: string | null;
  service: string;
  event_type: string;
  phase: string | null;
  status: string | null;
  message: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface ScraperSeriesDraft {
  id: string;
  source_url: string;
  adapter: string;
  title: string;
  slug: string;
  description: string | null;
  series_status: string;
  cover_source_url: string | null;
  cover_staging_path: string | null;
  genres: string[];
  tags: string[];
  workflow_status: string;
  operation_status: string | null;
  operation_phase: string | null;
  operation_revision: number | null;
  operation_lease_generation: number | null;
  operation_cancel_requested_at: string | null;
  operation_error_code: string | null;
  error_message: string | null;
  discovery_options: {
    recursive: boolean;
    max_depth: number;
    max_pages: number;
    suppress_chapter_titles?: boolean;
  };
  chapter_titles_suppressed?: boolean;
  discovery_progress: {
    phase: string;
    percent: number;
    message: string;
    chapters_found?: number;
    source_strategy?: string;
    [key: string]: unknown;
  };
  discovery_attempt: number;
  discovery_started_at: string | null;
  discovery_finished_at: string | null;
  discovery_worker_heartbeat_at: string | null;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  operation_cancel_requested_at: string | null;
  operation_cancel_requested_by: string | null;
  duplicate_series_id: string | null;
  duplicate_series_slug: string | null;
  duplicate_series_title: string | null;
  publish_progress: ScraperPublishProgress;
  publish_attempt: number;
  publish_started_at: string | null;
  publish_finished_at: string | null;
  publish_cancel_requested_at: string | null;
  publish_worker_heartbeat_at: string | null;
  published_series_id: string | null;
  chapters: ScraperSeriesDraftChapter[];
  created_at: string;
  updated_at: string;
  discovery?: {
    recursive_requested?: boolean;
    source_strategy?: string | null;
    recursive?: {
      enabled?: boolean;
      max_depth?: number;
      max_pages?: number;
      pages_fetched?: number;
      visited?: number;
      chapters_found?: number;
      errors?: string[];
    } | null;
  };
}

export type ScraperOperationGroup =
  | 'running'
  | 'awaiting_admin'
  | 'completed'
  | 'attention'
  | 'acknowledged'
  | 'unknown';

export interface ScraperOperation {
  id: string;
  source_url: string;
  adapter: string;
  title: string;
  slug: string;
  workflow_status: string;
  operation_status: string | null;
  operation_phase: string | null;
  operation_revision: number | null;
  operation_lease_generation: number | null;
  operation_cancel_requested_at: string | null;
  operation_error_code: string | null;
  error_message: string | null;
  discovery_options: Record<string, unknown>;
  discovery_progress: Record<string, any>;
  discovery_attempt: number;
  discovery_started_at: string | null;
  discovery_finished_at: string | null;
  discovery_worker_heartbeat_at: string | null;
  operation_cancel_requested_at: string | null;
  duplicate_series_id: string | null;
  duplicate_series_slug: string | null;
  duplicate_series_title: string | null;
  publish_progress: ScraperPublishProgress;
  publish_attempt: number;
  publish_started_at: string | null;
  publish_finished_at: string | null;
  publish_worker_heartbeat_at: string | null;
  published_series_id: string | null;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  chapter_count: number;
  selected_chapters: number;
  ready_chapters: number;
  stage_error_chapters: number;
  published_chapters: number;
  publish_failed_chapters: number;
  operation_group: ScraperOperationGroup;
  progress: {
    phase?: string;
    percent?: number;
    message?: string;
    [key: string]: unknown;
  };
  queue_name: string | null;
  queue_position: number | null;
}

export interface ScraperOperationsResponse {
  items: ScraperOperation[];
  summary: {
    running: number;
    awaiting_admin: number;
    completed: number;
    attention: number;
    acknowledged: number;
    total: number;
  };
  queue_depths: {
    discovery: number | null;
    staging: number | null;
    publish: number | null;
  };
}

export interface ScraperBatchItem {
  id: string;
  batch_id: string;
  target_series_id: string;
  chapter_number: number | string;
  chapter_slug: string;
  status:
    | 'queued'
    | 'processing'
    | 'completed'
    | 'failed_conflict'
    | 'failed_error'
    | 'discarded';
  existing_chapter_id: string | null;
  published_chapter_id: string | null;
  error_message: string | null;
  source_files?: Array<{
    filename: string;
    staging_path: string;
    content_type: string;
    order: number;
  }>;
  created_at: string;
  updated_at: string;
}

export interface ScraperBatch {
  id: string;
  target_series_id: string;
  series_title: string;
  series_slug: string;
  status: string;
  total_items: number;
  created_at: string;
  updated_at: string;
  items: ScraperBatchItem[];
}

export interface ScraperBatchSummary {
  id: string;
  target_series_id: string;
  series_title: string;
  series_slug: string;
  status: string;
  total_items: number;
  completed_items: number;
  conflict_items: number;
  error_items: number;
  queued_items: number;
  processing_items: number;
  created_at: string;
  updated_at: string;
}

export interface ScraperSeriesSummary {
  id: string;
  title: string;
  slug: string;
  status: string;
  cover_image_path: string | null;
  chapter_count: number;
}

export interface ScraperSeriesDetail extends Series {
  chapters: Chapter[];
  genres: Genre[];
  tags: Tag[];
}

export interface ScraperDraftPage {
  id: string;
  order: number;
  source_url: string | null;
  staging_path: string;
  content_type: string;
  enabled: boolean;
}

export interface ScraperChapterDraft {
  id: string;
  draft_type: string;
  source_url: string;
  target_series_id: string;
  series_data: {
    id: string;
    title: string;
    slug: string;
    status: string;
  };
  chapter_data: {
    chapter_number: string;
    chapter_slug: string;
    chapter_title: string | null;
    chapter_url: string;
    adapter: string;
    scrape_summary?: {
      discovered_count: number;
      staged_count: number;
      failed_count: number;
      failures: Array<{
        order: number;
        source_url: string;
        status_code: number | null;
        error: string;
      }>;
    };
  };
  pages: ScraperDraftPage[];
  status: string;
  published_chapter_id: string | null;
  created_at: string;
  updated_at: string;
}


function parseScraperJsonField<T>(
  value: T | string,
  field: string
): T {
  if (typeof value !== 'string') return value;

  try {
    return JSON.parse(value) as T;
  } catch {
    throw new Error(
      `Invalid scraper draft response: ${field} is not valid JSON.`
    );
  }
}

function normalizeScraperChapterDraft(
  raw: any
): ScraperChapterDraft {
  if (!raw || typeof raw !== 'object') {
    throw new Error('Invalid scraper draft response.');
  }

  const seriesData = parseScraperJsonField<any>(
    raw.series_data,
    'series_data'
  );
  const chapterData = parseScraperJsonField<any>(
    raw.chapter_data,
    'chapter_data'
  );
  const pages = parseScraperJsonField<any>(
    raw.pages,
    'pages'
  );

  if (!seriesData || typeof seriesData !== 'object' || Array.isArray(seriesData)) {
    throw new Error(
      'Invalid scraper draft response: series_data must be an object.'
    );
  }

  if (!chapterData || typeof chapterData !== 'object' || Array.isArray(chapterData)) {
    throw new Error(
      'Invalid scraper draft response: chapter_data must be an object.'
    );
  }

  if (!Array.isArray(pages)) {
    throw new Error(
      'Invalid scraper draft response: pages must be an array.'
    );
  }

  if (
    chapterData.scrape_summary &&
    typeof chapterData.scrape_summary === 'string'
  ) {
    chapterData.scrape_summary = parseScraperJsonField(
      chapterData.scrape_summary,
      'chapter_data.scrape_summary'
    );
  }

  return {
    ...raw,
    series_data: seriesData,
    chapter_data: chapterData,
    pages,
  } as ScraperChapterDraft;
}

export interface ScraperStagingHealth {
  root: string;
  spool_id: string | null;
  exists: boolean;
  writable: boolean;
  mount_visible: boolean;
  free_bytes: number | null;
  storage_backend: string;
  volume_name_hint: string | null;
  identity_matches: boolean;
  healthy: boolean;
  reference_sample: number;
  reference_visible: number;
  reference_missing: number;
  reference_missing_examples: string[];
  canonical: {
    spool_id: string;
    logical_root: string;
    last_service: string | null;
    last_seen_at: string | null;
  } | null;
}

export interface LifecycleCleanupJob {
  id: string;
  entity_type: string;
  entity_id: string | null;
  payload: Record<string, unknown>;
  status: 'queued' | 'processing' | 'retry' | 'completed' | 'failed' | string;
  attempts: number;
  max_attempts: number;
  next_attempt_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface HistoryItem {
  series_id: string;
  series_title: string;
  series_slug: string;
  chapter_id: string;
  chapter_number: number;
  chapter_title: string | null;
  chapter_slug: string;
  read_at: string;
}

async function waitForMediaJobResult(
  jobId: string,
  label: string,
  timeoutMs = 30 * 60 * 1000
): Promise<any> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await new Promise((resolve) => window.setTimeout(resolve, 1500));
    const statusRes = await apiFetch(`/api/upload/jobs/${jobId}`, { credentials: 'include' });
    const statusData = await statusRes.json().catch(() => null);
    if (!statusRes.ok) throw apiErrorFromResponse(statusRes, statusData, '', 'Failed to read media job status');
    if (statusData?.status === 'completed') return statusData.result;
    if (statusData?.status === 'failed') {
      throw { detail: statusData?.error || `${label} failed` };
    }
  }
  throw { detail: `${label} is still running. Check the media job status.` };
}

export const api = {
  // Auth
  register: (body: any) => request<User>('/api/auth/register', { method: 'POST', body: JSON.stringify(body) }),
  login: (body: any) => request<User>('/api/auth/login', { method: 'POST', body: JSON.stringify(body) }),
  logout: () => request('/api/auth/logout', { method: 'POST' }),
  clearCloudFrontCookies: () => request('/api/token/cloudfront/clear', { method: 'POST' }),
  getProfile: () => request<User>('/api/auth/profile'),
  updateProfile: (body: any) => request<User>('/api/auth/profile', { method: 'PUT', body: JSON.stringify(body) }),

  // Admin stats
  getAuthAdminStats: () => request<{ user_count: number }>('/api/auth/admin/stats'),
  getCatalogAdminStats: () => request<{ series_count: number; chapter_count: number }>('/api/catalog/admin/stats'),
  getSocialAdminStats: () => request<{ notification_count: number }>('/api/notifications/admin/stats'),
  getDatabaseProtection: (limit = 50, cursor?: string | null) =>
    request<DatabaseProtectionStatus>(
      `/api/admin/database?limit=${Math.max(1, Math.min(limit, 100))}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`
    ),
  createDatabaseBackup: () => request<{ operation: DatabaseOperationItem; created: boolean }>('/api/admin/database/backups', { method: 'POST' }),
  createDatabaseSnapshot: () => request<{ operation: DatabaseOperationItem; created: boolean }>('/api/admin/database/snapshots', { method: 'POST' }),
  createDatabaseRestoreDrill: (backupId: string) => request<{ operation: DatabaseOperationItem; created: boolean }>('/api/admin/database/restore-drills', { method: 'POST', body: JSON.stringify({ backup_id: backupId }) }),
  createDatabaseRestore: (backupId: string, confirmation: string, installationFingerprint: string, restoreGeneration: number) => request<{ operation: DatabaseOperationItem; created: boolean }>('/api/admin/database/restores', { method: 'POST', body: JSON.stringify({ backup_id: backupId, confirmation, installation_fingerprint: installationFingerprint, restore_generation: restoreGeneration }) }),
  cancelDatabaseOperation: (id: string) => request<DatabaseOperationItem>(`/api/admin/database/operations/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),

  // Catalog
  listSeries: (params = '') => request<Series[]>(`/api/catalog/series${params}`),
  getSeries: (slug: string, params = '') => request<Series>(`/api/catalog/series/${slug}${params}`),
  getGenres: () => request<Genre[]>('/api/catalog/genres'),
  getTags: () => request<Tag[]>('/api/catalog/tags'),
  getDiscovery: () => request<DiscoveryResponse>('/api/catalog/discover'),
  getTrending: (window: TrendingWindow = '24h', limit = 10) =>
    request<TrendingResponse>(`/api/catalog/trending?window=${encodeURIComponent(window)}&limit=${limit}`),
  getCuration: () => request<CurationResponse>('/api/catalog/curation'),
  getAdminCuration: () => request<CurationResponse>('/api/catalog/admin/curation'),
  createEditorPick: (body: EditorPickUpsert) => request<EditorPick>('/api/catalog/admin/editor-picks', { method: 'POST', body: JSON.stringify(body) }),
  updateEditorPick: (id: string, body: EditorPickUpsert) => request<EditorPick>(`/api/catalog/admin/editor-picks/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteEditorPick: (id: string) => request(`/api/catalog/admin/editor-picks/${id}`, { method: 'DELETE' }),
  createAnnouncement: (body: AnnouncementUpsert) => request<Announcement>('/api/catalog/admin/announcements', { method: 'POST', body: JSON.stringify(body) }),
  updateAnnouncement: (id: string, body: AnnouncementUpsert) => request<Announcement>(`/api/catalog/admin/announcements/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteAnnouncement: (id: string) => request(`/api/catalog/admin/announcements/${id}`, { method: 'DELETE' }),
  createSeries: (body: any) => request<Series>('/api/catalog/series', { method: 'POST', body: JSON.stringify(body) }),
  updateSeries: (id: string, body: SeriesUpdateInput) => request<Series>(`/api/catalog/series/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteSeries: (id: string) => request<CatalogDeletionResult>(`/api/catalog/series/${id}`, { method: 'DELETE' }),
  createChapter: (seriesId: string, body: any) => request<Chapter>(`/api/catalog/series/${seriesId}/chapters`, { method: 'POST', body: JSON.stringify(body) }),
  deleteChapter: (seriesId: string, chapterId: string) => request<CatalogDeletionResult>(`/api/catalog/series/${seriesId}/chapters/${chapterId}`, { method: 'DELETE' }),
  deleteChapterFiles: (seriesSlug: string, chapterSlug: string) => request(`/api/upload/${seriesSlug}/${chapterSlug}`, { method: 'DELETE' }),
  listLifecycleCleanupJobs: (state: 'active' | 'queued' | 'processing' | 'retry' | 'completed' | 'failed' = 'active', limit = 50) =>
    request<LifecycleCleanupJob[]>(`/api/upload/admin/lifecycle/cleanup-jobs?state=${encodeURIComponent(state)}&limit=${Math.max(1, Math.min(200, limit))}`),
  retryLifecycleCleanupJob: (jobId: string) =>
    request<{ accepted: boolean; job_id: string }>(`/api/upload/admin/lifecycle/cleanup-jobs/${encodeURIComponent(jobId)}/retry`, { method: 'POST' }),
  getScraperStagingHealth: () => request<ScraperStagingHealth>('/api/scraper/admin/staging-health'),
  downloadChapterExport: async (chapterId: string, mode: 'stored' | 'decoded' = 'stored') => {
    const res = await apiFetch(`/api/upload/admin/chapters/${encodeURIComponent(chapterId)}/download?mode=${mode}`, { credentials: 'include' });
    if (!res.ok) {
      const data = await res.json().catch(() => null);
      throw apiErrorFromResponse(res, data, '', 'Chapter export failed');
    }
    const blob = await res.blob();
    const disposition = res.headers.get('content-disposition') || '';
    const utf8 = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    const plain = disposition.match(/filename=\"?([^\";]+)\"?/i);
    const filename = utf8 ? decodeURIComponent(utf8[1]) : plain?.[1] || `chapter-${chapterId}-${mode}.zip`;
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  },
  publishChapter: (seriesId: string, chapterId: string) => request<Chapter>(`/api/catalog/series/${seriesId}/chapters/${chapterId}/publish`, { method: 'POST' }),
  uploadSeriesThumbnail: async (seriesSlug: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    const queued = await apiFetch(`/api/upload/series/${encodeURIComponent(seriesSlug)}/thumbnail`, {
      method: 'POST',
      credentials: 'include',
      body: formData,
    });
    const queuedData = await queued.json().catch(() => null);
    if (!queued.ok) throw apiErrorFromResponse(queued, queuedData, '', 'Failed to queue thumbnail upload');
    const jobId = String(queuedData?.job_id || '');
    if (!jobId) throw new Error('Media service did not return a job ID');
    return waitForMediaJobResult(jobId, 'Thumbnail generation', 10 * 60 * 1000);
  },
  deleteSeriesThumbnail: (seriesSlug: string, thumbnailName: string) =>
    request(`/api/upload/series/${seriesSlug}/thumbnail/${encodeURIComponent(thumbnailName)}`, { method: 'DELETE' }),

  // Reader
  getReader: (seriesSlug: string, chapterSlug: string) => {
    const visitor = getReaderVisitorId();
    return request<ReaderData>(`/api/reader/${seriesSlug}/${chapterSlug}`, {
      headers: visitor ? { 'X-MReader-Visitor': visitor } : undefined,
    });
  },
  getHistory: (params = '') => request<HistoryItem[]>(`/api/progress/history${params}`),
  getProgress: readingTransport(request).getProgress,
  recordChapterOpen: readingTransport(request).open,
  commitProgress: readingTransport(request).commit,
  getSeriesReadingState: (seriesSlug: string) =>
    request<SeriesReadingState>(`/api/progress/series/${encodeURIComponent(seriesSlug)}/state`),
  refreshChapterToken: (seriesSlug: string, chapterSlug: string) =>
    request<{ token: string; chapter_id: string }>(
      `/api/token/chapter/${encodeURIComponent(seriesSlug)}/${encodeURIComponent(chapterSlug)}`
    ),

  // Social
  addBookmark: (seriesId: string) => request<Bookmark>(`/api/social/bookmarks/${seriesId}`, { method: 'POST' }),
  removeBookmark: (seriesId: string) => request(`/api/social/bookmarks/${seriesId}`, { method: 'DELETE' }),
  listBookmarks: (params = '') => request<Bookmark[]>(`/api/social/bookmarks${params}`),
  bookmarkStatus: (seriesId: string) => request<{ bookmarked: boolean }>(`/api/social/bookmarks/${seriesId}/status`),
  subscribe: (seriesId: string) => request<Subscription>(`/api/social/subscriptions/${seriesId}`, { method: 'POST' }),
  unsubscribe: (seriesId: string) => request(`/api/social/subscriptions/${seriesId}`, { method: 'DELETE' }),
  listSubscriptions: (params = '') => request<Subscription[]>(`/api/social/subscriptions${params}`),
  getSmartLibrary: (params: {
    scope?: SmartLibraryScope;
    state?: SmartLibraryState;
    sort?: SmartLibrarySort;
    offset?: number;
    limit?: number;
  } = {}) => {
    const query = new URLSearchParams();
    if (params.scope) query.set('scope', params.scope);
    if (params.state) query.set('state', params.state);
    if (params.sort) query.set('sort', params.sort);
    if (params.offset !== undefined) query.set('offset', String(params.offset));
    if (params.limit !== undefined) query.set('limit', String(params.limit));
    const suffix = query.size ? `?${query.toString()}` : '';
    return request<SmartLibraryResponse>(`/api/social/library${suffix}`);
  },
  subscriptionStatus: (seriesId: string) => request<{ subscribed: boolean }>(`/api/social/subscriptions/${seriesId}/status`),
  seriesSocialMetrics: (seriesId: string) =>
    request<SeriesSocialMetrics>(`/api/social/series/${seriesId}/metrics`),
  seriesViewerState: (seriesId: string) =>
    request<SeriesViewerState>(`/api/social/series/${seriesId}/viewer-state`),
  seriesSocialMetricsBatch: (seriesIds: string[]) =>
    request<{ items: SeriesSocialMetrics[] }>(`/api/social/series/metrics-batch`, {
      method: 'POST',
      body: JSON.stringify({ series_ids: seriesIds }),
    }),
  setSeriesRating: (seriesId: string, rating: number) =>
    request<SeriesSocialMetrics>(`/api/social/series/${seriesId}/rating`, {
      method: 'PUT',
      body: JSON.stringify({ rating }),
    }),
  clearSeriesRating: (seriesId: string) =>
    request(`/api/social/series/${seriesId}/rating`, { method: 'DELETE' }),
  listComments: ({ seriesId, chapterId }: { seriesId?: string; chapterId?: string }) => {
    const params = new URLSearchParams();
    if (seriesId) params.set('seriesId', seriesId);
    if (chapterId) params.set('chapterId', chapterId);
    return request<CommentList>(`/api/social/comments?${params.toString()}`);
  },
  createComment: (body: any) => request<Comment>('/api/social/comments', { method: 'POST', body: JSON.stringify(body) }),
  deleteComment: (id: string) => request(`/api/social/comments/${id}`, { method: 'DELETE' }),

  // Notifications
  listNotifications: (params = '') => request<Notification[]>(`/api/notifications${params}`),
  notificationCount: () => request<{ unread: number }>('/api/notifications/count'),
  markRead: (id: string) => request(`/api/notifications/${id}/read`, { method: 'POST' }),
  markAllRead: () => request<{ marked: number }>('/api/notifications/read-all', { method: 'POST' }),


  // Scraper admin


  scraperDiscoverSeriesDraft: (
    url: string,
    options: {
      recursive?: boolean;
      maxDepth?: number;
      maxPages?: number;
    } = {}
  ) =>
    request<ScraperSeriesDraft>('/api/scraper/series-drafts/discover', {
      method: 'POST',
      body: JSON.stringify({
        url,
        recursive: options.recursive ?? true,
        max_depth: options.maxDepth ?? 1,
        max_pages: options.maxPages ?? 20,
      }),
    }),
  scraperGetSeriesDraft: (draftId: string) =>
    request<ScraperSeriesDraft>(`/api/scraper/series-drafts/${draftId}`),
  scraperListOperations: (state = 'unacknowledged', limit = 200) =>
    request<ScraperOperationsResponse>(
      `/api/scraper/operations?state=${encodeURIComponent(state)}&limit=${limit}`
    ),
  scraperCancelOperation: (draftId: string) =>
    request<{ status: string; operation_id: string; removed_from_dashboard: boolean }>(
      `/api/scraper/operations/${draftId}`,
      { method: 'DELETE' }
    ),
  scraperAcknowledgeOperation: (draftId: string) =>
    request<ScraperSeriesDraft>(
      `/api/scraper/operations/${draftId}/acknowledge`,
      { method: 'POST' }
    ),
  scraperUnacknowledgeOperation: (draftId: string) =>
    request<ScraperSeriesDraft>(
      `/api/scraper/operations/${draftId}/unacknowledge`,
      { method: 'POST' }
    ),
  scraperRetryDiscovery: (draftId: string) =>
    request<ScraperSeriesDraft>(
      `/api/scraper/operations/${draftId}/retry-discovery`,
      { method: 'POST' }
    ),
  scraperUpdateSeriesDraft: (
    draftId: string,
    body: {
      title: string;
      slug: string;
      description: string | null;
      series_status: string;
      genres: string[];
      tags: string[];
    }
  ) =>
    request<ScraperSeriesDraft>(`/api/scraper/series-drafts/${draftId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  scraperClearSeriesDraftChapterTitles: (draftId: string) =>
    request<ScraperSeriesDraft>(
      `/api/scraper/series-drafts/${draftId}/chapters/clear-titles`,
      { method: 'POST' }
    ),
  scraperUpdateSeriesDraftChapter: (
    chapterId: string,
    body: {
      chapter_number: string;
      chapter_slug: string;
      chapter_title: string | null;
      selected: boolean;
    }
  ) =>
    request<ScraperSeriesDraft>(
      `/api/scraper/series-drafts/chapters/${chapterId}`,
      {
        method: 'PATCH',
        body: JSON.stringify(body),
      }
    ),
  scraperStageSeriesChapters: (draftId: string, chapterIds: string[]) =>
    request<ScraperSeriesDraft>(`/api/scraper/series-drafts/${draftId}/stage`, {
      method: 'POST',
      body: JSON.stringify({ chapter_ids: chapterIds }),
    }),
  scraperReplaceSeriesCoverUrl: (draftId: string, url: string) =>
    request<ScraperSeriesDraft>(
      `/api/scraper/series-drafts/${draftId}/cover/from-url`,
      {
        method: 'PUT',
        body: JSON.stringify({ url }),
      }
    ),
  scraperUploadSeriesCover: (draftId: string, file: File) => {
    const form = new FormData();
    form.append('file', file);

    return apiFetch(`/api/scraper/series-drafts/${draftId}/cover/upload`, {
      method: 'POST',
      credentials: 'include',
      body: form,
    }).then(async (res) => {
      const data = await res.json().catch(() => null);
      if (!res.ok) throw apiErrorFromResponse(res, data, '', 'Cover upload failed');
      return data as ScraperSeriesDraft;
    });
  },
  scraperRemoveSeriesCover: (draftId: string) =>
    request<ScraperSeriesDraft>(
      `/api/scraper/series-drafts/${draftId}/cover`,
      { method: 'DELETE' }
    ),
  scraperRemoveSeriesDraftPage: (chapterId: string, pageId: string) =>
    request<ScraperSeriesDraft>(
      `/api/scraper/series-drafts/chapters/${chapterId}/pages/${pageId}`,
      { method: 'DELETE' }
    ),
  scraperReorderSeriesDraftPages: (chapterId: string, pageIds: string[]) =>
    request<ScraperSeriesDraft>(
      `/api/scraper/series-drafts/chapters/${chapterId}/pages/reorder`,
      {
        method: 'POST',
        body: JSON.stringify({ page_ids: pageIds }),
      }
    ),
  scraperAddSeriesDraftPageUrl: (
    chapterId: string,
    url: string,
    position?: number
  ) =>
    request<ScraperSeriesDraft>(
      `/api/scraper/series-drafts/chapters/${chapterId}/pages/from-url`,
      {
        method: 'POST',
        body: JSON.stringify({ url, position }),
      }
    ),
  scraperAddSeriesDraftPageFile: (
    chapterId: string,
    file: File,
    position?: number
  ) => {
    const form = new FormData();
    form.append('file', file);
    if (position) form.append('position', String(position));

    return apiFetch(
      `/api/scraper/series-drafts/chapters/${chapterId}/pages/upload`,
      {
        method: 'POST',
        credentials: 'include',
        body: form,
      }
    ).then(async (res) => {
      const data = await res.json().catch(() => null);
      if (!res.ok) throw apiErrorFromResponse(res, data, '', 'Page upload failed');
      return data as ScraperSeriesDraft;
    });
  },
  scraperPublishSeriesDraftChapter: (draftId: string, chapterId: string) =>
    request<unknown>(
      `/api/scraper/series-drafts/${draftId}/chapters/${chapterId}/publish`,
      { method: 'POST' }
    ),
  scraperPublishSeriesDraft: (draftId: string) =>
    request<ScraperSeriesDraft>(
      `/api/scraper/series-drafts/${draftId}/publish`,
      { method: 'POST' }
    ),
  scraperCancelSeriesPublish: (draftId: string) =>
    request<ScraperSeriesDraft>(
      `/api/scraper/series-drafts/${draftId}/publish/cancel`,
      { method: 'POST' }
    ),
  scraperGetSeriesDraftChapterPages: (draftId: string, chapterId: string) =>
    request<{
      id: string;
      draft_id: string;
      stage_status: string;
      pages: ScraperSeriesDraftPage[];
      page_count: number;
      updated_at: string;
    }>(`/api/scraper/series-drafts/${draftId}/chapters/${chapterId}/pages`),

  scraperGetSeriesOperationEvents: (draftId: string, limit = 250, beforeId?: string | null) => {
    const params = new URLSearchParams({ limit: String(Math.max(1, Math.min(500, limit))) });
    if (beforeId) params.set('before_id', beforeId);
    return request<{
      operation_id: string;
      items: ScraperOperationEvent[];
      total: number;
      next_before_id: string | null;
    }>(`/api/scraper/series-drafts/${draftId}/events?${params.toString()}`);
  },
  scraperGetSeriesPublishStatus: (draftId: string) =>
    request<{
      id: string;
      slug: string;
      workflow_status: string;
      operation_status: string | null;
      operation_phase: string | null;
      operation_revision: number | null;
      operation_lease_generation: number | null;
      operation_cancel_requested_at: string | null;
      operation_error_code: string | null;
      error_message: string | null;
      published_series_id: string | null;
      publish_attempt: number;
      publish_started_at: string | null;
      publish_finished_at: string | null;
      publish_cancel_requested_at: string | null;
      publish_worker_heartbeat_at: string | null;
      publish_progress: ScraperPublishProgress;
      discovery_progress?: ScraperDiscoveryProgress;
      chapters: Array<{
        id: string;
        chapter_number: string | number;
        chapter_slug: string;
        selected: boolean;
        stage_status: string;
        published_chapter_id: string | null;
        error_message: string | null;
        publish_status: string;
        publish_error: string | null;
        publish_progress: {
          phase: string;
          percent: number;
          message: string;
          [key: string]: unknown;
        };
        publish_attempt: number;
        publish_started_at: string | null;
        publish_finished_at: string | null;
        page_count: number;
      }>;
    }>(`/api/scraper/series-drafts/${draftId}/workflow-status`),

    scraperCreateBatch: (
    seriesId: string,
    files: File[]
  ) => {
    const form = new FormData();
    form.append('series_id', seriesId);

    for (const file of files) {
      form.append('files', file);
      form.append(
        'relative_paths',
        (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
      );
    }

    return apiFetch('/api/scraper/batches', {
      method: 'POST',
      credentials: 'include',
      body: form,
    }).then(async (res) => {
      const data = await res.json().catch(() => null);
      if (!res.ok) throw apiErrorFromResponse(res, data, '', 'Batch upload failed');
      return data as ScraperBatch;
    });
  },
  scraperListBatches: (seriesId?: string) =>
    request<ScraperBatchSummary[]>(
      `/api/scraper/batches?limit=50${
        seriesId ? `&series_id=${encodeURIComponent(seriesId)}` : ''
      }`
    ),
  scraperGetBatch: (batchId: string) =>
    request<ScraperBatch>(`/api/scraper/batches/${batchId}`),
  scraperFailedBatchItems: (seriesId?: string) =>
    request<ScraperBatchItem[]>(
      `/api/scraper/batches/failed?limit=200${
        seriesId ? `&series_id=${encodeURIComponent(seriesId)}` : ''
      }`
    ),
  scraperResolveBatchItem: (
    itemId: string,
    action: 'discard' | 'overwrite'
  ) =>
    request<{ id: string; status: string }>(
      `/api/scraper/batches/items/${itemId}/resolve`,
      {
        method: 'POST',
        body: JSON.stringify({ action }),
      }
    ),
  scraperRetryBatchItem: (itemId: string) =>
    request<{ id: string; status: string }>(
      `/api/scraper/batches/items/${itemId}/retry`,
      {
        method: 'POST',
        body: JSON.stringify({ action: 'retry' }),
      }
    ),

  scraperSearchSeries: (search = '') =>
    request<ScraperSeriesSummary[]>(
      `/api/scraper/admin/series?search=${encodeURIComponent(search)}&limit=100`
    ),
  scraperGetSeries: (seriesId: string) =>
    request<ScraperSeriesDetail>(`/api/scraper/admin/series/${seriesId}`),
  scraperCreateChapterDraft: (seriesId: string, chapterUrl: string) =>
    request<any>('/api/scraper/drafts/chapter', {
      method: 'POST',
      body: JSON.stringify({
        series_id: seriesId,
        chapter_url: chapterUrl,
      }),
    }).then(normalizeScraperChapterDraft),
  scraperGetDraft: (draftId: string) =>
    request<any>(`/api/scraper/drafts/${draftId}`)
      .then(normalizeScraperChapterDraft),
  scraperUpdateDraftChapter: (
    draftId: string,
    body: {
      chapter_number: string;
      chapter_slug: string;
      chapter_title: string | null;
    }
  ) =>
    request<any>(`/api/scraper/drafts/${draftId}/chapter`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }).then(normalizeScraperChapterDraft),
  scraperRemoveDraftPage: (draftId: string, pageId: string) =>
    request<any>(
      `/api/scraper/drafts/${draftId}/pages/${pageId}`,
      { method: 'DELETE' }
    ).then(normalizeScraperChapterDraft),
  scraperReorderDraftPages: (draftId: string, pageIds: string[]) =>
    request<any>(
      `/api/scraper/drafts/${draftId}/pages/reorder`,
      {
        method: 'POST',
        body: JSON.stringify({ page_ids: pageIds }),
      }
    ).then(normalizeScraperChapterDraft),
  scraperAddDraftPageUrl: (
    draftId: string,
    url: string,
    position?: number
  ) =>
    request<any>(
      `/api/scraper/drafts/${draftId}/pages/from-url`,
      {
        method: 'POST',
        body: JSON.stringify({ url, position }),
      }
    ).then(normalizeScraperChapterDraft),
  scraperAddDraftPageFile: (
    draftId: string,
    file: File,
    position?: number
  ) => {
    const form = new FormData();
    form.append('file', file);
    if (position) form.append('position', String(position));

    return apiFetch(`/api/scraper/drafts/${draftId}/pages/upload`, {
      method: 'POST',
      credentials: 'include',
      body: form,
    }).then(async (res) => {
      const data = await res.json().catch(() => null);
      if (!res.ok) throw apiErrorFromResponse(res, data, '', 'Upload failed');
      return normalizeScraperChapterDraft(data);
    });
  },
  scraperReplaceDraftPageUrl: (
    draftId: string,
    pageId: string,
    url: string
  ) =>
    request<any>(
      `/api/scraper/drafts/${draftId}/pages/${pageId}/from-url`,
      {
        method: 'PUT',
        body: JSON.stringify({ url }),
      }
    ).then(normalizeScraperChapterDraft),
  scraperRetryFailedDraftPages: (draftId: string) =>
    request<any>(
      `/api/scraper/drafts/${draftId}/pages/retry-failed`,
      { method: 'POST' }
    ).then(normalizeScraperChapterDraft),

  scraperPublishDraft: (draftId: string) =>
    request<any>(`/api/scraper/drafts/${draftId}/publish`, {
      method: 'POST',
    }),

  // Upload
  uploadChapter: async (
    seriesSlug: string,
    chapterSlug: string,
    file: File,
    chapterNumber = 1,
    title: string | null = null,
    firstImage: File | null = null,
    lastImage: File | null = null
  ) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('chapter_number', String(chapterNumber));
    if (title) formData.append('title', title);

    // Every chapter variant uses the same durable Media operation. Optional
    // boundary images are staged as inputs to that job instead of switching to
    // a second synchronous publication implementation.
    if (firstImage) formData.append('first_image', firstImage);
    if (lastImage) formData.append('last_image', lastImage);

    const queued = await apiFetch(`/api/upload/jobs/chapter/${seriesSlug}/${chapterSlug}`, {
      method: 'POST',
      credentials: 'include',
      body: formData,
    });
    const queuedData = await queued.json().catch(() => null);
    if (!queued.ok) throw apiErrorFromResponse(queued, queuedData, '', 'Failed to queue chapter upload');
    const jobId = String(queuedData?.job_id || '');
    if (!jobId) throw new Error('Media service did not return a job ID');

    // One admin polling loop is shared by chapter and cover jobs; Media remains
    // the only CPU-heavy execution boundary.
    return waitForMediaJobResult(jobId, 'Chapter ingestion');
  },
};
