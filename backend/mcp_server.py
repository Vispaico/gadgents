"""MCP (Model Context Protocol) server for Gadgents agents.

Exposes every Gadgents agent + composite workflow as MCP tools, authenticating via
long-lived API keys (Bearer tokens in the Authorization header). Hermes agents in
Mattermost connect here to call Gadgents as their tool arsenal.

Runs as a separate FastAPI app on port :8100 (configurable via MCP_PORT in .env),
started as a daemon thread by app.py. The transport is MCP Streamable HTTP
(https://spec.modelcontextprotocol.io/specification/2025-03-26/basic/transports/#streamable-http).

Protocol summary:
  POST /mcp        — JSON-RPC 2.0: initialize, tools/list, tools/call, ping
  GET  /mcp        — SSE stream (optional; we serve a minimal event stream)
  DELETE /mcp      — session teardown

Auth: Authorization: Bearer <gadgents_...> header on every POST request.
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import FastAPI, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session

from backend.auth import authenticate_api_key
from backend.agents import get_agent, run_agent
from backend.billing import charge
from backend.config import get_settings
from backend.db import User, get_engine
from backend.llm import LLMClient

_settings = get_settings()

# ---------------------------------------------------------------------------
# Tool definitions — one per agent + one per composite workflow
# ---------------------------------------------------------------------------
TOOLS: list[dict] = [
    # --- Individual agents (chat-style) ---
    {
        "name": "gadgents_prompt_engineer",
        "description": (
            "Turn raw material (article text, notes, URLs) into per-platform content "
            "generation prompts. Input: an essay/article/idea plus desired platforms "
            "(e.g. LinkedIn, X, Instagram). Output: structured prompts ready for a content "
            "producer agent."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "material": {"type": "string", "description": "Raw article text, notes, or idea"},
                "platforms": {"type": "array", "items": {"type": "string"}, "default": ["LinkedIn", "X"]},
            },
            "required": ["material"],
        },
    },
    {
        "name": "gadgents_content_producer",
        "description": (
            "Convert a prompt or brief into finished, platform-ready social content. "
            "Input: prompt text or brief + platforms. Output: captions, hooks, hashtags, "
            "posting tips per platform."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Content prompt or brief"},
                "platforms": {"type": "array", "items": {"type": "string"}, "default": ["LinkedIn", "X"]},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "gadgents_coder",
        "description": (
            "Answer coding questions and write small code snippets. Concise senior-engineer "
            "style output with working code and short explanations."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Coding question or task"},
            },
            "required": ["question"],
        },
    },
    {
        "name": "gadgents_personal_planner",
        "description": (
            "Turn a messy brain-dump into a structured day plan with tasks, time blocks, "
            "reminders, and learned preferences. Output: JSON tasks, time_blocks, reminders, "
            "classified inbox items, and new learned preferences."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dump": {"type": "string", "description": "Raw brain dump / todo / plan text"},
            },
            "required": ["dump"],
        },
    },
    # --- Composite workflows ---
    {
        "name": "gadgents_content_studio",
        "description": (
            "Take source material (article, notes) + target platforms and run the "
            "full two-stage content pipeline: prompt engineer -> content producer. Optionally "
            "add style instructions that guide the output tone. The quality/cost mode toggles "
            "the content-producer model (economic=llama33, balanced=qwen37, quality=aion-storytelling)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "material": {"type": "string", "description": "Raw article text, notes, or idea"},
                "platforms": {"type": "array", "items": {"type": "string"}, "default": ["LinkedIn", "X"]},
                "instructions": {"type": "string", "default": "", "description": "Optional style or tone instructions"},
                "mode": {"type": "string", "enum": ["economic", "balanced", "quality"], "default": "balanced"},
            },
            "required": ["material"],
        },
    },
    {
        "name": "gadgents_content_repurpose",
        "description": (
            "Repurpose a long article/essay into multi-platform social posts (LinkedIn, "
            "Facebook, X, Instagram, YouTube, Shorts/TikTok) with media suggestions and a "
            "short video script package. Preserves the source voice, never fabricates facts. "
            "Uses a multi-model Fusion panel for quality."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "material": {"type": "string", "description": "Long article or essay text"},
                "platforms": {"type": "array", "items": {"type": "string"}, "default": ["LinkedIn", "X", "Instagram"]},
                "instructions": {"type": "string", "default": "", "description": "Optional tone/style instructions"},
                "mode": {"type": "string", "enum": ["economic", "mixed", "high"], "default": "mixed"},
            },
            "required": ["material"],
        },
    },
    {
        "name": "gadgents_lead_finder",
        "description": (
            "Run the Lead Finder chain: from an ICP definition (offer, geography, target "
            "niches, company size, language), discover companies on the public web, audit "
            "their digital presence, score fit (0-100), and propose outreach angles. "
            "GDPR-safe: public web + business emails only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "offer": {"type": "string", "description": "What you sell / your service"},
                "geography": {"type": "string", "description": "Target locality/region", "default": ""},
                "target_description": {"type": "string", "description": "Target niches/industries, exclusions, any ICP nuance"},
                "company_size": {"type": "string", "description": "e.g. '11-50', '1-10', '' for any", "default": ""},
                "language": {"type": "string", "default": "en"},
                "name": {"type": "string", "description": "Human label for this run", "default": ""},
                "mode": {"type": "string", "enum": ["economic", "mixed", "high"], "default": "mixed"},
            },
            "required": ["offer", "target_description"],
        },
    },
    {
        "name": "gadgents_wan_video",
        "description": (
            "Generate a Wan2.2 image-to-video storyboard. Input a concept + optional source "
            "image reference + optional format (ad, short_film, doc, reel). Returns a shot-by-shot "
            "storyboard with camera moves and ready-to-paste Wan2.2 prompts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "concept": {"type": "string", "description": "Concept, script, or mood to visualize"},
                "source_image": {"type": "string", "description": "URL or description of the seed image", "default": ""},
                "format_kind": {"type": "string", "enum": ["ad", "short_film", "doc", "reel", ""], "default": ""},
                "mode": {"type": "string", "enum": ["economic", "mixed", "high"], "default": "mixed"},
            },
            "required": ["concept"],
        },
    },
    {
        "name": "gadgents_social_listen",
        "description": (
            "Listen to what's being said on X and/or LinkedIn for a given topic. Returns "
            "posts sorted by engagement (likes) with author, text, engagement counts, and URL. "
            "Requires a configured CloakBrowser profile on the server."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Topic to search"},
                "platforms": {"type": "array", "items": {"type": "string", "enum": ["x", "linkedin"]},
                               "default": ["x"]},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "gadgents_brain_query",
        "description": (
            "Query the Gadgents knowledge base (OpenKB wiki) for information saved via "
            "previous Social Listen / Content Studio saves. Returns a grounded answer "
            "with source citations from the compiled wiki."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Question to ask the knowledge base"},
            },
            "required": ["question"],
        },
    },
    {
        "name": "gadgents_brain_save",
        "description": (
            "Save a result into the Gadgents knowledge base (OpenKB/wiki). The content "
            "will be compiled into the wiki and become searchable via gadgents_brain_query."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Title for the saved knowledge item"},
                "body": {"type": "string", "description": "Content to save (markdown style welcome)"},
            },
            "required": ["title", "body"],
        },
    },
]

# ---------------------------------------------------------------------------
# LLM client (health-aware, shared across tool calls).
# ---------------------------------------------------------------------------
_llm = LLMClient()

# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------
def _resolve_user(auth_header: str) -> Optional["User"]:
    if not auth_header.startswith("Bearer "):
        return None
    raw_key = auth_header[len("Bearer "):].strip()
    return authenticate_api_key(raw_key)


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------
def _call_agent(agent_id: str, user_input: str, user, mode: str | None = None) -> dict:
    agent_def = get_agent(agent_id)
    if agent_def is None or not agent_def.production_ready:
        raise ValueError(f"Agent '{agent_id}' is not available")
    text, ti, to, credits = run_agent(agent_def, user_input, _llm, override_mode=mode)
    with Session(get_engine()) as session:
        charge(session, user, agent_id, credits, ti, to)
    return {"result": text, "agent_id": agent_id, "credits_estimate": credits}


def _execute_tool(name: str, args: dict, user) -> dict:
    mode = args.get("mode", None)

    if name == "gadgents_prompt_engineer":
        material = args.get("material", "")
        platforms = args.get("platforms", ["LinkedIn", "X"])
        user_input = f"Source material:\n\"\"\"\n{material}\n\"\"\"\n\nProduce generation prompts for: {', '.join(platforms)}."
        return _call_agent("prompt-engineer", user_input, user)

    if name == "gadgents_content_producer":
        prompt = args.get("prompt", "")
        platforms = args.get("platforms", ["LinkedIn", "X"])
        user_input = f"Prompt:\n\"\"\"\n{prompt}\n\"\"\"\n\nProduce finished content for: {', '.join(platforms)}."
        return _call_agent("content-producer", user_input, user, mode=mode)

    if name == "gadgents_coder":
        return _call_agent("coder", args.get("question", ""), user)

    if name == "gadgents_personal_planner":
        return _call_agent("personal-planner", args.get("dump", ""), user)

    if name == "gadgents_content_studio":
        material = args.get("material", "")
        platforms = args.get("platforms", ["LinkedIn", "X"])
        instructions = args.get("instructions", "")
        mode_map = {"economic": "economic", "balanced": "balanced", "quality": "high"}
        internal_mode = mode_map.get(mode, "balanced")
        from backend.pipeline import run_content_pipeline
        with Session(engine) as session:
            result = run_content_pipeline(
                session, user, material, platforms, _llm,
                mode=internal_mode, output_mode="content",
                instructions=instructions,
            )
        return {"content": result["content"], "prompts": result.get("prompts", ""), "credits_used": result["credits_used"]}

    if name == "gadgents_content_repurpose":
        material = args.get("material", "")
        platforms = args.get("platforms", ["LinkedIn", "X", "Instagram"])
        instructions_block = (
            f"EXPLICIT INSTRUCTIONS:\n\"\"\"\n{args.get('instructions', '').strip()}\n\"\"\""
            if args.get("instructions", "").strip() else ""
        )
        channel_map = {
            "Instagram": "instagram", "TikTok": "shorts_tiktok", "LinkedIn": "linkedin",
            "X": "x", "YouTube": "youtube", "Facebook": "facebook",
        }
        channels = [channel_map.get(p, p) for p in platforms]
        user_input = (
            f"Audience: general\nProduce outputs for these platforms ONLY: {', '.join(channels)}.\n"
            f"ARTICLE / ESSAY:\n\"\"\"\n{material}\n\"\"\""
            + (f"\n\n{instructions_block}" if instructions_block else "")
        )
        return _call_agent("content-repurposer", user_input, user, mode=mode)

    if name == "gadgents_lead_finder":
        from backend.leads.models import ICPInput
        from backend.leads.agent import run_and_persist
        icp = ICPInput(
            name=args.get("name", ""),
            offer=args.get("offer", ""),
            geography=args.get("geography", ""),
            target_description=args.get("target_description", ""),
            company_size=args.get("company_size", ""),
            language=args.get("language", "en"),
        )
        with Session(engine) as session:
            result = run_and_persist(icp, _llm, session, user=user, mode=mode)
        return {
            "icp": result.icp.model_dump() if hasattr(result, 'icp') else {},
            "leads": [getattr(l, 'model_dump', lambda: str(l))() for l in result.leads] if hasattr(result, 'leads') else [],
            "leads_count": len(result.leads) if hasattr(result, 'leads') else 0,
            "gdpr_note": getattr(result, 'gdpr_note', ""),
        }

    if name == "gadgents_wan_video":
        concept = args.get("concept", "")
        source_image = args.get("source_image", "")
        format_kind = args.get("format_kind", "")
        user_input = (
            f"SOURCE IMAGE: {source_image or '(none provided)'}\n"
            f"FORMAT PRESET: {format_kind or 'free'}\n"
            f"CONCEPT:\n\"\"\"\n{concept}\n\"\"\""
        )
        return _call_agent("wan-video", user_input, user, mode=mode)

    if name == "gadgents_social_listen":
        from backend.social import listen as run_listen
        topic = args.get("topic", "")
        platforms = args.get("platforms", ["x"])
        limit = args.get("limit", 20)
        posts = run_listen(platforms, topic, limit)
        return {"topic": topic, "platforms": platforms, "count": len(posts), "posts": posts}

    if name == "gadgents_brain_query":
        return _call_brain_query(args.get("question", ""))

    if name == "gadgents_brain_save":
        return _call_brain_save(args.get("title", ""), args.get("body", ""))

    return {"error": f"Unknown tool: {name}"}


# ---------------------------------------------------------------------------
# Brain helpers (in-process, reusing the brain module)
# ---------------------------------------------------------------------------
def _call_brain_query(question: str) -> dict:
    """Run openkb query against the brain wiki."""
    import os, subprocess
    from pathlib import Path
    from backend.config import get_settings
    from shutil import which

    brain_dir = Path(__file__).resolve().parent.parent / "brain"
    if not which("openkb"):
        return {"error": "openkb not installed on the server — brain queries unavailable", "answer": None}

    env = dict(os.environ)
    s = get_settings()
    if s.openrouter_api_key:
        env["OPENROUTER_API_KEY"] = s.openrouter_api_key

    try:
        proc = subprocess.run(
            ["openkb", "query", question],
            cwd=str(brain_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return {"answer": None, "error": "Brain query timed out (>5 min)"}
    if proc.returncode != 0:
        return {"answer": None, "error": f"openkb query failed: {proc.stderr[:500]}"}
    answer = (proc.stdout or "").strip()
    import re
    sources = sorted(set(re.findall(r"\[\[([^\]]+)\]\]", answer)))
    return {"answer": answer, "sources": sources}


def _call_brain_save(title: str, body: str) -> dict:
    """Save content to the brain KB (write .md + call openkb add)."""
    import os
    import subprocess
    from datetime import datetime, timezone
    from pathlib import Path
    from shutil import which
    from backend.config import get_settings

    brain_dir = Path(__file__).resolve().parent.parent / "brain"
    raw_dir = brain_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    slug = title.lower().replace(" ", "-")
    slug = "".join(c for c in slug if c.isalnum() or c in "-_").strip("-")[:60] or "note"
    stamp_fn = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fname = f"{stamp_fn}-{slug}.md"
    fpath = raw_dir / fname

    md = f"# {title}\n\n> saved via API: {stamp_fn}\n\n{body}\n"
    fpath.write_text(md, encoding="utf-8")

    if not which("openkb"):
        return {"saved_file": str(fpath), "indexed": False, "note": "openkb not installed — file saved only"}

    env = dict(os.environ)
    s = get_settings()
    if s.openrouter_api_key:
        env["OPENROUTER_API_KEY"] = s.openrouter_api_key

    try:
        proc = subprocess.run(
            ["openkb", "add", str(fpath)],
            cwd=str(brain_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return {"saved_file": str(fpath), "indexed": False, "note": "openkb add timed out"}

    if proc.returncode != 0:
        return {"saved_file": str(fpath), "indexed": False, "note": f"openkb add failed: {proc.stderr[:300]}"}

    out = (proc.stdout or "") + (proc.stderr or "")
    if "Compilation failed" in out or "RateLimitError" in out:
        return {"saved_file": str(fpath), "indexed": False, "note": "file saved; compile hit rate limit"}
    return {"saved_file": str(fpath), "indexed": True}


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 handlers
# ---------------------------------------------------------------------------
def _ok(rpc_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def _err(rpc_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


async def _handle_jsonrpc(body: dict, request: Request) -> dict:
    method = body.get("method", "")
    params = body.get("params", {})
    rpc_id = body.get("id")

    try:
        if method == "initialize":
            return _ok(rpc_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "gadgents-mcp", "version": "2.0.0"},
            })

        if method == "notifications/initialized":
            return {}

        if method == "tools/list":
            return _ok(rpc_id, {"tools": TOOLS})

        if method == "tools/call":
            auth_header = request.headers.get("Authorization", "")
            user = _resolve_user(auth_header)
            if user is None:
                return _err(rpc_id, -32001, "Unauthorized: valid Bearer API key required")

            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})
            result = _execute_tool(tool_name, tool_args, user)
            return _ok(rpc_id, {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}],
            })

        return _err(rpc_id, -32601, f"Method not found: {method}")

    except Exception as exc:
        import traceback
        return _err(rpc_id, -32000, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-2000:]}")


# ---------------------------------------------------------------------------
# FastAPI app for the MCP server
# ---------------------------------------------------------------------------
engine = get_engine()

mcp_app = FastAPI(title="Gadgents MCP", version="2.0.0")

mcp_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@mcp_app.post("/mcp")
async def mcp_jsonrpc(request: Request, body: dict = Body(...)):
    return await _handle_jsonrpc(body, request)


@mcp_app.get("/mcp")
async def mcp_sse():
    """Minimal SSE endpoint for the MCP streamable HTTP transport."""
    from starlette.responses import StreamingResponse

    async def event_stream():
        import asyncio
        yield "event: endpoint\ndata: /mcp\n\n"
        while True:
            try:
                yield f":\n\n"
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@mcp_app.delete("/mcp")
async def mcp_delete():
    return {"jsonrpc": "2.0", "id": None, "result": {}}


@mcp_app.get("/health")
async def mcp_health():
    return {"status": "ok", "name": "gadgents-mcp", "tools_count": len(TOOLS)}


def start_mcp_server() -> None:
    """Start the MCP server in a daemon thread on port 8100 (or MCP_PORT from .env)."""
    import threading
    import uvicorn

    port = getattr(_settings, 'mcp_port', None)
    if port:
        port = int(port)
    else:
        port = 8100

    def _run():
        uvicorn.run(mcp_app, host="0.0.0.0", port=port, log_level="warning")

    t = threading.Thread(target=_run, daemon=True, name="gadgents-mcp")
    t.start()
    return t
