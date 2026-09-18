export const AVATAR_OPTIONS = [
  { key: 'bard', label: 'Bard', description: 'Songs, support and travelling-story energy.' },
  { key: 'cleric', label: 'Cleric', description: 'Calm, faithful and temple-guarded resolve.' },
  { key: 'fire_wielder', label: 'Fire Wielder', description: 'Explosive magic and burning combat focus.' },
  { key: 'king', label: 'King', description: 'Royal instinct, command and ruling presence.' },
  { key: 'paladin', label: 'Paladin', description: 'Holy armor, discipline and frontline courage.' },
  { key: 'shadow_rogue', label: 'Shadow Rogue', description: 'Stealth, night hunts and dangerous precision.' },
  { key: 'sorcerer', label: 'Sorcerer', description: 'Arcane mystery, starlight and hidden power.' },
  { key: 'swordsman', label: 'Swordsman', description: 'Blade mastery, focus and clean striking force.' },
] as const;

export type AvatarKey = 'skull' | typeof AVATAR_OPTIONS[number]['key'];

const AVATAR_KEYS = new Set<string>(['skull', ...AVATAR_OPTIONS.map((item) => item.key)]);

export function normalizeAvatarKey(value?: string | null): AvatarKey {
  return value && AVATAR_KEYS.has(value) ? value as AvatarKey : 'skull';
}

export function avatarSrc(value?: string | null): string {
  return `/avatars/${normalizeAvatarKey(value)}.webp`;
}
