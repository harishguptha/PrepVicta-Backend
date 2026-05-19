from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.database import get_pool, close_pool
from app.db.init import init_db
from app.routers.auth import router as auth_router
from app.routers.planning_agent import router as planning_agent_router
from app.routers.learn import router as learn_router
from app.routers.revision import router as revision_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = await get_pool()
    await init_db(pool)
    yield
    await close_pool()


app = FastAPI(
    title="PrepVicta Backend",
    description="AI-powered NEET preparation backend services.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(planning_agent_router)
app.include_router(auth_router)
app.include_router(learn_router)
app.include_router(revision_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
