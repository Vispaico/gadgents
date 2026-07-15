import React, { useEffect, useState } from "react";
import { api, getToken, setToken, getMode, setMode } from "./api.js";

const ALL_PLATFORMS = ["Instagram", "TikTok", "LinkedIn", "X", "YouTube", "Facebook"];

export function App() {
  const [view, setView] = useState(getToken() ? "home" : "auth");
  const [requireLogin, setRequireLogin] = useState(true);
  const [user, setUser] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // Learn whether the backend is in dev-bypass mode (REQUIRE_LOGIN=false).
    // If not required, skip the login screen entirely and go straight to home.
    api
      .config()
      .then((cfg) => {
        setRequireLogin(!!cfg.require_login);
        if (!cfg.require_login) {
          // Dev-bypass: no account needed. Use a synthetic user so credits
          // display and handler assignments don't crash.
          setUser({ email: "", credits: 0, plan: "dev" });
          setView("home");
        } else if (getToken()) {
          return api.me().then(setUser).catch(() => setToken(""));
        }
      })
      .catch(() => setRequireLogin(true));
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

// Global quality/cost mode shared by every agent call.
const MODES = [
  { id: "high", label: "Quality" },
  { id: "mixed", label: "Balanced" },
  { id: "economic", label: "Economic" },
];


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
  const [wanSeed, setWanSeed] = useState("");  // concept passed from Content Studio -> Wan tab
  const [studioSeed, setStudioSeed] = useState("");  // post text passed from Social Listen -> Content Studio
  return (
    <div className="app">
      <header>
        <strong>Gadgents</strong>
        <span className="muted">credits: {user?.credits}</span>
        <span className="muted">plan: {user?.plan}</span>
        <ModeToggle />
        <nav>
          <button className={tab === "bots" ? "active" : ""} onClick={() => setTab("bots")}>Bots</button>
          <button className={tab === "content" ? "active" : ""} onClick={() => setTab("content")}>Content Studio</button>
          <button className={tab === "social" ? "active" : ""} onClick={() => setTab("social")}>Social Listen</button>
          <button className={tab === "leads" ? "active" : ""} onClick={() => setTab("leads")}>Lead Finder</button>
          <button className={tab === "wan" ? "active" : ""} onClick={() => setTab("wan")}>Wan Video</button>
          <button className={tab === "billing" ? "active" : ""} onClick={() => setTab("billing")}>Billing</button>
          <button className="link" onClick={onLogout}>Log out</button>
        </nav>
      </header>
      <main>
        {tab === "bots" && <BotList user={user} />}
        {tab === "content" && (
          <ContentStudio
            user={user}
            setError={setError}
            onSendToWan={(prompts) => { setWanSeed(prompts); setTab("wan"); }}
          />
        )}
        {tab === "leads" && <LeadFinder user={user} setError={setError} />}
        {tab === "social" && (
          <SocialListen
            user={user}
            setError={setError}
            onRepurpose={(text) => { setStudioSeed(text); setTab("content"); }}
          />
        )}
        {tab === "wan" && <WanVideo user={user} setError={setError} seed={wanSeed} />}
        {tab === "billing" && <Billing onBought={onBought} />}
      </main>
    </div>
  );
}

function ModeToggle() {
  const [mode, setLocal] = useState(getMode() || "mixed");
  function pick(m) {
    setLocal(m);
    setMode(m === "mixed" ? null : m); // mixed = agent default, don't force
  }
  return (
    <span className="mode-toggle" title="Quality vs cost for every agent call">
      {MODES.map((m) => (
        <button
          key={m.id}
          className={mode === m.id ? "chip active" : "chip"}
          onClick={() => pick(m.id)}
        >
          {m.label}
        </button>
      ))}
    </span>
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

const CONTENT_OUTPUTS = [
  { id: "prompts", label: "Prompts", desc: "Per-platform generation prompts (use in Wan or elsewhere)" },
  { id: "content", label: "Content + Media", desc: "Finished posts, hooks, hashtags, media suggestions" },
  { id: "repurpose", label: "Repurpose / Summarize", desc: "Multi-platform + media suggestions + short-video script" },
];

function ContentStudio({ user, setError, onSendToWan, seed = "" }) {
  const [material, setMaterial] = useState(seed);
  const [urls, setUrls] = useState("");
  const [instructions, setInstructions] = useState("");
  const [platforms, setPlatforms] = useState(["Instagram", "TikTok"]);
  const [output, setOutput] = useState("content");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [past, setPast] = useState([]);
  const [openBrief, setOpenBrief] = useState(null);

  async function openBriefById(id) {
    try {
      setOpenBrief(await api.pipelineBrief(id));
    } catch (e) {
      setErr(e.message);
    }
  }

  function toggle(p) {
    setPlatforms((cur) => (cur.includes(p) ? cur.filter((x) => x !== p) : [...cur, p]));
  }

  // Allow either splitting on whitespace/newlines or recognizing a single URL.
  function parseUrls() {
    return urls
      .split(/[\s,]+/)
      .map((u) => u.trim())
      .filter(Boolean);
  }

  async function loadPast() {
    try {
      setPast(await api.pipelineBriefs());
    } catch {
      setPast([]);
    }
  }

  async function run() {
    if (!material.trim() && !urls.trim() && !instructions.trim()) return;
    setBusy(true);
    setErr("");
    setResult(null);
    try {
      const res = await api.pipeline(material, platforms, output, parseUrls(), instructions);
      setResult(res);
      user.credits = res.remaining_credits;
      if (output === "repurpose") loadPast();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (output === "repurpose") loadPast();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="studio">
      <h2>Content Studio</h2>
      <p className="muted">
        Paste an article, image notes or video idea — or drop in URLs/links and we'll read
        them. Pick an output, choose platforms, generate.
      </p>
      <textarea
        className="big"
        value={material}
        placeholder="Paste your source material or idea here…"
        onChange={(e) => setMaterial(e.target.value)}
      />
      <textarea
        className="big"
        value={urls}
        placeholder="Optional: paste article/blog URLs (one per line or space-separated) to read and repurpose…"
        onChange={(e) => setUrls(e.target.value)}
      />
      <textarea
        className="big"
        value={instructions}
        placeholder="Optional: instructions / style notes the model must follow (e.g. 'keep the warehouse metaphor', 'tone: confident, target CTOs', 'rewrite in your own words, avoid plagiarism')…"
        onChange={(e) => setInstructions(e.target.value)}
      />

      <div className="output-modes">
        {CONTENT_OUTPUTS.map((o) => (
          <button
            key={o.id}
            className={output === o.id ? "card active" : "card"}
            onClick={() => setOutput(o.id)}
          >
            <strong>{o.label}</strong>
            <span className="muted">{o.desc}</span>
          </button>
        ))}
      </div>

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
        {busy ? "Generating…" : `Generate: ${CONTENT_OUTPUTS.find((o) => o.id === output).label}`}
      </button>
      {err && <div className="error">{err}</div>}
      {result && (
        <div className="result">
          {output === "prompts" && result.prompts && (
            <>
              <h3>Prompts</h3>
              <pre>{result.prompts}</pre>
              <button className="link" onClick={() => onSendToWan(result.prompts)}>
                → Send prompts to Wan Video
              </button>
            </>
          )}
          {result.content && (
            <>
              <h3>{output === "prompts" ? "Content" : output === "repurpose" ? "Repurposed content" : "Content + Media"}</h3>
              <pre>{result.content}</pre>
            </>
          )}
          <p className="muted">used {result.credits_used} credits · {result.remaining_credits} left</p>
        </div>
      )}
      {output === "repurpose" && past.length > 0 && (
        <div className="result">
          <h3>Past Repurpose runs</h3>
          {openBrief ? (
            <div className="brief-detail">
              <button className="link" onClick={() => setOpenBrief(null)}>← Back to runs</button>
              <h3>{openBrief.title}</h3>
              <p className="muted">{openBrief.channels || "all channels"} · {openBrief.created_at}</p>
              <pre>{openBrief.brief_json || "(no brief)"}</pre>
              {openBrief.outputs.map((o, i) => (
                <div key={i} className="card">
                  <span className="badge">{o.channel}</span>
                  <pre>{o.content_json}</pre>
                </div>
              ))}
            </div>
          ) : (
            <div className="grid">
              {past.map((b) => (
                <div
                  className="card click"
                  key={b.id}
                  onClick={() => openBriefById(b.id)}
                >
                  <h3>{b.title}</h3>
                  <p className="muted">{b.channels || "all channels"} · {b.created_at}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SocialListen({ user, setError, onRepurpose }) {
  const [topic, setTopic] = useState("");
  const [platforms, setPlatforms] = useState(["x"]);
  const [posts, setPosts] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [queries, setQueries] = useState([]);

  function toggle(p) {
    setPlatforms((cur) => (cur.includes(p) ? cur.filter((x) => x !== p) : [...cur, p]));
  }

  async function loadQueries() {
    try {
      setQueries(await api.socialQueries());
    } catch {
      setQueries([]);
    }
  }

  useEffect(() => {
    loadQueries();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function run() {
    if (!topic.trim()) return;
    setBusy(true);
    setErr("");
    setPosts([]);
    try {
      const res = await api.socialListen(topic, platforms, 20);
      // Already sorted by likes desc server-side; re-sort client-side to be safe.
      const sorted = [...res.posts].sort((a, b) => (b.like_count || 0) - (a.like_count || 0));
      setPosts(sorted);
      loadQueries();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  function repurpose(post) {
    const header = `Source (${post.platform}${post.author ? " @" + post.author : ""}):\n`;
    onRepurpose(header + post.text);
  }

  return (
    <div className="studio">
      <h2>Social Listen</h2>
      <p className="muted">
        Pull posts by topic from X / LinkedIn (via CloakBrowser) and sort by engagement.
        Repurpose any post straight into Content Studio.
      </p>
      <input
        value={topic}
        placeholder="Topic or #hashtag (e.g. 'ai agents' or '#founder')"
        onChange={(e) => setTopic(e.target.value)}
      />
      <div className="chips">
        {["x", "linkedin"].map((p) => (
          <button
            key={p}
            className={platforms.includes(p) ? "chip active" : "chip"}
            onClick={() => toggle(p)}
          >
            {p === "x" ? "X" : "LinkedIn"}
          </button>
        ))}
      </div>
      <button disabled={busy || !topic.trim()} onClick={run}>
        {busy ? "Listening…" : "Listen"}
      </button>
      {err && <div className="error">{err}</div>}
      {posts.length > 0 && (
        <div className="result">
          <h3>Posts by engagement ({posts.length})</h3>
          <div className="grid">
            {posts.map((post, i) => (
              <div className="card" key={i}>
                <span className="badge">{post.platform}</span>
                {post.author && <span className="muted"> · {post.author}</span>}
                <p>{post.text}</p>
                <p className="muted">
                  ♥ {post.like_count} · ↻ {post.repost_count} · 💬 {post.reply_count}
                </p>
                <div style={{ display: "flex", gap: 8 }}>
                  {post.url && (
                    <a className="link" href={post.url} target="_blank" rel="noreferrer">View ↗</a>
                  )}
                  <button className="link" onClick={() => repurpose(post)}>→ Repurpose</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      {queries.length > 0 && (
        <div className="result">
          <h3>Past listens</h3>
          <div className="grid">
            {queries.map((q) => (
              <div className="card" key={q.id}>
                <h3>{q.topic}</h3>
                <p className="muted">{q.platforms} · {q.created_at}</p>
              </div>
            ))}
          </div>
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

function LeadFinder({ user, setError }) {
  // Structured ICP fields
  const [name, setName] = useState("");
  const [offer, setOffer] = useState("");
  const [geography, setGeography] = useState("");
  const [target, setTarget] = useState("");
  const [companySize, setCompanySize] = useState("");
  const [language, setLanguage] = useState("en");
  const [useFirecrawl, setUseFirecrawl] = useState(false);

  // Chat refinement panel (feeds the same ICP)
  const [chat, setChat] = useState([]);
  const [chatInput, setChatInput] = useState("");
  const [history, setHistory] = useState([]);

  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [past, setPast] = useState([]);

  useEffect(() => {
    api.leadList().then(setPast).catch(() => {});
  }, []);

  async function sendChat() {
    if (!chatInput.trim()) return;
    setBusy(true);
    setErr("");
    const text = chatInput;
    setChat((m) => [...m, { role: "user", content: text }]);
    setHistory((h) => [...h, { role: "user", content: text }]);
    setChatInput("");
    try {
      const res = await api.leadIcpChat(text, history);
      setChat((m) => [...m, { role: "assistant", content: res.text }]);
      setHistory((h) => [...h, { role: "assistant", content: res.text }]);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function run() {
    if (!offer.trim()) {
      setErr("Describe what you sell (the offer) so we can find your leads.");
      return;
    }
    setBusy(true);
    setErr("");
    setResult(null);
    try {
      const icp = {
        name,
        offer,
        geography,
        target_description: target + (history.length ? `\nRefinement from chat:\n${history.map((m) => `${m.role}: ${m.content}`).join("\n")}` : ""),
        company_size: companySize,
        language,
        use_firecrawl: useFirecrawl,
      };
      const res = await api.leadRun(icp);
      setResult(res);
      if (user) user.credits = res.credits_used != null ? user.credits : user.credits;
      api.leadList().then(setPast).catch(() => {});
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="studio">
      <h2>Lead Finder</h2>
      <p className="muted">
        Define who you want as clients. Fill the fields, or chat with the agent to sharpen the
        target. Then run discovery across the public web (GDPR-safe: public pages + business
        emails only).
      </p>

      <div className="fields">
        <label>Run name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Berlin boutique consultancies" /></label>
        <label>Your offer *<input value={offer} onChange={(e) => setOffer(e.target.value)} placeholder="what you sell / the service" /></label>
        <label>Geography<input value={geography} onChange={(e) => setGeography(e.target.value)} placeholder="e.g. Berlin, Vietnam, remote" /></label>
        <label>Company size<select value={companySize} onChange={(e) => setCompanySize(e.target.value)}>
          <option value="">any</option>
          <option value="1-10">1-10</option>
          <option value="11-50">11-50</option>
          <option value="51-200">51-200</option>
        </select></label>
        <label>Language<select value={language} onChange={(e) => setLanguage(e.target.value)}>
          <option value="en">English</option>
          <option value="de">German</option>
          <option value="es">Spanish</option>
          <option value="fr">French</option>
        </select></label>
        <label>Target / niche / exclusions<textarea value={target} onChange={(e) => setTarget(e.target.value)} placeholder="boutique strategy consultancies 10-50 people; exclude giants like McKinsey" /></label>
        <label className="row">
          <input type="checkbox" checked={useFirecrawl} onChange={(e) => setUseFirecrawl(e.target.checked)} />
          Use Firecrawl (local docker :3002) for JS-rendered discovery + deep audit
        </label>
      </div>

      <div className="icp-chat">
        <h3>Refine with the agent</h3>
        <div className="messages">
          {chat.length === 0 && <p className="muted">Ask it to narrow the niche, suggest exclusions, or pick a target segment.</p>}
          {chat.map((m, i) => (
            <div key={i} className={`msg ${m.role}`}>{m.content}</div>
          ))}
        </div>
        <div className="composer">
          <textarea
            value={chatInput}
            placeholder="e.g. focus on legal boutiques and exclude personal injury"
            onChange={(e) => setChatInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), sendChat())}
          />
          <button disabled={busy} onClick={sendChat}>{busy ? "…" : "Send"}</button>
        </div>
      </div>

      <button disabled={busy || !offer.trim()} onClick={run}>
        {busy ? "Searching…" : "Run Lead Finder"}
      </button>
      {err && <div className="error">{err}</div>}

      {result && (
        <div className="result">
          <h3>ICP</h3>
          <p><strong>Clarified:</strong> {result.icp.clarified}</p>
          {result.icp.notes && <p className="muted">{result.icp.notes}</p>}
          <h3>Search strings</h3>
          <ul>
            {result.icp.search_terms.map((t, i) => (
              <li key={i}><code>{t.query}</code> <span className="muted">— {t.why}</span></li>
            ))}
          </ul>
          <h3>Leads ({result.leads.length})</h3>
          {result.leads.length === 0 && <p className="muted">No domains discovered. Try a broader geography or different terms.</p>}
          <div className="grid">
            {result.leads.map((l, i) => (
              <div className="card" key={i}>
                <h3><a href={`https://${l.domain}`} target="_blank" rel="noreferrer">{l.domain}</a></h3>
                <span className="badge">fit {l.score.fit_score}</span>
                <p className="muted">age: {l.audit.site_age_label || "unknown"}</p>
                {l.emails.length > 0 && <p className="muted">emails: {l.emails.join(", ")}</p>}
                {l.score.suggested_angle && <p><strong>Angle:</strong> {l.score.suggested_angle}</p>}
                {l.score.why_now && <p className="muted">why now: {l.score.why_now}</p>}
              </div>
            ))}
          </div>
          <p className="muted" style={{ whiteSpace: "pre-wrap" }}>{result.gdpr_note}</p>
        </div>
      )}

      {past.length > 0 && (
        <div className="result">
          <h3>Past runs</h3>
          {past.map((q) => (
            <div key={q.query_id} className="card">
              <h3>{q.name}</h3>
              <p className="muted">{q.offer} · {q.geography || "anywhere"} · {q.leads.length} leads</p>
              {q.leads.slice(0, 5).map((l, i) => (
                <div key={i} className="muted">• {l.domain} (fit {l.fit_score})</div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function WanVideo({ user, setError, seed = "" }) {
  const [sourceImage, setSourceImage] = useState("");
  const [concept, setConcept] = useState(seed);
  const [formatKind, setFormatKind] = useState("");
  const [title, setTitle] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function run() {
    if (!concept.trim()) {
      setErr("Describe the concept, script or mood you want turned into video.");
      return;
    }
    setBusy(true);
    setErr("");
    setResult(null);
    try {
      const res = await api.wanRun(sourceImage, concept, formatKind, title);
      // Agent returns a storyboard JSON in res.text (may need parsing for nested display)
      let data = null;
      try {
        const txt = res.text.trim();
        data = JSON.parse(txt.startsWith("```") ? txt.replace(/^```json?|```$/g, "") : txt);
      } catch {
        try { data = JSON.parse(res.text); } catch { data = null; }
      }
      setResult({ ...res, data });
      api.wanBriefs().catch(() => {});
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  const shots = result?.data?.shots || [];

  return (
    <div className="studio">
      <h2>Wan2.2 Video Prompt</h2>
      <p className="muted">
        Drop a source image (URL or reference) and your concept. We build a storyboard of
        Wan2.2 image-to-video shots — each a one-shot ~5s clip with one camera move from a
        50-move vocabulary, so stitched clips form a coherent video.
      </p>

      <div className="fields">
        <label>Source image URL<input value={sourceImage} onChange={(e) => setSourceImage(e.target.value)} placeholder="https://… or leave blank for concept-only" /></label>
        <label>Run title<input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Product reveal ad" /></label>
        <label>Format (optional)<select value={formatKind} onChange={(e) => setFormatKind(e.target.value)}>
          <option value="">free / unspecified</option>
          <option value="ad">Ad</option>
          <option value="short_film">Short film</option>
          <option value="doc">Documentary</option>
          <option value="podcast">Podcast clip</option>
          <option value="reel">Social reel</option>
        </select></label>
        <label style={{ gridColumn: "1 / -1" }}>Concept / script / mood<textarea
          value={concept}
          onChange={(e) => setConcept(e.target.value)}
          placeholder="A lone founder at a desk at night; the camera slowly pushes in as the screen lights up with the product launch…"
        /></label>
      </div>

      <button disabled={busy || !concept.trim()} onClick={run}>
        {busy ? "Storyboarding…" : "Generate Wan shots"}
      </button>
      {err && <div className="error">{err}</div>}

      {result && (
        <div className="result">
          <h3>{result.title || (result.data ? result.data.title : "Storyboard")}</h3>
          {result.data?.summary && <p className="muted">{result.data.summary}</p>}
          {result.data?.stitching_notes && <p className="muted">Stitching: {result.data.stitching_notes}</p>}
          {shots.length === 0 && <pre>{result.text}</pre>}
          <div className="grid">
            {shots.map((s, i) => (
              <div className="card" key={i}>
                <h3>Shot {s.shot}</h3>
                <span className="badge">{s.camera}</span>
                <p className="muted">Frame: {s.frame}</p>
                <p>Action: {s.action}</p>
                <p className="muted">Look: {s.look}</p>
                <p><strong>Wan prompt:</strong></p>
                <pre>{s.wan_prompt}</pre>
              </div>
            ))}
          </div>
        </div>
      )}
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
