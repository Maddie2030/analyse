import type { PrismaClient } from "@prisma/client";

export type NotificationRetentionOptions = {
  readDays: number;
  unreadDays: number;
  batchSize: number;
  maxBatches: number;
};

export type NotificationRetentionResult = {
  lock_acquired: boolean;
  deleted_total: number;
  deleted_read: number;
  deleted_unread: number;
  batches: number;
  capped: boolean;
};

type RetentionBatchRow = {
  acquired: boolean;
  deleted_total: number;
  deleted_read: number;
  deleted_unread: number;
};

/**
 * Delete expired notification rows in bounded transactions.
 *
 * Read notifications expire after readDays from delivery (created_at).
 * Unread notifications expire after unreadDays from delivery (created_at).
 *
 * The transaction-scoped advisory lock prevents horizontally-scaled Social TS
 * instances from running the same batch concurrently. The job is idempotent,
 * and each batch is intentionally small to avoid long table locks/WAL spikes.
 */
export async function sweepExpiredNotifications(
  prisma: PrismaClient,
  options: NotificationRetentionOptions,
): Promise<NotificationRetentionResult> {
  let deletedTotal = 0;
  let deletedRead = 0;
  let deletedUnread = 0;
  let batches = 0;
  let lockAcquired = false;

  for (let batch = 0; batch < options.maxBatches; batch += 1) {
    const rows = await prisma.$queryRaw<RetentionBatchRow[]>`
      WITH lock_guard AS (
        SELECT pg_try_advisory_xact_lock(
          hashtextextended('mreader:social:notification-retention', 0)
        ) AS acquired
      ),
      victims AS (
        SELECT n.ctid
        FROM notifications n
        CROSS JOIN lock_guard l
        WHERE l.acquired
          AND (
            (
              n.is_read = TRUE
              AND n.created_at < NOW() - make_interval(days => ${options.readDays}::int)
            )
            OR
            (
              n.is_read = FALSE
              AND n.created_at < NOW() - make_interval(days => ${options.unreadDays}::int)
            )
          )
        ORDER BY n.created_at ASC
        LIMIT ${options.batchSize}
      ),
      deleted AS (
        DELETE FROM notifications n
        USING victims v
        WHERE n.ctid = v.ctid
        RETURNING n.is_read
      )
      SELECT
        (SELECT acquired FROM lock_guard) AS acquired,
        COUNT(*)::int AS deleted_total,
        COUNT(*) FILTER (WHERE is_read = TRUE)::int AS deleted_read,
        COUNT(*) FILTER (WHERE is_read = FALSE)::int AS deleted_unread
      FROM deleted
    `;

    const result = rows[0] ?? {
      acquired: false,
      deleted_total: 0,
      deleted_read: 0,
      deleted_unread: 0,
    };

    if (!result.acquired) {
      return {
        lock_acquired: false,
        deleted_total: deletedTotal,
        deleted_read: deletedRead,
        deleted_unread: deletedUnread,
        batches,
        capped: false,
      };
    }

    lockAcquired = true;
    batches += 1;
    deletedTotal += Number(result.deleted_total ?? 0);
    deletedRead += Number(result.deleted_read ?? 0);
    deletedUnread += Number(result.deleted_unread ?? 0);

    if (Number(result.deleted_total ?? 0) < options.batchSize) {
      return {
        lock_acquired: lockAcquired,
        deleted_total: deletedTotal,
        deleted_read: deletedRead,
        deleted_unread: deletedUnread,
        batches,
        capped: false,
      };
    }
  }

  return {
    lock_acquired: lockAcquired,
    deleted_total: deletedTotal,
    deleted_read: deletedRead,
    deleted_unread: deletedUnread,
    batches,
    capped: true,
  };
}
