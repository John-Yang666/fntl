import { describe, expect, it } from 'vitest';
import {
  BACKGROUND_LAUNCH_ARGUMENT,
  buildWatchdogTaskArguments,
  consumeRelaunchAttempt,
  isBackgroundLaunch,
  RecoveryThrottle,
  shouldRecoverRenderer,
  WATCHDOG_TASK_NAME,
} from './recovery';

describe('desktop recovery helpers', () => {
  it('detects watchdog background launches', () => {
    expect(isBackgroundLaunch(['client.exe', BACKGROUND_LAUNCH_ARGUMENT])).toBe(true);
    expect(isBackgroundLaunch(['client.exe'])).toBe(false);
  });

  it('limits renderer recovery attempts inside a rolling window', () => {
    const throttle = new RecoveryThrottle(2, 1_000);
    expect(throttle.consume(1_000)).toBe(true);
    expect(throttle.consume(1_500)).toBe(true);
    expect(throttle.consume(1_999)).toBe(false);
    expect(throttle.consume(2_001)).toBe(true);
  });

  it('persists only recent main-process relaunch attempts', () => {
    expect(consumeRelaunchAttempt([1_000, 5_000], 10_000, 2, 6_000)).toEqual({
      allowed: true,
      history: [5_000, 10_000],
    });
    expect(consumeRelaunchAttempt([5_000, 9_000], 10_000, 2, 6_000)).toEqual({
      allowed: false,
      history: [5_000, 9_000],
    });
  });

  it('does not recover a renderer that exited cleanly', () => {
    expect(shouldRecoverRenderer('clean-exit')).toBe(false);
    expect(shouldRecoverRenderer('crashed')).toBe(true);
    expect(shouldRecoverRenderer('oom')).toBe(true);
  });

  it('builds a per-minute Windows watchdog task for paths with spaces', () => {
    const args = buildWatchdogTaskArguments('C:\\Program Files\\BeiTong\\client.exe');
    expect(args).toContain(WATCHDOG_TASK_NAME);
    expect(args).toContain('MINUTE');
    expect(args).toContain('1');
    expect(args).toContain('"C:\\Program Files\\BeiTong\\client.exe" --watchdog-launch');
  });
});
