const configuredBackendUrl = process.env.NEXT_PUBLIC_BACKEND_URL;

export function backendUrl() {
  if (configuredBackendUrl) return configuredBackendUrl;
  return process.env.NODE_ENV === "production"
    ? "/backend"
    : "http://localhost:8000";
}
