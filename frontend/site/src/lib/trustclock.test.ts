import { describe, expect, it } from 'vitest';
import { withExpectedRange } from './trustclock';

describe('withExpectedRange', () => {
  it('alarms on a move beyond 3x the normal wobble, and only there', () => {
    const days = withExpectedRange([94, 94.5, 94, 94.5, 94, 94.5, 87, 87.4]);
    expect(days.filter(d => d.alarm).map(d => d.day)).toEqual([7]);
    expect(days[6].alarm).toContain('-7.5 points');
  });

  it('treats an equally big jump up as an alarm too', () => {
    const days = withExpectedRange([80, 80.4, 80, 80.4, 88]);
    expect(days[4].alarm).toBeDefined();
  });

  it('does not let an alarm widen the range of the days after it', () => {
    const days = withExpectedRange([94, 94.5, 94, 94.5, 94, 94.5, 87, 87.4, 87.1]);
    expect(days[7].high - days[7].low).toBeCloseTo(days[6].high - days[6].low);
    expect(days.slice(7).every(d => !d.alarm)).toBe(true);
  });

  it('never alarms on the first day', () => {
    expect(withExpectedRange([50])[0].alarm).toBeUndefined();
  });
});
