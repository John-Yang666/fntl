export const BACKGROUND_LAUNCH_ARGUMENT = '--watchdog-launch';
export const WATCHDOG_TASK_NAME = 'BeiTongNmsClientWatchdog';
export const LOGIN_ITEM_NAME = 'BeiTongNmsClient';
export const WATCHDOG_INSTALL_MARKER = '.bt-nms-watchdog-installed';

export interface RelaunchDecision {
  allowed: boolean;
  history: number[];
}

export function isBackgroundLaunch(args: string[]): boolean {
  return args.includes(BACKGROUND_LAUNCH_ARGUMENT);
}

export function shouldRecoverRenderer(reason: string): boolean {
  return reason !== 'clean-exit';
}

export function consumeRelaunchAttempt(
  history: number[],
  now: number,
  maxAttempts: number,
  windowMs: number,
): RelaunchDecision {
  const cutoff = now - windowMs;
  const recentHistory = history.filter((timestamp) => (
    Number.isFinite(timestamp) && timestamp >= cutoff && timestamp <= now
  ));
  if (recentHistory.length >= maxAttempts) {
    return { allowed: false, history: recentHistory };
  }
  return { allowed: true, history: [...recentHistory, now] };
}

export class RecoveryThrottle {
  private attempts: number[] = [];

  constructor(
    private readonly maxAttempts: number,
    private readonly windowMs: number,
  ) {}

  consume(now = Date.now()): boolean {
    const decision = consumeRelaunchAttempt(
      this.attempts,
      now,
      this.maxAttempts,
      this.windowMs,
    );
    this.attempts = decision.history;
    return decision.allowed;
  }
}

export function buildWatchdogTaskArguments(executablePath: string): string[] {
  return [
    '/Create',
    '/F',
    '/TN',
    WATCHDOG_TASK_NAME,
    '/SC',
    'MINUTE',
    '/MO',
    '1',
    '/TR',
    `"${executablePath}" ${BACKGROUND_LAUNCH_ARGUMENT}`,
    '/RL',
    'LIMITED',
  ];
}
