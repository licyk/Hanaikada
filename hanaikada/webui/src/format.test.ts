import { describe, expect, it } from 'vitest';
import { formatDuration } from '@/format';

describe('formatDuration', () => {
  it('writes minutes and seconds, and hours past one', () => {
    expect(formatDuration(4.6)).toBe('0:05');
    expect(formatDuration(750)).toBe('12:30');
    expect(formatDuration(3723)).toBe('1:02:03');
    expect(formatDuration(-1)).toBe('0:00');
  });
});
