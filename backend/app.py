from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import get_settings
from backend.db import init_db
from backend.routes import agents, auth, billing, pipeline, router as router_routes, planner, leadfinder, wan, social, editorial
from backend.routes.agents import close_llm
from backend.routes.router import close_router_llm
from backend.routes.planner import close_planner_llm
from backend.routes.leadfinder import close_leadfinder_llm
from backend.routes.wan import close_wan_llm

_settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield
    close_llm()
    close_router_llm()
    close_planner_llm()
    close_leadfinder_llm()
    close_wan_llm()


app = FastAPI(title="Gadgents", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(agents.router)
app.include_router(billing.router)
app.include_router(pipeline.router)
app.include_router(router_routes.router)
app.include_router(planner.router)
app.include_router(leadfinder.router)
app.include_router(wan.router)
app.include_router(social.router)
app.include_router(editorial.router)


@app.get("/health")
def health():
    return {"status": "ok", "providers": _settings.llm_provider_order}


@app.get("/api/config")
def app_config():
    # Public flag so the frontend can skip the login screen in dev-bypass mode
    # (REQUIRE_LOGIN=false) without needing a token.
    return {
        "require_login": _settings.require_login,
        "enable_paywall": _settings.enable_paywall,
        "providers": _settings.llm_provider_order,
    }
