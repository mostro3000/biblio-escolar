"""Motor y sesión de SQLAlchemy."""
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    """Base declarativa de todos los modelos."""


# El engine es None hasta que se configure DATABASE_URL, así la app
# arranca igual (útil para el health-check antes de tener PostgreSQL).
engine = (
    create_engine(settings.database_url, pool_pre_ping=True, future=True)
    if settings.database_url
    else None
)
SessionLocal = (
    sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    if engine is not None
    else None
)


def get_db() -> Iterator[Session]:
    """Dependencia de FastAPI: una sesión por request."""
    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL no configurada")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
