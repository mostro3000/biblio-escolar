"""Login / logout / sesión actual del staff."""
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Persona, Sesion
from ..ratelimit import rate_limit
from ..schemas import LoginIn, MeOut
from ..security import COOKIE, DURACION, crear_sesion, usuario_actual, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

_login_rl = Depends(rate_limit("login", settings.login_rate_max, settings.login_rate_window))


def _me(persona: Persona) -> MeOut:
    return MeOut(dni=persona.dni, nombre=persona.nombre, apellido=persona.apellido, rol=persona.rol.value)


@router.post("/login", response_model=MeOut)
def login(payload: LoginIn, response: Response, db: Session = Depends(get_db), _rl: None = _login_rl) -> MeOut:
    persona = db.scalar(select(Persona).where(Persona.dni == payload.dni))
    # Mismo mensaje para DNI inexistente o contraseña mala (no filtrar cuáles existen).
    if persona is None or not verify_password(payload.password, persona.password_hash):
        raise HTTPException(401, "DNI o contraseña incorrectos.")
    token = crear_sesion(db, persona)
    response.set_cookie(
        COOKIE, token,
        max_age=int(DURACION.total_seconds()),
        httponly=True, secure=True, samesite="strict", path="/",
    )
    return _me(persona)


@router.post("/logout")
def logout(
    response: Response,
    biblio_sesion: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> dict:
    if biblio_sesion:
        sesion = db.get(Sesion, biblio_sesion)
        if sesion:
            sesion.revocada = True
            db.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me", response_model=MeOut)
def me(persona: Persona = Depends(usuario_actual)) -> MeOut:
    return _me(persona)
