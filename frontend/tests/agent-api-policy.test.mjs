import assert from "node:assert/strict";
import { test } from "node:test";
import * as policy from "../src/providers/agent-api-policy.ts";

const production = {
  nodeEnv: "production",
  origin: "https://chat.hy-ai.xyz",
};
const development = {
  nodeEnv: "development",
  origin: "http://localhost:3000",
};

test("production ignores query and environment Agent API overrides", () => {
  assert.equal(
    policy.selectAgentApiUrl(
      "https://attacker.example/collect",
      "https://configured.example/graph",
      production,
    ),
    "/api",
  );
  assert.equal(
    policy.resolveApiUrl("https://attacker.example/collect", production),
    "https://chat.hy-ai.xyz/api",
  );
});

test("production only attaches a user Bearer token to same-origin /api", () => {
  assert.deepEqual(
    policy.userBearerHeaders(
      "https://chat.hy-ai.xyz/api",
      "user-token",
      production,
    ),
    { Authorization: "Bearer user-token" },
  );
  assert.deepEqual(
    policy.userBearerHeaders(
      "https://attacker.example/api",
      "user-token",
      production,
    ),
    {},
  );
  assert.deepEqual(
    policy.userBearerHeaders(
      "https://chat.hy-ai.xyz/not-api",
      "user-token",
      production,
    ),
    {},
  );
});

test("development keeps explicit graph-server configuration", () => {
  assert.equal(
    policy.selectAgentApiUrl(
      "http://localhost:2024",
      "http://agent:2024",
      development,
    ),
    "http://localhost:2024",
  );
  assert.deepEqual(
    policy.userBearerHeaders(
      "http://localhost:2024",
      "development-token",
      development,
    ),
    { Authorization: "Bearer development-token" },
  );
});
