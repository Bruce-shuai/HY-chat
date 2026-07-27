export const PRODUCTION_AGENT_API_PATH = "/api";
export const PRODUCTION_AGENT_ASSISTANT_ID = "hy-chat";

type AgentApiPolicyOptions = {
  nodeEnv?: string;
  origin?: string;
};

function runtimeNodeEnv(options: AgentApiPolicyOptions): string | undefined {
  return options.nodeEnv ?? process.env.NODE_ENV;
}

function runtimeOrigin(options: AgentApiPolicyOptions): string | undefined {
  if (options.origin !== undefined) return options.origin;
  if (typeof window === "undefined") return undefined;
  return window.location.origin;
}

export function isAgentApiLocked(options: AgentApiPolicyOptions = {}): boolean {
  return runtimeNodeEnv(options) === "production";
}

/**
 * Production always uses the same-origin Next.js passthrough. Query parameters
 * remain useful for local development, but can never choose a production token
 * recipient.
 */
export function selectAgentApiUrl(
  queryApiUrl: string | null | undefined,
  environmentApiUrl: string | undefined,
  options: AgentApiPolicyOptions = {},
): string {
  if (isAgentApiLocked(options)) return PRODUCTION_AGENT_API_PATH;
  return queryApiUrl?.trim() || environmentApiUrl?.trim() || "";
}

/**
 * Production serves a single, application-owned graph. Keeping its identifier
 * here makes the browser independent of optional build-time public variables
 * and prevents URL parameters from selecting a different graph.
 */
export function selectAgentAssistantId(
  queryAssistantId: string | null | undefined,
  environmentAssistantId: string | undefined,
  options: AgentApiPolicyOptions = {},
): string {
  if (isAgentApiLocked(options)) return PRODUCTION_AGENT_ASSISTANT_ID;
  return queryAssistantId?.trim() || environmentAssistantId?.trim() || "";
}

export function resolveApiUrl(
  apiUrl: string,
  options: AgentApiPolicyOptions = {},
): string {
  const selectedApiUrl = isAgentApiLocked(options)
    ? PRODUCTION_AGENT_API_PATH
    : apiUrl;
  const origin = runtimeOrigin(options);

  if (!origin) return selectedApiUrl.replace(/\/$/, "");
  return new URL(selectedApiUrl, origin).toString().replace(/\/$/, "");
}

/**
 * This is a second, independent guard at the credential attachment boundary.
 * In production, a user JWT is only valid for the exact same-origin /api base.
 */
export function userBearerHeaders(
  apiUrl: string,
  accessToken: string | null | undefined,
  options: AgentApiPolicyOptions = {},
): Record<string, string> {
  if (!accessToken) return {};
  if (!isAgentApiLocked(options)) {
    return { Authorization: `Bearer ${accessToken}` };
  }

  const origin = runtimeOrigin(options);
  if (!origin) return {};

  try {
    const target = new URL(apiUrl, origin);
    const trusted = new URL(PRODUCTION_AGENT_API_PATH, origin);
    const isTrustedTarget =
      target.origin === trusted.origin &&
      target.pathname === trusted.pathname &&
      target.username === "" &&
      target.password === "";

    return isTrustedTarget ? { Authorization: `Bearer ${accessToken}` } : {};
  } catch {
    return {};
  }
}
