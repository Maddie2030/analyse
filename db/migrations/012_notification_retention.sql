-- Efficient global retention scans for the Social TypeScript maintenance job.
CREATE INDEX IF NOT EXISTS ix_notifications_retention
    ON notifications (is_read, created_at);
