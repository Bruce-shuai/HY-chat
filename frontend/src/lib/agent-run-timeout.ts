export const AGENT_RUN_TIMEOUT_ERROR_CODE = "AGENT_RUN_TIMEOUT";
export const DEFAULT_AGENT_RUN_TIMEOUT_MS = 180_000;

const MIN_AGENT_RUN_TIMEOUT_MS = 10_000;
const MAX_AGENT_RUN_TIMEOUT_MS = 600_000;

export function resolveAgentRunTimeoutMs(value?: string): number {
  if (!value?.trim()) return DEFAULT_AGENT_RUN_TIMEOUT_MS;

  const timeoutMs = Number(value);
  if (
    !Number.isInteger(timeoutMs) ||
    timeoutMs < MIN_AGENT_RUN_TIMEOUT_MS ||
    timeoutMs > MAX_AGENT_RUN_TIMEOUT_MS
  ) {
    return DEFAULT_AGENT_RUN_TIMEOUT_MS;
  }
  return timeoutMs;
}

function formatTimeout(timeoutMs: number): string {
  const seconds = Math.ceil(timeoutMs / 1000);
  if (seconds % 60 === 0) return `${seconds / 60} 分钟`;
  return `${seconds} 秒`;
}

export class AgentRunTimeoutError extends Error {
  readonly code = AGENT_RUN_TIMEOUT_ERROR_CODE;
  readonly timeoutMs: number;

  constructor(timeoutMs: number) {
    super(`本次回答超过 ${formatTimeout(timeoutMs)}，已自动停止`);
    this.name = "AgentRunTimeoutError";
    this.timeoutMs = timeoutMs;
  }
}

export class AgentRunWatchdog {
  private timer: ReturnType<typeof setTimeout> | null = null;
  readonly timeoutMs: number;

  constructor(timeoutMs: number) {
    this.timeoutMs = timeoutMs;
  }

  start(onTimeout: () => void): void {
    if (this.timer !== null) return;
    this.timer = setTimeout(() => {
      this.timer = null;
      onTimeout();
    }, this.timeoutMs);
  }

  clear(): void {
    if (this.timer === null) return;
    clearTimeout(this.timer);
    this.timer = null;
  }

  get isActive(): boolean {
    return this.timer !== null;
  }
}

export class ResumedRunLifecycleTracker {
  private sawRunning = false;

  observe(event: unknown): boolean {
    if (event === "running") {
      this.sawRunning = true;
      return false;
    }

    if (event === "completed" || event === "failed") return true;
    return event === "interrupted" && this.sawRunning;
  }
}

export function isAgentRunTimeoutError(error: unknown): boolean {
  return (
    error instanceof AgentRunTimeoutError ||
    (typeof error === "object" &&
      error !== null &&
      "code" in error &&
      error.code === AGENT_RUN_TIMEOUT_ERROR_CODE)
  );
}
