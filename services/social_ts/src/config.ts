function portEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) return fallback;
  if (!/^\d+$/.test(raw)) return fallback;
  const value = Number(raw);
  return Number.isInteger(value) && value >= 1 && value <= 65535 ? value : fallback;
}

function intEnv(name: string, fallback: number, min: number, max: number): number {
  const value = Number(process.env[name] ?? fallback);
  if (!Number.isInteger(value) || value < min || value > max) return fallback;
  return value;
}

function upsertQueryParam(value: string, name: string, parameterValue: number, force: boolean): string {
  const pattern = new RegExp(`([?&])${name}=[^&]*`);
  if (pattern.test(value)) {
    return force ? value.replace(pattern, `$1${name}=${parameterValue}`) : value;
  }
  return `${value}${value.includes("?") ? "&" : "?"}${name}=${parameterValue}`;
}

function databaseUrl(): string {
  let value = process.env.SOCIAL_DATABASE_URL?.trim();
  if (!value) {
    throw new Error("SOCIAL_DATABASE_URL is required");
  }

  const connectionLimit = intEnv("SOCIAL_DB_CONNECTION_LIMIT", 8, 1, 64);
  const poolTimeout = intEnv("SOCIAL_DB_POOL_TIMEOUT", 10, 1, 120);
  value = upsertQueryParam(value, "connection_limit", connectionLimit, process.env.SOCIAL_DB_CONNECTION_LIMIT !== undefined);
  value = upsertQueryParam(value, "pool_timeout", poolTimeout, process.env.SOCIAL_DB_POOL_TIMEOUT !== undefined);
  return value;
}

export const config = {
  port: portEnv("SOCIAL_TS_PORT", 8080),
  databaseUrl: databaseUrl(),
  redisUrl: process.env.REDIS_URL ?? "redis://redis:6379/0",
  sessionCookie: process.env.SESSION_COOKIE_NAME ?? "session_id",
  notificationRetentionReadDays: intEnv("NOTIFICATION_RETENTION_READ_DAYS", 14, 1, 3650),
  notificationRetentionUnreadDays: intEnv("NOTIFICATION_RETENTION_UNREAD_DAYS", 30, 1, 3650),
  notificationRetentionSweepHours: intEnv("NOTIFICATION_RETENTION_SWEEP_HOURS", 24, 1, 168),
  notificationRetentionBatchSize: intEnv("NOTIFICATION_RETENTION_BATCH_SIZE", 5000, 100, 50000),
  notificationRetentionMaxBatches: intEnv("NOTIFICATION_RETENTION_MAX_BATCHES", 20, 1, 1000),
};
