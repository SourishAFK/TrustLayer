export type Day = { day: number; value: number; low: number; high: number; alarm?: string };

/**
 * The Trust Clock rule: today's expected range is yesterday's value plus or minus 3x the
 * normal day-to-day wobble (mean absolute move over the last `window` normal days).
 * A value outside that range raises an alarm. Alarm moves are not "normal", so they never
 * widen the range that follows them.
 */
export function withExpectedRange(values: number[], window = 7): Day[] {
  const normal: number[] = [];
  return values.map((value, i) => {
    const recent = normal.slice(-window);
    const wobble = recent.length ? recent.reduce((sum, m) => sum + m, 0) / recent.length : 0.5;
    const previous = i ? values[i - 1] : value;
    const low = previous - 3 * wobble, high = previous + 3 * wobble;
    const alarm = i > 0 && (value < low || value > high)
      ? `Moved ${(value - previous).toFixed(1)} points overnight, more than 3× the normal wobble (±${wobble.toFixed(1)}).`
      : undefined;
    if (i > 0 && !alarm) normal.push(Math.abs(value - previous));
    return { day: i + 1, value, low, high, alarm };
  });
}
