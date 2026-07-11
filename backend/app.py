from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import get_settings
from backend.db import init_db
from backend.routes import agents, auth, billing, pipeline, router as router_routes, planner, repurposer, leadfinder
from backend.routes.agents import close_llm
from backend.routes.router import close_router_llm
from backend.routes.planner import close_planner_llm
from backend.routes.repurposer import close_repurposer_llm
from backend.routes.leadfinder import close_leadfinder_llm

_settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield
    close_llm()
    close_router_llm()
    close_planner_llm()
    close_repurposer_llm()
    close_leadfinder_llm()


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
app.include_router(repurposer.router)
app.include_router(leadfinder.router)


@app.get("/health")
def health():
    return {"status": "ok", "providers": _settings.llm_provider_order}
