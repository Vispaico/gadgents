import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { sentryVitePlugin } from "@sentry/vite-plugin";

export default defineConfig({
  plugins: [
    react(),
    sentryVitePlugin({
      org: "sentry",
      project: "gadgents-frontend",
      authToken: process.env.SENTRY_AUTH_TOKEN,
      telemetry: false,
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  build: {
    sourcemap: true,
  },
});
