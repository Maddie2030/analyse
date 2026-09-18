-- RC4.75: replace the themed avatar set while retaining the default skull.
-- Existing removed selections are mapped to the default so no user is left with
-- an avatar key that the web/mobile clients or Auth validator no longer accept.
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

ALTER TABLE users
    DROP CONSTRAINT IF EXISTS ck_users_avatar_key;

ALTER TABLE users
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
