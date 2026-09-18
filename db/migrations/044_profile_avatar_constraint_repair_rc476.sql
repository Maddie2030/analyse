-- RC4.76: repair legacy avatar constraints left by old fresh-install schemas.
-- Older databases can contain BOTH users_avatar_key_check (from db/init.sql)
-- and ck_users_avatar_key (from migration 025). RC4.75 only replaced the latter,
-- so new profile avatars could still fail with PostgreSQL CHECK violations / HTTP 500.

-- First normalize any removed/unknown values while the old constraints still accept
-- the legacy values. This guarantees the final constraint can be installed safely.
UPDATE users
SET avatar_key = 'skull'
WHERE avatar_key IS NULL
   OR avatar_key = ''
   OR avatar_key NOT IN (
       'skull',
       'bard',
       'cleric',
       'fire_wielder',
       'king',
       'paladin',
       'shadow_rogue',
       'sorcerer',
       'swordsman'
   );

-- Drop every CHECK constraint on public.users that references avatar_key. This
-- catches both the historical inline constraint and explicitly named variants.
DO $$
DECLARE
    constraint_row RECORD;
BEGIN
    FOR constraint_row IN
        SELECT c.conname
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = 'public'
          AND t.relname = 'users'
          AND c.contype = 'c'
          AND pg_get_constraintdef(c.oid) ILIKE '%avatar_key%'
    LOOP
        EXECUTE format('ALTER TABLE public.users DROP CONSTRAINT IF EXISTS %I', constraint_row.conname);
    END LOOP;
END
$$;

ALTER TABLE public.users
    ADD CONSTRAINT ck_users_avatar_key CHECK (
        avatar_key IN (
            'skull',
            'bard',
            'cleric',
            'fire_wielder',
            'king',
            'paladin',
            'shadow_rogue',
            'sorcerer',
            'swordsman'
        )
    );
