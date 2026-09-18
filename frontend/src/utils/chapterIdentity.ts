export const chapterSlugFromNumber = (value: string | number): string => {
  const raw = String(value).trim();
  if (!/^\d+(?:\.\d+)?$/.test(raw)) return '';

  const [wholeRaw, fractionRaw = ''] = raw.split('.');
  const whole = wholeRaw.replace(/^0+(?=\d)/, '') || '0';
  const fraction = fractionRaw.replace(/0+$/, '');
  const canonical = fraction ? `${whole}.${fraction}` : whole;

  return `ch-${canonical.replace('.', '-')}`;
};
