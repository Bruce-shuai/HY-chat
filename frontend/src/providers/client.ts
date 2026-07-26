import { Client } from "@langchain/langgraph-sdk";
import { resolveApiUrl, userBearerHeaders } from "./agent-api-policy";

export { resolveApiUrl } from "./agent-api-policy";

export function createClient(
  apiUrl: string,
  apiKey: string | undefined,
  authScheme: string | undefined,
  accessToken?: string | null,
) {
  const resolvedApiUrl = resolveApiUrl(apiUrl);

  return new Client({
    apiKey,
    apiUrl: resolvedApiUrl,
    defaultHeaders: {
      ...(authScheme ? { "X-Auth-Scheme": authScheme } : {}),
      ...userBearerHeaders(resolvedApiUrl, accessToken),
    },
  });
}
