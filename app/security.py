"""Auth de staff: hashing de contraseñas, sesiones por cookie y dependencies.

Alumnos/docentes usan el flujo biométrico + QR; el staff (encargado/admin) entra
con DNI + contraseña. La sesión es un token opaco guardado en la tabla `sesion`,
referenciado por una cookie HttpOnly.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.orm import Session

from .db import get_db
from .models import EstadoPersona, Persona, Rol, Sesion

COOKIE = "biblio_sesion"
DURACION = timedelta(hours=12)
_ITER = 600_000  # iteraciones PBKDF2 (recomendación OWASP para sha256)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITER)
    return f"pbkdf2_sha256${_ITER}${salt.hex()}${h.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        _, iters, salt_hex, hash_hex = stored.split("$")
        h = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(h.hex(), hash_hex)
    except Exception:
        return False


ARG_TZ = timezone(timedelta(hours=-3))  # Argentina (sin horario de verano)


def fin_de_anio(ahora: datetime | None = None) -> datetime:
    """Fin del año escolar: 31/dic 23:59:59 (hora ARG) del año en curso, en UTC.

    La sesión de alumno/docente caduca acá → cada año re-verifican (re-login por
    selfie, pendiente). Como el padrón cambia año a año, el corte anual es higiene.
    El staff no usa esto (su sesión es corta, por contraseña).
    """
    ahora = ahora or datetime.now(timezone.utc)
    arg = ahora.astimezone(ARG_TZ)
    return datetime(arg.year, 12, 31, 23, 59, 59, tzinfo=ARG_TZ).astimezone(timezone.utc)


def nuevo_qr_token() -> str:
    return secrets.token_urlsafe(12)


def crear_sesion(db: Session, persona: Persona, duracion: timedelta = DURACION,
                 expira_at: datetime | None = None) -> str:
    """Crea una sesión. `expira_at` absoluto (p.ej. fin de año para alumnos) tiene
    prioridad sobre `duracion` (relativa, default para staff)."""
    token = secrets.token_urlsafe(32)
    exp = expira_at if expira_at is not None else datetime.now(timezone.utc) + duracion
    db.add(Sesion(id=token, persona_id=persona.id, expira_at=exp))
    db.commit()
    return token


def usuario_actual(
    biblio_sesion: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> Persona:
    """Dependency: devuelve la persona logueada o 401/403."""
    if not biblio_sesion:
        raise HTTPException(401, "No autenticado")
    sesion = db.get(Sesion, biblio_sesion)
    if sesion is None or sesion.revocada or sesion.expira_at < datetime.now(timezone.utc):
        raise HTTPException(401, "Sesión inválida o expirada")
    persona = db.get(Persona, sesion.persona_id)
    if persona is None or persona.estado == EstadoPersona.suspendido:
        raise HTTPException(403, "Cuenta no habilitada")
    return persona


def requiere_rol(*roles: Rol):
    """Dependency factory: exige que la persona tenga uno de los roles dados."""
    def dep(persona: Persona = Depends(usuario_actual)) -> Persona:
        if persona.rol not in roles:
            raise HTTPException(403, "No tenés permiso para esto")
        return persona
    return dep
