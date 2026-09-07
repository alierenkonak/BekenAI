from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.cases import router as cases_router
from app.api.chat import router as chat_router
from app.api.conversations import router as conversations_router
from app.api.files import router as files_router
from app.api.health import router as health_router
from app.api.me import router as me_router
from app.api.search import router as search_router
from app.api.sources import router as sources_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Domain-aware, kaynağa dayalı Türk hukuku araştırma API'si.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)
app.include_router(health_router)
app.include_router(search_router)
app.include_router(me_router)
app.include_router(cases_router)
app.include_router(conversations_router)
app.include_router(chat_router)
app.include_router(files_router)
app.include_router(sources_router)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"service": settings.app_name, "docs": "/docs"}
