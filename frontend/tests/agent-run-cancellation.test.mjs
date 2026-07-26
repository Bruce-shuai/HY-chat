import assert from "node:assert/strict";
import { test } from "node:test";

import {
  cancelActiveThreadRuns,
  cancelRunExactly,
} from "../src/lib/agent-run-cancellation.ts";

function run(runId) {
  return { run_id: runId };
}

function createRunsClient({
  runsByStatus = {},
  cancelError,
  cancelManyError,
} = {}) {
  const calls = {
    cancel: [],
    cancelMany: [],
    list: [],
  };

  return {
    calls,
    client: {
      async cancel(...args) {
        calls.cancel.push(args);
        if (cancelError) throw cancelError;
      },
      async cancelMany(options) {
        calls.cancelMany.push(options);
        if (cancelManyError) throw cancelManyError;
      },
      async list(threadId, options) {
        calls.list.push([threadId, options]);
        return runsByStatus[options.status] ?? [];
      },
    },
  };
}

test("cancellation only lists and cancels active runs from the target thread", async () => {
  const { client, calls } = createRunsClient({
    runsByStatus: {
      pending: [run("pending-a")],
      running: [run("running-a")],
    },
  });

  await cancelActiveThreadRuns(client, "thread-a");

  assert.deepEqual(
    calls.list.map(([threadId, options]) => [threadId, options.status]),
    [
      ["thread-a", "pending"],
      ["thread-a", "running"],
    ],
  );
  assert.equal(calls.cancelMany.length, 1);
  assert.equal(calls.cancelMany[0].threadId, "thread-a");
  assert.deepEqual([...calls.cancelMany[0].runIds].sort(), [
    "pending-a",
    "running-a",
  ]);
  assert.equal(calls.cancel.length, 0);
});

test("approval resume without an onCreated run id discovers the active run", async () => {
  const { client, calls } = createRunsClient({
    runsByStatus: {
      running: [run("approval-resume-run")],
    },
  });

  await cancelActiveThreadRuns(client, "approval-thread");

  assert.equal(calls.cancel.length, 0);
  assert.deepEqual(calls.cancelMany[0].runIds, ["approval-resume-run"]);
  assert.equal(calls.cancelMany[0].threadId, "approval-thread");
});

test("switching threads keeps cleanup bound to the previous thread", async () => {
  const { client, calls } = createRunsClient({
    runsByStatus: {
      running: [run("old-thread-run")],
    },
  });

  await cancelActiveThreadRuns(client, "old-thread");

  for (const [threadId] of calls.list) {
    assert.equal(threadId, "old-thread");
  }
  assert.equal(calls.cancelMany[0].threadId, "old-thread");
  assert.notEqual(calls.cancelMany[0].threadId, "new-thread");
});

test("a late onCreated run id is cancelled precisely and idempotently", async () => {
  const { client, calls } = createRunsClient({
    runsByStatus: {
      running: [run("late-run")],
    },
  });

  await cancelActiveThreadRuns(client, "submit-thread", "late-run");

  assert.equal(calls.cancel[0][0], "submit-thread");
  assert.equal(calls.cancel[0][1], "late-run");
  assert.equal(calls.cancelMany[0].threadId, "submit-thread");
  assert.deepEqual(calls.cancelMany[0].runIds, ["late-run"]);
});

test("a stale onCreated callback never sweeps a same-thread retry", async () => {
  const { client, calls } = createRunsClient({
    runsByStatus: {
      running: [run("new-retry-run")],
    },
  });

  await cancelRunExactly(client, "same-thread", "stale-run");

  assert.equal(calls.cancel.length, 1);
  assert.equal(calls.cancel[0][0], "same-thread");
  assert.equal(calls.cancel[0][1], "stale-run");
  assert.equal(calls.list.length, 0);
  assert.equal(calls.cancelMany.length, 0);
});

test("401 and 404 cleanup failures are best effort and do not reject", async (t) => {
  const unauthorized = Object.assign(new Error("Unauthorized"), {
    status: 401,
  });
  const notFound = Object.assign(new Error("Run not found"), {
    status: 404,
  });
  const { client, calls } = createRunsClient({
    runsByStatus: {
      running: [run("already-finished-run")],
    },
    cancelError: unauthorized,
    cancelManyError: notFound,
  });
  const warning = t.mock.method(console, "warn", () => {});

  await assert.doesNotReject(() =>
    cancelActiveThreadRuns(client, "thread-with-stale-run", "stale-run"),
  );

  assert.equal(calls.cancelMany.length, 1);
  assert.ok(calls.cancel.length >= 2);
  assert.equal(warning.mock.callCount(), 1);
});
