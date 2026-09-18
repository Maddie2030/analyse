-- RC4.32: any backup request left in running state across an upgrade/restart
-- no longer has a live worker.  Mark it failed once so the admin can retry;
-- verified NAS artifacts remain untouched and retention handles them normally.

UPDATE backup_requests
SET status = 'failed',
    completed_at = COALESCE(completed_at, now()),
    error = COALESCE(error, 'Backup worker restarted before request bookkeeping completed; request a new manual backup.'),
    metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object('recovered_by_release', 'v1.3.0-rc4.36')
WHERE status = 'running';
