import { Client } from "@langchain/langgraph-sdk";

export function createClient(
  apiUrl: string,
  apiKey: string | undefined,
  authScheme: string | undefined,
  accessToken?: string | null,
) {
  return new Client({
    apiKey,
    apiUrl,
    defaultHeaders: {
      ...(authScheme ? { "X-Auth-Scheme": authScheme } : {}),
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
  });
}
