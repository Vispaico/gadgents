import * as Sentry from "@sentry/react";

// Init is deferred until the app fetches /api/config and passes the DSN.
// We export initSentry so the App can call it once the DSN is known.
let initialized = false;

export function initSentry(dsn) {
  if (initialized || !dsn) return;
  Sentry.init({
    dsn,
    integrations: [
      Sentry.browserTracingIntegration(),
      Sentry.replayIntegration(),
    ],
    tracesSampleRate: 1.0,
    replaysSessionSampleRate: 0.1,
    replaysOnErrorSampleRate: 1.0,
  });
  initialized = true;
}
