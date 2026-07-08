import React, { useEffect, useState } from "react";
import { api, getToken, setToken } from "./api.js";

const ALL_PLATFORMS = ["Instagram", "TikTok", "LinkedIn", "X", "YouTube", "Facebook"];

export function App() {
  const [view, setView] = useState(getToken() ? "home" : "auth");
  const [user, setUser] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (getToken()) {
      api
        .me()
        .then((m) => setUser(m))
        .catch(() => setToken(""));
    }
  }, []);

  function applyAuth(res) {
    setToken(res.access_token);
    setUser({ email: res.email || "", credits: res.credits, plan: res.plan });
    setView("home");
  }

  async function refreshMe() {
    try {
      setUser(await api.me());
    } catch {}
  }

  if (view === "auth") {
    return (
      <AuthScreen
        error={error}
        setError={setError}
        onLogin={async (e, p) => {
          setBusy(true);
          try {
            applyAuth(await api.login(e, p));
          } catch (err) {
            setError(err.message);
          } finally {
            setBusy(false);
          }
        }}
        onRegister={async (e, p) => {
          setBusy(true);
          try {
            applyAuth(await api.register(e, p));
          } catch (err) {
            setError(err.message);
          } finally {
            setBusy(false);
          }
        }}
      />
    );
  }

  return (
    <Home
      user={user}
      setError={setError}
      onBought={refreshMe}
      onLogout={() => {
        setToken("");
        setUser(null);
        setView("auth");
      }}
    />
  );
}

function AuthScreen({ error, setError, onLogin, onRegister, busy }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState("login");

  return (
    <Center>
      <Card>
        <h1>Gadgents</h1>
        <p className="muted">Rent an AI bot. Pay per use.</p>
        {error && <div className="error">{error}</div>}
        <input placeholder="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <input
          type="password"
          placeholder="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <button disabled={busy} onClick={() => (mode === "login" ? onLogin(email, password) : onRegister(email, password))}>
          {busy ? "…" : mode === "login" ? "Log in" : "Create account"}
        </button>
        <button className="link" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }}>
          {mode === "login" ? "Need an account? Sign up" : "Have an account? Log in"}
        </button>
      </Card>
    </Center>
  );
}

function Home({ user, setError, onBought, onLogout }) {
  const [tab, setTab] = useState("bots");
  return (
    <div className="app">
      <header>
        <strong>Gadgents</strong>
        <span className="muted">credits: {user?.credits}</span>
        <span className="muted">plan: {user?.plan}</span>
        <nav>
          <button className={tab === "bots" ? "active" : ""} onClick={() => setTab("bots")}>Bots</button>
          <button className={tab === "content" ? "active" : ""} onClick={() => setTab("content")}>Content Studio</button>
          <button className={tab === "billing" ? "active" : ""} onClick={() => setTab("billing")}>Billing</button>
          <button className="link" onClick={onLogout}>Log out</button>
        </nav>
      </header>
      <main>
        {tab === "bots" && <BotList user={user} />}
        {tab === "content" && <ContentStudio user={user} setError={setError} />}
        {tab === "billing" && <Billing onBought={onBought} />}
      </main>
    </div>
  );
}

function BotList({ user }) {
  const [agents, setAgents] = useState([]);
  const [active, setActive] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.listAgents().then(setAgents).catch((e) => setErr(e.message));
  }, []);

  async function openAgent(a) {
    setActive(a);
    setMessages([]);
    setErr("");
  }

  async function send() {
    if (!input.trim() || !active) return;
    setBusy(true);
    setErr("");
    const text = input;
    setMessages((m) => [...m, { role: "user", content: text }]);
    setInput("");
    try {
      const res = await api.chat(active.id, text);
      setMessages((m) => [...m, { role: "assistant", content: res.text }]);
      user.credits = res.remaining_credits;
    } catch (e) {
      setErr(e.message);
      if (e.message.includes("credits")) setInput(text);
    } finally {
      setBusy(false);
    }
  }

  if (!active) {
    return (
      <div className="grid">
        {agents.map((a) => (
          <div className="card click" key={a.id} onClick={() => openAgent(a)}>
            <h3>{a.name}</h3>
            <p className="muted">{a.description}</p>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="chat">
      <button className="link" onClick={() => setActive(null)}>← Back to bots</button>
      <h2>{active.name}</h2>
      <div className="messages">
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>{m.content}</div>
        ))}
      </div>
      {err && <div className="error">{err}</div>}
      <div className="composer">
        <textarea
          value={input}
          placeholder="Type your task…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), send())}
        />
        <button disabled={busy} onClick={send}>{busy ? "…" : "Send"}</button>
      </div>
    </div>
  );
}

function ContentStudio({ user, setError }) {
  const [material, setMaterial] = useState("");
  const [platforms, setPlatforms] = useState(["Instagram", "TikTok"]);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  function toggle(p) {
    setPlatforms((cur) => (cur.includes(p) ? cur.filter((x) => x !== p) : [...cur, p]));
  }

  async function run() {
    if (!material.trim()) return;
    setBusy(true);
    setErr("");
    setResult(null);
    try {
      const res = await api.pipeline(material, platforms);
      setResult(res);
      user.credits = res.remaining_credits;
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="studio">
      <h2>Content Studio</h2>
      <p className="muted">Paste an article, image notes or video idea. We turn it into prompts, then finished content.</p>
      <textarea
        className="big"
        value={material}
        placeholder="Paste your source material or idea here…"
        onChange={(e) => setMaterial(e.target.value)}
      />
      <div className="chips">
        {ALL_PLATFORMS.map((p) => (
          <button
            key={p}
            className={platforms.includes(p) ? "chip active" : "chip"}
            onClick={() => toggle(p)}
          >
            {p}
          </button>
        ))}
      </div>
      <button disabled={busy || platforms.length === 0} onClick={run}>
        {busy ? "Generating…" : "Generate prompts + content"}
      </button>
      {err && <div className="error">{err}</div>}
      {result && (
        <div className="result">
          <h3>Prompts</h3>
          <pre>{result.prompts}</pre>
          <h3>Content</h3>
          <pre>{result.content}</pre>
          <p className="muted">used {result.credits_used} credits · {result.remaining_credits} left</p>
        </div>
      )}
    </div>
  );
}

function Billing({ onBought }) {
  const [plans, setPlans] = useState({});
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");

  useEffect(() => {
    api.plans().then(setPlans).catch((e) => setErr(e.message));
  }, []);

  async function buy(key) {
    setBusy(key);
    setErr("");
    try {
      const res = await api.buy(key);
      if (!res.ok) setErr(res.message);
      else onBought();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy("");
    }
  }

  return (
    <div>
      <h2>Billing</h2>
      <p className="muted">100 credits = $1. Buy a credit pack or a subscription plan.</p>
      {err && <div className="error">{err}</div>}
      <div className="grid">
        {Object.entries(plans).map(([key, p]) => (
          <div className="card" key={key}>
            <h3>{p.label}</h3>
            <button disabled={!!busy} onClick={() => buy(key)}>
              {busy === key ? "…" : "Buy"}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---- minimal styling ---- */
function Center({ children }) {
  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", background: "#0f1115" }}>
      {children}
    </div>
  );
}
function Card({ children }) {
  return (
    <div className="card" style={{ width: 340, display: "flex", flexDirection: "column", gap: 10 }}>
      {children}
    </div>
  );
}
