import Fastify from "fastify";
import cookie from "@fastify/cookie";
import { PrismaClient } from "@prisma/client";
import { Redis } from "ioredis";
import { config } from "./config.js";
import { registerRoutes } from "./routes.js";
import { sweepExpiredNotifications } from "./maintenance.js";

process.env.SOCIAL_DATABASE_URL = config.databaseUrl;

const app = Fastify({
  logger: {
    level: process.env.LOG_LEVEL ?? "info",
  },
  disableRequestLogging: true,
});

await app.register(cookie);

// Compatibility with the established Python Social HTTP contract:
// several action endpoints are bodyless POSTs. Browsers/older frontend builds
// can still send `Content-Type: application/json` with Content-Length: 0.
// Fastify's stock JSON parser rejects that before the route is reached, so
// accept an empty JSON body as an empty object while keeping malformed non-empty
// JSON as a normal 400 error.
app.removeContentTypeParser("application/json");
app.addContentTypeParser(
  "application/json",
  { parseAs: "string" },
  (_request, body, done) => {
    const value = String(body ?? "").trim();
    if (!value) {
      done(null, {});
      return;
    }
    try {
      done(null, JSON.parse(value));
    } catch (error) {
      const err = new Error("Invalid JSON body.") as Error & { statusCode?: number };
      err.statusCode = 400;
      done(err);
    }
  },
);

const prisma = new PrismaClient();
const redis = new Redis(config.redisUrl, {
  maxRetriesPerRequest: 2,
  enableReadyCheck: true,
});

app.addHook("onRequest", async (request) => {
  request.log.info(
    {
      request_id: request.id,
      method: request.method,
      path: request.url,
    },
    "request started",
  );
});

app.addHook("onResponse", async (request, reply) => {
  request.log.info(
    {
      request_id: request.id,
      method: request.method,
      path: request.url,
      status: reply.statusCode,
      response_time_ms: reply.elapsedTime,
    },
    "request completed",
  );
});

app.get("/health", async () => ({
  status: "ok",
  service: "social-ts",
  mode: "primary-capable",
}));

app.get("/health/ready", async (_request, reply) => {
  try {
    await Promise.all([
      prisma.$queryRawUnsafe("SELECT 1"),
      redis.ping(),
    ]);
    return {
      status: "ok",
      service: "social-ts",
      dependencies: {
        postgres: { ok: true },
        valkey: { ok: true },
      },
    };
  } catch (error) {
    app.log.error({ error }, "readiness failed");
    return reply.code(503).send({
      status: "degraded",
      service: "social-ts",
    });
  }
});

registerRoutes(app, prisma, redis);

app.setErrorHandler((error, _request, reply) => {
  const statusCode =
    typeof (error as { statusCode?: unknown }).statusCode === "number"
      ? (error as { statusCode: number }).statusCode
      : 500;

  if (statusCode >= 500) {
    app.log.error({ err: error }, "request failed");
  }

  reply.code(statusCode).send({
    detail:
      statusCode >= 500
        ? "Internal server error"
        : error instanceof Error
          ? error.message
          : String(error),
  });
});

let notificationRetentionTimer: NodeJS.Timeout | undefined;

const runNotificationRetention = async () => {
  try {
    const result = await sweepExpiredNotifications(prisma, {
      readDays: config.notificationRetentionReadDays,
      unreadDays: config.notificationRetentionUnreadDays,
      batchSize: config.notificationRetentionBatchSize,
      maxBatches: config.notificationRetentionMaxBatches,
    });

    app.log.info(
      {
        event: "notification_retention_sweep",
        read_retention_days: config.notificationRetentionReadDays,
        unread_retention_days: config.notificationRetentionUnreadDays,
        ...result,
      },
      "notification retention sweep completed",
    );
  } catch (error) {
    // Retention cleanup must never take the API offline. A later scheduled
    // sweep will retry automatically.
    app.log.error({ error }, "notification retention sweep failed");
  }
};

const shutdown = async () => {
  if (notificationRetentionTimer) clearInterval(notificationRetentionTimer);
  await app.close();
  redis.disconnect();
  await prisma.$disconnect();
};

process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);

await app.listen({
  port: config.port,
  host: "0.0.0.0",
});

// Run once after the API is listening, then enforce retention periodically.
// The timer is unref'd so it never prevents graceful process shutdown.
void runNotificationRetention();
notificationRetentionTimer = setInterval(
  () => void runNotificationRetention(),
  config.notificationRetentionSweepHours * 60 * 60 * 1000,
);
notificationRetentionTimer.unref();
