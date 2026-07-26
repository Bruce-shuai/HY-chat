import type { Client } from "@langchain/langgraph-sdk/client";

const ACTIVE_RUN_STATUSES = ["pending", "running"] as const;
export const DEFAULT_RUN_CANCEL_TIMEOUT_MS = 10_000;

type RunsClient = Pick<Client["runs"], "cancel" | "cancelMany" | "list">;

function runIdOf(run: unknown): string | null {
  if (
    typeof run === "object" &&
    run !== null &&
    "run_id" in run &&
    typeof run.run_id === "string"
  ) {
    return run.run_id;
  }
  return null;
}

export async function cancelRunExactly(
  runs: RunsClient,
  threadId: string,
  runId: string,
  timeoutMs = DEFAULT_RUN_CANCEL_TIMEOUT_MS,
): Promise<void> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    await runs.cancel(threadId, runId, false, "interrupt", {
      signal: controller.signal,
    });
  } catch (error) {
    console.warn("精确取消 Agent Run 失败", error);
  } finally {
    clearTimeout(timeout);
  }
}

/**
 * Best-effort cleanup for one thread only.
 *
 * The Agent API does not accept `threadId` together with a status filter on
 * `cancelMany`. List the thread's active runs first, then cancel the exact IDs
 * so a timeout can never affect another user's thread.
 */
export async function cancelActiveThreadRuns(
  runs: RunsClient,
  threadId: string,
  knownRunId?: string,
  timeoutMs = DEFAULT_RUN_CANCEL_TIMEOUT_MS,
): Promise<void> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  const cancellationErrors: unknown[] = [];

  try {
    const knownRunCancellation = knownRunId
      ? runs
          .cancel(threadId, knownRunId, false, "interrupt", {
            signal: controller.signal,
          })
          .catch((error) => {
            cancellationErrors.push(error);
          })
      : Promise.resolve();

    const listedRuns = await Promise.allSettled(
      ACTIVE_RUN_STATUSES.map((status) =>
        runs.list(threadId, {
          limit: 100,
          status,
          signal: controller.signal,
        }),
      ),
    );
    const runIds = new Set<string>(knownRunId ? [knownRunId] : []);
    for (const result of listedRuns) {
      if (result.status === "rejected") {
        cancellationErrors.push(result.reason);
        continue;
      }
      for (const run of result.value) {
        const runId = runIdOf(run);
        if (runId) runIds.add(runId);
      }
    }

    const exactRunIds = [...runIds];
    if (exactRunIds.length > 0) {
      try {
        await runs.cancelMany({
          threadId,
          runIds: exactRunIds,
          action: "interrupt",
          signal: controller.signal,
        });
      } catch (error) {
        cancellationErrors.push(error);
        await Promise.allSettled(
          exactRunIds.map((runId) =>
            runs.cancel(threadId, runId, false, "interrupt", {
              signal: controller.signal,
            }),
          ),
        );
      }
    }

    await knownRunCancellation;
  } finally {
    clearTimeout(timeout);
  }

  if (cancellationErrors.length > 0) {
    console.warn("Agent Run 清理未完全成功", cancellationErrors);
  }
}
