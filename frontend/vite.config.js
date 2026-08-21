import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { sentryVitePlugin } from "@sentry/vite-plugin";

// code-server forwards /proxy/5173/<path> to 127.0.0.1:5173/<path> (prefix
// stripped). vite with base "/proxy/5173/" expects the prefix, so we re-add
// it — except for /api, which must stay root-relative for vite's own proxy.
function codeServerProxyBase() {
  const basePath = "/proxy/5173";
  return {
    name: "code-server-proxy-base",
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        const url = req.url || "";
        if (!url.startsWith(basePath) && !url.startsWith("/api")) {
          req.url = basePath + url;
        }
        next();
      });
    },
  };
}

export default defineConfig({
  base: "/proxy/5173/",
  plugins: [
    react(),
    codeServerProxyBase(),
    sentryVitePlugin({
      org: "sentry",
      project: "gadgents-frontend",
      authToken: process.env.SENTRY_AUTH_TOKEN,
      telemetry: false,
    }),
  ],
  server: {
    host: "127.0.0.1",
    port: 5173,
    allowedHosts: ["code.vispaico.com"],
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
  build: {
    sourcemap: true,
  },
});
