"""App FastAPI del sistema de biblioteca (biblioteca escolar).

Detrás de Apache, que hace ProxyPass /api/ -> localhost:8091/api/.
Por eso todas las rutas viven bajo el prefijo /api.

SPDX-License-Identifier: GPL-3.0-or-later
Biblio — sistema de préstamos de biblioteca escolar. Licencia GNU GPL v3 (ver LICENSE).
"""
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, FastAPI
from sqlalchemy import text

from .config import settings
from .db import engine
from .routers import admin, auth, materiales, mi, mostrador, onboarding, push, reportes


def _version() -> str:
    """Versión del sistema (fuente única: archivo VERSION en la raíz del proyecto)."""
    for p in (Path("/opt/biblio/VERSION"), Path(__file__).resolve().parent.parent / "VERSION"):
        try:
            return p.read_text().strip()
        except OSError:
            continue
    return "1.0.0"


app = FastAPI(
    title="Biblioteca Escolar",
    version=_version(),
    # docs y openapi también bajo /api para que pasen por el proxy de Apache
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

api = APIRouter(prefix="/api")


@api.get("/health")
def health() -> dict:
    """Chequeo de salud: circuito Apache -> FastAPI y conexión a PostgreSQL."""
    db_ok: bool | None = None
    if engine is not None:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            db_ok = True
        except Exception:
            db_ok = False
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": app.version,
        "db_configured": bool(settings.database_url),
        "db_ok": db_ok,
        "time": datetime.now(timezone.utc).isoformat(),
    }


app.include_router(api)
app.include_router(auth.router)
app.include_router(onboarding.router)
app.include_router(materiales.router)
app.include_router(mi.router)
app.include_router(mostrador.router)
app.include_router(admin.router)
app.include_router(reportes.router)
app.include_router(push.router)
