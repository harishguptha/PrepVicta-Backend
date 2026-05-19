from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.config import get_settings
from app.db.database import get_pool, close_pool
from app.db.init import init_db
from app.observability import RequestLoggingMiddleware, configure_logging
from app.routers.auth import router as auth_router
from app.routers.planning_agent import router as planning_agent_router
from app.routers.learn import router as learn_router
from app.routers.revision import router as revision_router
from app.routers.dashboard import router as dashboard_router
from app.security import SecurityMiddleware

settings = get_settings()
configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_required_for_startup()
    pool = await get_pool()
    await init_db(pool)
    yield
    await close_pool()


app = FastAPI(
    title=settings.app_name,
    description="AI-powered NEET preparation backend services.",
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(SecurityMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
)

app.include_router(planning_agent_router)
app.include_router(auth_router)
app.include_router(learn_router)
app.include_router(revision_router)
app.include_router(dashboard_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def readiness_check() -> dict[str, str]:
    pool = await get_pool()
    await pool.fetchval("SELECT 1")
    return {"status": "ready"}
