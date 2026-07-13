import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.jsx";
import "./index.css";

// Surface any render error instead of a blank/black screen.
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  componentDidCatch(error, info) {
    console.error("App crashed:", error, info);
  }
  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 24, color: "#e6e8ee", background: "#0f1115", fontFamily: "ui-sans-serif, system-ui" }}>
          <h2>Something broke while rendering.</h2>
          <pre style={{ whiteSpace: "pre-wrap", color: "#ff6b6b" }}>{String(this.state.error && this.state.error.stack || this.state.error)}</pre>
        </div>
      );
    }
    return this.props.children;
  }
}

createRoot(document.getElementById("root")).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>
);
