import type { FastifyInstance } from "fastify";
import { Prisma, type PrismaClient } from "@prisma/client";
import type { Redis } from "ioredis";
import { config } from "./config.js";
import { requireAdmin, requireUser, sessionFromRequest } from "./session.js";
import { sweepExpiredNotifications } from "./maintenance.js";

type HttpError = Error & { statusCode?: number };
const MAX_COMMENT_DEPTH = 5;

function httpError(statusCode: number, message: string): HttpError {
  const err = new Error(message) as HttpError;
  err.statusCode = statusCode;
  return err;
}

function asInt(value: unknown, fallback: number, min: number, max: number): number {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < min) return fallback;
  return Math.min(parsed, max);
}

function validUuid(value: string | undefined | null): value is string {
  if (!value) return false;
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

function requireUuid(value: string, field: string): string {
  if (!validUuid(value)) throw httpError(400, `Invalid ${field}.`);
  return value;
}

function commentResponse(row: {
  id: string; userId: string; seriesId: string; chapterId: string | null;
  parentId: string | null; content: string; createdAt: Date; updatedAt: Date;
  user: { username: string };
}) {
  return {
    id: row.id, user_id: row.userId, author_username: row.user.username,
    series_id: row.seriesId, chapter_id: row.chapterId, parent_id: row.parentId,
    content: row.content, created_at: row.createdAt, updated_at: row.updatedAt,
  };
}

function commentChannel(seriesId: string, chapterId: string | null): string {
  return `social:comments:${seriesId}:${chapterId ?? "series"}`;
}

async function publishCommentEvent(
  redis: Redis, seriesId: string, chapterId: string | null, payload: unknown,
): Promise<void> {
  await redis.publish(commentChannel(seriesId, chapterId), JSON.stringify(payload));
}

async function commentDepth(
  prisma: PrismaClient, parentId: string, seriesId: string, chapterId: string | null,
): Promise<number> {
  let cursor: string | null = parentId;
  let depth = 0;
  while (cursor) {
    depth += 1;
    if (depth >= MAX_COMMENT_DEPTH) {
      throw httpError(400, `Replies are limited to ${MAX_COMMENT_DEPTH} levels.`);
    }
    const parent: { parentId: string | null; seriesId: string; chapterId: string | null } | null =
      await prisma.comment.findUnique({
        where: { id: cursor },
        select: { parentId: true, seriesId: true, chapterId: true },
      });
    if (!parent) throw httpError(404, "Parent comment not found.");
    if (parent.seriesId !== seriesId || parent.chapterId !== chapterId) {
      throw httpError(400, "Parent comment does not match target.");
    }
    cursor = parent.parentId;
  }
  return depth;
}

type SeriesMetric = {
  series_id: string;
  bookmark_count: number;
  subscription_count: number;
  comment_count: number;
  rating_average: number | null;
  rating_count: number;
  user_rating: number | null;
};

function uuidList(ids: string[]) {
  return Prisma.join(ids.map((id) => Prisma.sql`${id}::uuid`));
}

async function metricsForSeriesBatch(
  prisma: PrismaClient, seriesIds: string[], userId?: string,
): Promise<SeriesMetric[]> {
  if (seriesIds.length === 0) return [];
  const idList = uuidList(seriesIds);

  const baseRows = await prisma.$queryRaw<Array<{
    series_id: string;
    bookmark_count: bigint;
    subscription_count: bigint;
    comment_count: bigint;
  }>>(Prisma.sql`
    WITH requested AS (
      SELECT s.id
        FROM series s
       WHERE s.id IN (${idList})
    ),
    bookmark_counts AS (
      SELECT b.series_id, COUNT(*)::bigint AS count
        FROM bookmarks b
        JOIN requested r ON r.id = b.series_id
       GROUP BY b.series_id
    ),
    subscription_counts AS (
      SELECT sub.series_id, COUNT(*)::bigint AS count
        FROM subscriptions sub
        JOIN requested r ON r.id = sub.series_id
       GROUP BY sub.series_id
    ),
    comment_counts AS (
      SELECT c.series_id, COUNT(*)::bigint AS count
        FROM comments c
        JOIN requested r ON r.id = c.series_id
       GROUP BY c.series_id
    )
    SELECT r.id::text AS series_id,
           COALESCE(b.count, 0)::bigint AS bookmark_count,
           COALESCE(sub.count, 0)::bigint AS subscription_count,
           COALESCE(c.count, 0)::bigint AS comment_count
      FROM requested r
      LEFT JOIN bookmark_counts b ON b.series_id = r.id
      LEFT JOIN subscription_counts sub ON sub.series_id = r.id
      LEFT JOIN comment_counts c ON c.series_id = r.id
  `);

  if (baseRows.length !== seriesIds.length) {
    throw httpError(404, "Series not found.");
  }

  const metrics = new Map<string, SeriesMetric>();
  for (const row of baseRows) {
    metrics.set(row.series_id, {
      series_id: row.series_id,
      bookmark_count: Number(row.bookmark_count),
      subscription_count: Number(row.subscription_count),
      comment_count: Number(row.comment_count),
      rating_average: null,
      rating_count: 0,
      user_rating: null,
    });
  }

  // Ratings migration is mandatory in the consolidated baseline.
    const ratingRows = await prisma.$queryRaw<Array<{
      series_id: string;
      rating_average: number | null;
      rating_count: bigint;
    }>>(Prisma.sql`
      SELECT sr.series_id::text AS series_id,
             AVG(sr.rating)::float8 AS rating_average,
             COUNT(*)::bigint AS rating_count
        FROM series_ratings sr
       WHERE sr.series_id IN (${idList})
       GROUP BY sr.series_id
    `);
    for (const row of ratingRows) {
      const item = metrics.get(row.series_id);
      if (!item) continue;
      item.rating_average = row.rating_average === null ? null : Number(row.rating_average);
      item.rating_count = Number(row.rating_count);
    }

    if (userId) {
      const ownRows = await prisma.$queryRaw<Array<{ series_id: string; rating: number }>>(Prisma.sql`
        SELECT sr.series_id::text AS series_id, sr.rating::int AS rating
          FROM series_ratings sr
         WHERE sr.user_id = ${userId}::uuid
           AND sr.series_id IN (${idList})
      `);
      for (const row of ownRows) {
        const item = metrics.get(row.series_id);
        if (item) item.user_rating = Number(row.rating);
      }
    }

  return seriesIds.map((id) => metrics.get(id)!).filter(Boolean);
}

async function metricsForSeries(
  prisma: PrismaClient, seriesId: string, userId?: string,
) {
  return (await metricsForSeriesBatch(prisma, [seriesId], userId))[0];
}

type SeriesViewerState = SeriesMetric & {
  bookmarked: boolean;
  subscribed: boolean;
};

async function viewerStateForSeries(
  prisma: PrismaClient, seriesId: string, userId?: string,
): Promise<SeriesViewerState> {
  const metric = (await metricsForSeriesBatch(prisma, [seriesId], userId))[0];
  if (!metric) throw httpError(404, "Series not found.");
  if (!userId) return { ...metric, bookmarked: false, subscribed: false };

  const rows = await prisma.$queryRaw<Array<{ bookmarked: boolean; subscribed: boolean }>>(Prisma.sql`
    SELECT EXISTS(
             SELECT 1 FROM bookmarks b
              WHERE b.series_id=${seriesId}::uuid AND b.user_id=${userId}::uuid
           ) AS bookmarked,
           EXISTS(
             SELECT 1 FROM subscriptions sub
              WHERE sub.series_id=${seriesId}::uuid AND sub.user_id=${userId}::uuid
           ) AS subscribed
  `);
  const flags = rows[0] ?? { bookmarked: false, subscribed: false };
  return { ...metric, bookmarked: Boolean(flags.bookmarked), subscribed: Boolean(flags.subscribed) };
}


type SmartLibraryScope = "all" | "bookmarks" | "following" | "history";
type SmartLibraryState = "all" | "updates" | "caught_up" | "not_started";
type SmartLibrarySort = "activity" | "updated" | "unread" | "title";

function enumQuery<T extends string>(
  value: unknown,
  fallback: T,
  allowed: readonly T[],
  field: string,
): T {
  if (value === undefined || value === null || value === "") return fallback;
  if (typeof value !== "string" || !allowed.includes(value as T)) {
    throw httpError(400, `Invalid ${field}.`);
  }
  return value as T;
}

const SMART_LIBRARY_BASE_SQL = `
WITH reading AS MATERIALIZED (
  SELECT * FROM reading_state_v1
  WHERE user_id=$1::uuid AND (has_history OR furthest_chapter_id IS NOT NULL)
),
personal_ids AS (
  SELECT series_id FROM bookmarks WHERE user_id = $1::uuid
  UNION
  SELECT series_id FROM subscriptions WHERE user_id = $1::uuid
  UNION
  SELECT series_id FROM reading
),
personal AS (
  SELECT
    s.id AS series_id,
    s.title AS series_title,
    s.slug AS series_slug,
    s.cover_image_path AS series_cover,
    s.status AS series_status,
    (b.id IS NOT NULL) AS bookmarked,
    (sub.id IS NOT NULL) AS followed,
    COALESCE(eh.has_history, FALSE) AS has_history,
    b.created_at AS bookmark_created_at,
    sub.created_at AS followed_at,
    eh.last_opened_at AS read_at,
    COALESCE(eh.revision, 0) AS reading_revision,
    eh.last_page,
    eh.scroll_position,
    resume.id AS resume_chapter_id,
    resume.chapter_number::float8 AS resume_chapter_number,
    resume.title AS resume_chapter_title,
    resume.slug AS resume_chapter_slug,
    eh.furthest_chapter_id AS furthest_chapter_id,
    furthest.chapter_number::float8 AS furthest_chapter_number,
    furthest.title AS furthest_chapter_title,
    furthest.slug AS furthest_chapter_slug
  FROM personal_ids pi
  JOIN series s ON s.id = pi.series_id
  LEFT JOIN bookmarks b
    ON b.series_id = s.id AND b.user_id = $1::uuid
  LEFT JOIN subscriptions sub
    ON sub.series_id = s.id AND sub.user_id = $1::uuid
  LEFT JOIN reading eh
    ON eh.series_id = s.id AND eh.user_id = $1::uuid
  LEFT JOIN chapters resume ON resume.id = eh.resume_chapter_id AND resume.status = 'published'
  LEFT JOIN chapters furthest ON furthest.id = eh.furthest_chapter_id
  WHERE b.id IS NOT NULL OR sub.id IS NOT NULL OR eh.series_id IS NOT NULL
),
latest AS (
  SELECT DISTINCT ON (c.series_id)
    c.series_id,
    c.id AS latest_chapter_id,
    c.chapter_number::float8 AS latest_chapter_number,
    c.title AS latest_chapter_title,
    c.slug AS latest_chapter_slug,
    c.created_at AS latest_published_at
  FROM chapters c
  JOIN personal p ON p.series_id = c.series_id
  WHERE c.status = 'published'
  ORDER BY c.series_id, c.chapter_number DESC, c.id
),
first_published AS (
  SELECT DISTINCT ON (c.series_id)
    c.series_id,
    c.id AS first_chapter_id,
    c.chapter_number::float8 AS first_chapter_number,
    c.title AS first_chapter_title,
    c.slug AS first_chapter_slug
  FROM chapters c
  JOIN personal p ON p.series_id = c.series_id
  WHERE c.status = 'published'
  ORDER BY c.series_id, c.chapter_number ASC, c.id
),
chapter_stats AS (
  SELECT
    p.series_id,
    COUNT(c.id)::int AS published_chapter_count,
    COUNT(c.id) FILTER (
      WHERE p.furthest_chapter_number IS NULL
         OR c.chapter_number > p.furthest_chapter_number
    )::int AS unread_chapter_count
  FROM personal p
  LEFT JOIN chapters c
    ON c.series_id = p.series_id AND c.status = 'published'
  GROUP BY p.series_id, p.furthest_chapter_number
),
next_unread AS (
  SELECT DISTINCT ON (c.series_id)
    c.series_id,
    c.id AS next_chapter_id,
    c.chapter_number::float8 AS next_chapter_number,
    c.title AS next_chapter_title,
    c.slug AS next_chapter_slug
  FROM chapters c
  JOIN personal p ON p.series_id = c.series_id
  WHERE c.status = 'published'
    AND p.furthest_chapter_number IS NOT NULL
    AND c.chapter_number > p.furthest_chapter_number
  ORDER BY c.series_id, c.chapter_number ASC, c.id
),
base AS (
  SELECT
    p.*,
    COALESCE(n.next_chapter_id, p.resume_chapter_id, f.first_chapter_id) IS NOT NULL AS reading_available,
    CASE
      WHEN n.next_chapter_id IS NOT NULL THEN jsonb_build_object('kind','next','chapter_id',n.next_chapter_id,'chapter_slug',n.next_chapter_slug)
      WHEN p.resume_chapter_id IS NOT NULL THEN jsonb_build_object('kind','resume','chapter_id',p.resume_chapter_id,'chapter_slug',p.resume_chapter_slug)
      WHEN f.first_chapter_id IS NOT NULL THEN jsonb_build_object('kind','start','chapter_id',f.first_chapter_id,'chapter_slug',f.first_chapter_slug)
      ELSE NULL
    END AS reading_action,
    l.latest_chapter_id,
    l.latest_chapter_number,
    l.latest_chapter_title,
    l.latest_chapter_slug,
    l.latest_published_at,
    f.first_chapter_id,
    f.first_chapter_number,
    f.first_chapter_title,
    f.first_chapter_slug,
    n.next_chapter_id,
    n.next_chapter_number,
    n.next_chapter_title,
    n.next_chapter_slug,
    COALESCE(cs.published_chapter_count, 0)::int AS published_chapter_count,
    COALESCE(cs.unread_chapter_count, 0)::int AS unread_chapter_count,
    CASE
      WHEN NOT p.has_history AND p.furthest_chapter_id IS NULL THEN 'not_started'
      WHEN COALESCE(cs.unread_chapter_count, 0) > 0 THEN 'updates'
      ELSE 'caught_up'
    END AS read_state,
    GREATEST(
      COALESCE(p.read_at, 'epoch'::timestamptz),
      COALESCE(p.bookmark_created_at, 'epoch'::timestamptz),
      COALESCE(p.followed_at, 'epoch'::timestamptz)
    ) AS activity_at
  FROM personal p
  LEFT JOIN latest l ON l.series_id = p.series_id
  LEFT JOIN first_published f ON f.series_id = p.series_id
  LEFT JOIN chapter_stats cs ON cs.series_id = p.series_id
  LEFT JOIN next_unread n ON n.series_id = p.series_id
)
`;



export function registerRoutes(app: FastifyInstance, prisma: PrismaClient, redis: Redis): void {
  // ---------------- BOOKMARKS ----------------
  app.get("/api/social/bookmarks", async (request) => {
    const user = await requireUser(request, redis, config.sessionCookie);
    const q = request.query as Record<string, unknown>;
    const offset = asInt(q.offset, 0, 0, 1_000_000);
    const limit = asInt(q.limit, 20, 1, 100);
    const rows = await prisma.bookmark.findMany({
      where: { userId: user.user_id }, include: { series: true },
      orderBy: { createdAt: "desc" }, skip: offset, take: limit,
    });
    return rows.map((row) => ({
      id: row.id, series_id: row.seriesId, series_title: row.series.title,
      series_slug: row.series.slug, series_cover: row.series.coverImagePath,
      series_status: row.series.status, created_at: row.createdAt,
    }));
  });

  app.get("/api/social/bookmarks/:seriesId/status", async (request) => {
    const user = await requireUser(request, redis, config.sessionCookie);
    const { seriesId } = request.params as { seriesId: string };
    requireUuid(seriesId, "series_id");
    const row = await prisma.bookmark.findFirst({ where: { userId: user.user_id, seriesId }, select: { id: true } });
    return { bookmarked: row !== null };
  });

  app.post("/api/social/bookmarks/:seriesId", async (request, reply) => {
    const user = await requireUser(request, redis, config.sessionCookie);
    const { seriesId } = request.params as { seriesId: string };
    requireUuid(seriesId, "series_id");
    const series = await prisma.series.findUnique({ where: { id: seriesId } });
    if (!series) throw httpError(404, "Series not found.");
    let bookmark = await prisma.bookmark.findFirst({ where: { userId: user.user_id, seriesId } });
    const already = bookmark !== null;
    if (!bookmark) bookmark = await prisma.bookmark.create({ data: { userId: user.user_id, seriesId } });
    return reply.code(already ? 200 : 201).send({
      id: bookmark.id, series_id: seriesId, series_title: series.title,
      series_slug: series.slug, series_cover: series.coverImagePath,
      series_status: series.status, created_at: bookmark.createdAt,
    });
  });

  app.delete("/api/social/bookmarks/:seriesId", async (request, reply) => {
    const user = await requireUser(request, redis, config.sessionCookie);
    const { seriesId } = request.params as { seriesId: string };
    requireUuid(seriesId, "series_id");
    const row = await prisma.bookmark.findFirst({ where: { userId: user.user_id, seriesId } });
    if (!row) throw httpError(404, "Bookmark not found.");
    await prisma.bookmark.delete({ where: { id: row.id } });
    return reply.code(204).send();
  });

  // ---------------- SUBSCRIPTIONS ----------------
  app.get("/api/social/subscriptions", async (request) => {
    const user = await requireUser(request, redis, config.sessionCookie);
    const q = request.query as Record<string, unknown>;
    const offset = asInt(q.offset, 0, 0, 1_000_000);
    const limit = asInt(q.limit, 20, 1, 100);
    const rows = await prisma.subscription.findMany({
      where: { userId: user.user_id }, include: { series: true },
      orderBy: { createdAt: "desc" }, skip: offset, take: limit,
    });
    return Promise.all(rows.map(async (row) => ({
      id: row.id, series_id: row.seriesId, series_title: row.series.title,
      series_slug: row.series.slug, series_cover: row.series.coverImagePath,
      series_status: row.series.status,
      unread_count: await prisma.notification.count({ where: { userId: user.user_id, seriesId: row.seriesId, isRead: false } }),
      created_at: row.createdAt,
    })));
  });

  app.get("/api/social/subscriptions/:seriesId/status", async (request) => {
    const user = await requireUser(request, redis, config.sessionCookie);
    const { seriesId } = request.params as { seriesId: string };
    requireUuid(seriesId, "series_id");
    const row = await prisma.subscription.findFirst({ where: { userId: user.user_id, seriesId }, select: { id: true } });
    return { subscribed: row !== null };
  });

  app.post("/api/social/subscriptions/:seriesId", async (request, reply) => {
    const user = await requireUser(request, redis, config.sessionCookie);
    const { seriesId } = request.params as { seriesId: string };
    requireUuid(seriesId, "series_id");
    const series = await prisma.series.findUnique({ where: { id: seriesId } });
    if (!series) throw httpError(404, "Series not found.");
    let row = await prisma.subscription.findFirst({ where: { userId: user.user_id, seriesId } });
    const already = row !== null;
    if (!row) row = await prisma.subscription.create({ data: { userId: user.user_id, seriesId } });
    return reply.code(already ? 200 : 201).send({
      id: row.id, series_id: seriesId, series_title: series.title,
      series_slug: series.slug, series_cover: series.coverImagePath,
      // Stable Python subscribe response returns zero; the list endpoint computes
      // the actual unread count for each subscription.
      series_status: series.status, unread_count: 0, created_at: row.createdAt,
    });
  });

  app.delete("/api/social/subscriptions/:seriesId", async (request, reply) => {
    const user = await requireUser(request, redis, config.sessionCookie);
    const { seriesId } = request.params as { seriesId: string };
    requireUuid(seriesId, "series_id");
    const row = await prisma.subscription.findFirst({ where: { userId: user.user_id, seriesId } });
    if (!row) throw httpError(404, "Subscription not found.");
    await prisma.subscription.delete({ where: { id: row.id } });
    return reply.code(204).send();
  });


  // ---------------- SMART LIBRARY ----------------
  app.get("/api/social/library", async (request) => {
    const user = await requireUser(request, redis, config.sessionCookie);
    const q = request.query as Record<string, unknown>;
    const scope = enumQuery<SmartLibraryScope>(
      q.scope, "all", ["all", "bookmarks", "following", "history"], "scope",
    );
    const state = enumQuery<SmartLibraryState>(
      q.state, "all", ["all", "updates", "caught_up", "not_started"], "state",
    );
    const sort = enumQuery<SmartLibrarySort>(
      q.sort, "activity", ["activity", "updated", "unread", "title"], "sort",
    );
    const offset = asInt(q.offset, 0, 0, 1_000_000);
    const limit = asInt(q.limit, 48, 1, 100);

    const scopeClause: Record<SmartLibraryScope, string> = {
      all: "TRUE",
      bookmarks: "bookmarked",
      following: "followed",
      history: "has_history",
    };
    const stateClause: Record<SmartLibraryState, string> = {
      all: "TRUE",
      updates: "read_state = 'updates'",
      caught_up: "read_state = 'caught_up'",
      not_started: "read_state = 'not_started'",
    };
    const sortClause: Record<SmartLibrarySort, string> = {
      activity: "activity_at DESC, series_title ASC, series_id ASC",
      updated: "latest_published_at DESC NULLS LAST, series_title ASC, series_id ASC",
      unread: "unread_chapter_count DESC, latest_published_at DESC NULLS LAST, series_title ASC, series_id ASC",
      title: "series_title ASC, activity_at DESC, series_id ASC",
    };
    const filterSql = `(${scopeClause[scope]}) AND (${stateClause[state]})`;

    type SmartLibrarySummary = {
      all_count: number;
      bookmark_count: number;
      following_count: number;
      history_count: number;
      updates_count: number;
      caught_up_count: number;
      not_started_count: number;
      filtered_total: number;
    };
    type SmartLibraryEnvelope = {
      summary: SmartLibrarySummary;
      generated_at: Date;
      recent_items: Array<Record<string, unknown>>;
      items: Array<Record<string, unknown>>;
    };

    // Base is referenced by both summary and page selection inside ONE SQL
    // statement. PostgreSQL can materialize/reuse it instead of reconstructing
    // the complete personal library in two separate round trips.
    const rows = await prisma.$queryRawUnsafe<SmartLibraryEnvelope[]>(
      `${SMART_LIBRARY_BASE_SQL},
       summary AS MATERIALIZED (
         SELECT
           COUNT(*)::int AS all_count,
           COUNT(*) FILTER (WHERE bookmarked)::int AS bookmark_count,
           COUNT(*) FILTER (WHERE followed)::int AS following_count,
           COUNT(*) FILTER (WHERE has_history)::int AS history_count,
           COUNT(*) FILTER (WHERE read_state = 'updates')::int AS updates_count,
           COUNT(*) FILTER (WHERE read_state = 'caught_up')::int AS caught_up_count,
           COUNT(*) FILTER (WHERE read_state = 'not_started')::int AS not_started_count,
           COUNT(*) FILTER (WHERE ${filterSql})::int AS filtered_total
         FROM base
       ),
       paged AS MATERIALIZED (
         SELECT base.*,
                ROW_NUMBER() OVER (ORDER BY ${sortClause[sort]}) AS _row_order
         FROM base
         WHERE ${filterSql}
         ORDER BY ${sortClause[sort]}
         LIMIT $2 OFFSET $3
       ),
       recent AS MATERIALIZED (
         SELECT base.*, ROW_NUMBER() OVER (ORDER BY read_at DESC NULLS LAST, series_id) AS _row_order
         FROM base WHERE has_history
         ORDER BY read_at DESC NULLS LAST, series_id
         LIMIT 12
       )
       SELECT
         statement_timestamp() AS generated_at,
         COALESCE((SELECT jsonb_agg(to_jsonb(recent) - '_row_order' ORDER BY recent._row_order) FROM recent), '[]'::jsonb) AS recent_items,
         jsonb_build_object(
           'all_count', summary.all_count,
           'bookmark_count', summary.bookmark_count,
           'following_count', summary.following_count,
           'history_count', summary.history_count,
           'updates_count', summary.updates_count,
           'caught_up_count', summary.caught_up_count,
           'not_started_count', summary.not_started_count,
           'filtered_total', summary.filtered_total
         ) AS summary,
         COALESCE((
           SELECT jsonb_agg(to_jsonb(paged) - '_row_order' ORDER BY paged._row_order)
           FROM paged
         ), '[]'::jsonb) AS items
       FROM summary`,
      user.user_id,
      limit,
      offset,
    );

    const envelope = rows[0];
    if (!envelope?.summary || !Array.isArray(envelope.items) || !Array.isArray(envelope.recent_items)) {
      throw httpError(503, "Library state is unavailable.");
    }
    const summary = envelope.summary;
    const items = envelope.items;

    return {
      contract_version: 1,
      generated_at: envelope.generated_at.toISOString(),
      request_identity: { scope, state, sort, offset, limit },
      recently_opened: { items: envelope.recent_items, total: Number(summary.history_count) },
      items,
      total: Number(summary.filtered_total),
      offset,
      limit,
      has_more: offset + items.length < Number(summary.filtered_total),
      summary: {
        all: Number(summary.all_count),
        bookmarks: Number(summary.bookmark_count),
        following: Number(summary.following_count),
        history: Number(summary.history_count),
        updates: Number(summary.updates_count),
        caught_up: Number(summary.caught_up_count),
        not_started: Number(summary.not_started_count),
      },
    };
  });

  // ---------------- SERIES SOCIAL METRICS / RATINGS ----------------
  app.get("/api/social/series/:seriesId/viewer-state", async (request) => {
    const { seriesId } = request.params as { seriesId: string };
    requireUuid(seriesId, "series_id");
    const session = await sessionFromRequest(request, redis, config.sessionCookie);
    return viewerStateForSeries(prisma, seriesId, session?.user_id);
  });

  app.post("/api/social/series/metrics-batch", async (request) => {
    const body = (request.body ?? {}) as Record<string, unknown>;
    const ids = Array.isArray(body.series_ids)
      ? body.series_ids.filter((value): value is string => typeof value === "string")
      : [];
    const uniqueIds = [...new Set(ids)].slice(0, 100);
    if (uniqueIds.some((value) => !validUuid(value))) {
      throw httpError(400, "Invalid series id in batch.");
    }
    if (uniqueIds.length === 0) return { items: [] };
    // Aggregate series metrics are public product data. Do not make an
    // anonymous card/grid depend on Redis session lookup; personal state is
    // served separately by viewer-state and mutation responses.
    const items = await metricsForSeriesBatch(prisma, uniqueIds);
    return { items };
  });

  app.get("/api/social/series/:seriesId/metrics", async (request) => {
    const { seriesId } = request.params as { seriesId: string };
    requireUuid(seriesId, "series_id");
    // Keep this endpoint strictly public and session-independent so guests can
    // always see aggregate bookmarks/followers/ratings when Social is healthy.
    return metricsForSeries(prisma, seriesId);
  });

  app.put("/api/social/series/:seriesId/rating", async (request) => {
    const user = await requireUser(request, redis, config.sessionCookie);
    const { seriesId } = request.params as { seriesId: string };
    requireUuid(seriesId, "series_id");
    const body = (request.body ?? {}) as Record<string, unknown>;
    const rating = Number(body.rating);
    if (!Number.isInteger(rating) || rating < 1 || rating > 5) throw httpError(422, "Rating must be an integer from 1 to 5.");
    const series = await prisma.series.findUnique({ where: { id: seriesId }, select: { id: true } });
    if (!series) throw httpError(404, "Series not found.");
    await prisma.seriesRating.upsert({
      where: { userId_seriesId: { userId: user.user_id, seriesId } },
      create: { userId: user.user_id, seriesId, rating },
      update: { rating },
    });
    return metricsForSeries(prisma, seriesId, user.user_id);
  });

  app.delete("/api/social/series/:seriesId/rating", async (request, reply) => {
    const user = await requireUser(request, redis, config.sessionCookie);
    const { seriesId } = request.params as { seriesId: string };
    requireUuid(seriesId, "series_id");
    await prisma.seriesRating.deleteMany({ where: { userId: user.user_id, seriesId } });
    return reply.code(204).send();
  });

  // ---------------- COMMENTS ----------------
  app.get("/api/social/comments", async (request) => {
    const q = request.query as Record<string, unknown>;
    const seriesId = typeof q.seriesId === "string" ? q.seriesId : undefined;
    const chapterId = typeof q.chapterId === "string" ? q.chapterId : undefined;
    const offset = asInt(q.offset, 0, 0, 1_000_000);
    const limit = asInt(q.limit, 50, 1, 100);
    if (!seriesId && !chapterId) throw httpError(400, "Provide a seriesId or chapterId to load comments.");
    if (seriesId) requireUuid(seriesId, "seriesId");
    if (chapterId) requireUuid(chapterId, "chapterId");
    // A series-only discussion is distinct from chapter discussions.  When a
    // caller provides seriesId without chapterId, return only comments whose
    // chapterId is NULL instead of every chapter comment in the series.
    const where = chapterId
      ? { ...(seriesId ? { seriesId } : {}), chapterId }
      : seriesId
        ? { seriesId, chapterId: null }
        : {};
    const [total, rows] = await Promise.all([
      prisma.comment.count({ where }),
      prisma.comment.findMany({ where, include: { user: true }, orderBy: { createdAt: "asc" }, skip: offset, take: limit }),
    ]);
    return { items: rows.map(commentResponse), total, offset, limit };
  });



  app.post("/api/social/comments", async (request, reply) => {
    const user = await requireUser(request, redis, config.sessionCookie);
    const body = (request.body ?? {}) as Record<string, unknown>;
    let seriesId = typeof body.series_id === "string" && body.series_id ? body.series_id : null;
    const chapterId = typeof body.chapter_id === "string" && body.chapter_id ? body.chapter_id : null;
    const parentId = typeof body.parent_id === "string" && body.parent_id ? body.parent_id : null;
    const content = typeof body.content === "string" ? body.content.trim() : "";

    if (!seriesId && !chapterId) {
      throw httpError(400, "Provide a series_id or chapter_id for the comment.");
    }
    if (seriesId) requireUuid(seriesId, "series_id");
    if (chapterId) requireUuid(chapterId, "chapter_id");
    if (parentId) requireUuid(parentId, "parent_id");
    if (!content) throw httpError(422, "Comment cannot be empty.");
    if (content.length > 2000) throw httpError(422, "Comment is too long.");

    if (chapterId) {
      const chapter = await prisma.chapter.findUnique({
        where: { id: chapterId },
        select: { seriesId: true },
      });
      if (!chapter) throw httpError(404, "Chapter not found.");
      if (seriesId && chapter.seriesId !== seriesId) {
        throw httpError(400, "Chapter does not belong to the selected series.");
      }
      seriesId = chapter.seriesId;
    } else {
      const series = await prisma.series.findUnique({
        where: { id: seriesId! },
        select: { id: true },
      });
      if (!series) throw httpError(404, "Series not found.");
    }

    if (parentId) await commentDepth(prisma, parentId, seriesId!, chapterId);
    const created = await prisma.comment.create({
      data: { userId: user.user_id, seriesId: seriesId!, chapterId, parentId, content },
      include: { user: true },
    });
    const response = commentResponse(created);
    await publishCommentEvent(redis, seriesId!, chapterId, { type: "created", comment: response });
    return reply.code(201).send(response);
  });

  app.delete("/api/social/comments/:commentId", async (request, reply) => {
    const user = await requireUser(request, redis, config.sessionCookie);
    const { commentId } = request.params as { commentId: string };
    requireUuid(commentId, "comment_id");
    const comment = await prisma.comment.findFirst({ where: { id: commentId, userId: user.user_id } });
    if (!comment) throw httpError(404, "Comment not found.");
    await prisma.comment.delete({ where: { id: commentId } });
    await publishCommentEvent(redis, comment.seriesId, comment.chapterId, { type: "deleted", comment_id: commentId });
    return reply.code(204).send();
  });

  // ---------------- NOTIFICATIONS ----------------
  app.get("/api/notifications", async (request) => {
    const user = await requireUser(request, redis, config.sessionCookie);
    const q = request.query as Record<string, unknown>;
    const unreadOnly = q.unread_only === true || q.unread_only === "true";
    const offset = asInt(q.offset, 0, 0, 1_000_000);
    const limit = asInt(q.limit, 30, 1, 100);
    const rows = await prisma.notification.findMany({
      where: { userId: user.user_id, ...(unreadOnly ? { isRead: false } : {}) },
      include: { series: true, chapter: true }, orderBy: { createdAt: "desc" }, skip: offset, take: limit,
    });
    return rows.map((row) => ({
      id: row.id, kind: row.kind,
      series_id: row.seriesId, chapter_id: row.chapterId,
      message: row.message, is_read: row.isRead, created_at: row.createdAt,
      series_title: row.series?.title ?? null, series_slug: row.series?.slug ?? null,
      chapter_number: row.chapter ? Number(row.chapter.chapterNumber) : null,
      chapter_slug: row.chapter?.slug ?? null,
    }));
  });

  app.get("/api/notifications/count", async (request) => {
    const user = await requireUser(request, redis, config.sessionCookie);
    return { unread: await prisma.notification.count({ where: { userId: user.user_id, isRead: false } }) };
  });

  app.post("/api/notifications/:notificationId/read", async (request) => {
    const user = await requireUser(request, redis, config.sessionCookie);
    const { notificationId } = request.params as { notificationId: string };
    if (!validUuid(notificationId)) throw httpError(404, "Notification not found.");
    const row = await prisma.notification.findFirst({ where: { id: notificationId, userId: user.user_id } });
    if (!row) throw httpError(404, "Notification not found.");
    await prisma.notification.update({ where: { id: row.id }, data: { isRead: true } });
    return { marked: true };
  });

  app.post("/api/notifications/read-all", async (request) => {
    const user = await requireUser(request, redis, config.sessionCookie);
    const result = await prisma.notification.updateMany({ where: { userId: user.user_id, isRead: false }, data: { isRead: true } });
    return { marked: result.count };
  });

  app.get("/api/notifications/admin/stats", async (request) => {
    await requireAdmin(request, redis, config.sessionCookie);
    const [notificationCount, readCount, unreadCount] = await Promise.all([
      prisma.notification.count(),
      prisma.notification.count({ where: { isRead: true } }),
      prisma.notification.count({ where: { isRead: false } }),
    ]);
    return {
      notification_count: notificationCount,
      read_count: readCount,
      unread_count: unreadCount,
      retention: {
        read_days: config.notificationRetentionReadDays,
        unread_days: config.notificationRetentionUnreadDays,
        sweep_hours: config.notificationRetentionSweepHours,
      },
    };
  });

  app.post("/api/notifications/admin/retention/sweep", async (request) => {
    await requireAdmin(request, redis, config.sessionCookie);
    const result = await sweepExpiredNotifications(prisma, {
      readDays: config.notificationRetentionReadDays,
      unreadDays: config.notificationRetentionUnreadDays,
      batchSize: config.notificationRetentionBatchSize,
      maxBatches: config.notificationRetentionMaxBatches,
    });
    return {
      policy: {
        read_days: config.notificationRetentionReadDays,
        unread_days: config.notificationRetentionUnreadDays,
      },
      ...result,
    };
  });
}
