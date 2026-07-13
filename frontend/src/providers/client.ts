import { Client } from "@langchain/langgraph-sdk";

export function resolveApiUrl(apiUrl: string): string {
  if (typeof window === "undefined") return apiUrl;
  return new URL(apiUrl, window.location.origin).toString().replace(/\/$/, "");
}

export function createClient(
  apiUrl: string,
  apiKey: string | undefined,
  authScheme: string | undefined,
  accessToken?: string | null,
) {
  return new Client({
    apiKey,
    apiUrl: resolveApiUrl(apiUrl),
    defaultHeaders: {
      ...(authScheme ? { "X-Auth-Scheme": authScheme } : {}),
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
  });
}
