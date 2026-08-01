import assert from "node:assert/strict";
import { test } from "node:test";

import {
  AGENT_RUN_TIMEOUT_ERROR_CODE,
  AgentRunCompletionReconciler,
  AgentRunTimeoutError,
  AgentRunWatchdog,
  DEFAULT_AGENT_RUN_TIMEOUT_MS,
  ResumedRunLifecycleTracker,
  isTerminalAgentRunStatus,
  isAgentRunTimeoutError,
  resolveAgentRunTimeoutMs,
} from "../src/lib/agent-run-timeout.ts";

async function flushMicrotasks() {
  await Promise.resolve();
  await Promise.resolve();
}

test("chat run timeout defaults to three minutes for invalid configuration", () => {
  for (const value of [undefined, "", "not-a-number", "0", "1000", "900000"]) {
    assert.equal(resolveAgentRunTimeoutMs(value), DEFAULT_AGENT_RUN_TIMEOUT_MS);
  }
});

test("chat run timeout accepts a bounded build-time override", () => {
  assert.equal(resolveAgentRunTimeoutMs("240000"), 240000);
});

test("chat run timeout has a stable error code and user-facing copy", () => {
  const error = new AgentRunTimeoutError(180000);

  assert.equal(error.code, AGENT_RUN_TIMEOUT_ERROR_CODE);
  assert.match(error.message, /3 分钟/);
  assert.equal(isAgentRunTimeoutError(error), true);
});

test("chat run watchdog starts once and is not reset by stream updates", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const watchdog = new AgentRunWatchdog(180000);
  let timeoutCount = 0;

  watchdog.start(() => {
    timeoutCount += 1;
  });
  t.mock.timers.tick(120000);
  watchdog.start(() => {
    timeoutCount += 100;
  });
  t.mock.timers.tick(59999);
  assert.equal(timeoutCount, 0);

  t.mock.timers.tick(1);
  assert.equal(timeoutCount, 1);
  assert.equal(watchdog.isActive, false);
});

test("chat run watchdog can be cleared on completion", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const watchdog = new AgentRunWatchdog(180000);
  let timedOut = false;

  watchdog.start(() => {
    timedOut = true;
  });
  watchdog.clear();
  t.mock.timers.tick(180000);

  assert.equal(timedOut, false);
  assert.equal(watchdog.isActive, false);
});

test("approval dispatch is bounded before a loading lifecycle event", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const watchdog = new AgentRunWatchdog(180000);
  let timedOut = false;

  // Approval commands can block before the SDK reports isLoading=true.
  watchdog.start(() => {
    timedOut = true;
  });
  t.mock.timers.tick(180000);

  assert.equal(timedOut, true);
});

test("a fast approval terminal clears the watchdog without a React render", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const watchdog = new AgentRunWatchdog(180000);
  const lifecycle = new ResumedRunLifecycleTracker();
  let timedOut = false;

  watchdog.start(() => {
    timedOut = true;
  });
  assert.equal(lifecycle.observe("running"), false);
  if (lifecycle.observe("completed")) watchdog.clear();
  t.mock.timers.tick(180000);

  assert.equal(timedOut, false);
  assert.equal(watchdog.isActive, false);
});

test("a stale pre-resume interrupt does not clear the approval watchdog", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const watchdog = new AgentRunWatchdog(180000);
  const lifecycle = new ResumedRunLifecycleTracker();
  let timedOut = false;

  watchdog.start(() => {
    timedOut = true;
  });
  assert.equal(lifecycle.observe("interrupted"), false);
  t.mock.timers.tick(180000);

  assert.equal(timedOut, true);
});

test("run reconciliation ignores active states and detects a terminal run", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const reconciler = new AgentRunCompletionReconciler(12000, 3000);
  const statuses = ["running", "success"];
  const terminals = [];

  reconciler.start(
    async () => statuses.shift(),
    (status) => terminals.push(status),
  );
  t.mock.timers.tick(12000);
  await flushMicrotasks();
  assert.deepEqual(terminals, []);
  assert.equal(reconciler.isActive, true);

  t.mock.timers.tick(3000);
  await flushMicrotasks();
  assert.deepEqual(terminals, ["success"]);
  assert.equal(reconciler.isActive, false);
});

test("clearing reconciliation invalidates an in-flight status read", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const reconciler = new AgentRunCompletionReconciler(12000, 3000);
  let resolveStatus;
  const status = new Promise((resolve) => {
    resolveStatus = resolve;
  });
  let terminalCount = 0;

  reconciler.start(
    () => status,
    () => {
      terminalCount += 1;
    },
  );
  t.mock.timers.tick(12000);
  reconciler.clear();
  resolveStatus("success");
  await flushMicrotasks();

  assert.equal(terminalCount, 0);
  assert.equal(reconciler.isActive, false);
});

test("only final Agent run statuses trigger stream reconciliation", () => {
  assert.equal(isTerminalAgentRunStatus("pending"), false);
  assert.equal(isTerminalAgentRunStatus("running"), false);
  assert.equal(isTerminalAgentRunStatus("success"), true);
  assert.equal(isTerminalAgentRunStatus("error"), true);
  assert.equal(isTerminalAgentRunStatus("timeout"), true);
  assert.equal(isTerminalAgentRunStatus("interrupted"), true);
});
