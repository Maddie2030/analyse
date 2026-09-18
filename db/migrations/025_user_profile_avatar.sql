-- Fixed themed avatar selection. Stored values are keys, never arbitrary URLs/uploads.
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS avatar_key VARCHAR(32) NOT NULL DEFAULT 'skull';

UPDATE users
SET avatar_key = 'skull'
WHERE avatar_key IS NULL OR avatar_key = '';

ALTER TABLE users
    DROP CONSTRAINT IF EXISTS ck_users_avatar_key;
ALTER TABLE users
    ADD CONSTRAINT ck_users_avatar_key CHECK (
        avatar_key IN ('skull','blade','moon','flame','crown','spirit')
    );
