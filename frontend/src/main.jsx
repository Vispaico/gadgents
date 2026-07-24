import React from "react";
import { createRoot } from "react-dom/client";
import * as Sentry from "@sentry/react";
import { App } from "./App.jsx";
import "./index.css";

createRoot(document.getElementById("root")).render(
  <Sentry.ErrorBoundary fallback={({ error }) => (
    <div style={{ padding: 24, color: "#e6e8ee", background: "#0f1115", fontFamily: "ui-sans-serif, system-ui" }}>
      <h2>Something broke while rendering.</h2>
      <pre style={{ whiteSpace: "pre-wrap", color: "#ff6b6b" }}>{String(error && error.stack || error)}</pre>
    </div>
  )}>
    <App />
  </Sentry.ErrorBoundary>
);
