import assert from "node:assert/strict";
import { test } from "node:test";

import {
  AGENT_RUN_TIMEOUT_ERROR_CODE,
  AgentRunTimeoutError,
  AgentRunWatchdog,
  DEFAULT_AGENT_RUN_TIMEOUT_MS,
  ResumedRunLifecycleTracker,
  isAgentRunTimeoutError,
  resolveAgentRunTimeoutMs,
} from "../src/lib/agent-run-timeout.ts";

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
