"""Endpoints del usuario logueado (su credencial y sus préstamos)."""
from fastapi import APIRouter, Cookie, Depends, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import (
    TIPO_LABEL,
    EstadoMaterial,
    Material,
    Persona,
    Prestamo,
    Rol,
    Sesion,
    TipoCodigo,
    TipoMaterial,
    Titulo,
)
from ..security import COOKIE, fin_de_anio, nuevo_qr_token, usuario_actual

router = APIRouter(prefix="/api/mi", tags=["mi"])


def _describir_material(db: Session, material: Material | None) -> str:
    if material is None:
        return "material"
    if material.titulo_id:
        titulo = db.get(Titulo, material.titulo_id)
        nombre = titulo.titulo if titulo else "libro"
        return f"{nombre} (copia {material.numero_copia})" if material.numero_copia else nombre
    return f"{TIPO_LABEL.get(material.tipo.value, material.tipo.value)} {material.codigo_interno or ''}".strip()


@router.get("/credencial")
def credencial(
    response: Response,
    persona: Persona = Depends(usuario_actual),
    db: Session = Depends(get_db),
    biblio_sesion: str | None = Cookie(default=None),
) -> dict:
    """Datos para mostrar el QR rotativo. Genera el qr_token (secreto) si falta.

    Devuelve el **secreto** y la ventana: el celular calcula el código TOTP
    localmente (offline) y arma el QR. El secreto nunca viaja dentro del QR.

    Sesión hasta fin del año escolar: para alumno/docente, abrir la credencial
    refresca la sesión y la cookie hasta el 31/dic (DB + cookie). Una vez registrado
    no pone clave ni re-onboardea durante el año; el staff conserva su sesión corta.
    """
    if not persona.qr_token:
        persona.qr_token = nuevo_qr_token()
        db.commit()

    if persona.rol in (Rol.alumno, Rol.docente) and biblio_sesion:
        sesion = db.get(Sesion, biblio_sesion)
        if sesion and not sesion.revocada:
            exp = fin_de_anio()
            sesion.expira_at = exp
            db.commit()
            response.set_cookie(
                COOKIE, biblio_sesion, expires=exp,
                httponly=True, secure=True, samesite="strict", path="/",
            )

    return {
        "dni": persona.dni,
        "nombre": persona.nombre,
        "apellido": persona.apellido,
        "rol": persona.rol.value,
        "qr_secret": persona.qr_token,
        "qr_step": settings.qr_step_seconds,
    }


@router.get("/disponibilidad")
def disponibilidad(q: str = "", persona: Persona = Depends(usuario_actual),
                   db: Session = Depends(get_db)) -> dict:
    """Disponibilidad de materiales para el alumno/docente: ¿hay alguno sin prestar?

    Devuelve SOLO conteos (total y disponibles), nunca quién tiene qué (privacidad).
    `tech` se agrupa por tipo (netbooks, etc.); `libros` se buscan por título/autor si hay `q`.
    """
    tech = [{"tipo": tipo.value, "tipo_label": TIPO_LABEL.get(tipo.value, tipo.value),
             "total": total, "disponibles": disp}
            for tipo, total, disp in db.execute(
                select(Material.tipo, func.count(),
                       func.count().filter(Material.estado == EstadoMaterial.disponible))
                .where(Material.tipo_codigo == TipoCodigo.interno,
                       Material.tipo != TipoMaterial.libro)  # los libros sin ISBN van con libros
                .group_by(Material.tipo).order_by(Material.tipo)).all()]

    libros: list[dict] = []
    q = q.strip()
    if q:
        like = f"%{q}%"
        titulos = db.scalars(
            select(Titulo).where(or_(Titulo.titulo.ilike(like), Titulo.autor.ilike(like)))
            .order_by(Titulo.titulo).limit(40)
        ).all()
        ids = [t.id for t in titulos]
        cont: dict[int, tuple[int, int]] = {}
        if ids:
            for tid, tot, disp in db.execute(
                select(Material.titulo_id, func.count(),
                       func.count().filter(Material.estado == EstadoMaterial.disponible))
                .where(Material.titulo_id.in_(ids)).group_by(Material.titulo_id)).all():
                cont[tid] = (tot, disp)
        libros = [{"titulo": t.titulo, "autor": t.autor, "cover_url": t.cover_url,
                   "total": cont.get(t.id, (0, 0))[0], "disponibles": cont.get(t.id, (0, 0))[1]}
                  for t in titulos]
    return {"tech": tech, "libros": libros}


@router.get("/prestamos")
def mis_prestamos(persona: Persona = Depends(usuario_actual), db: Session = Depends(get_db)) -> list[dict]:
    """Préstamos activos (sin devolver) del usuario."""
    activos = db.scalars(
        select(Prestamo).where(Prestamo.persona_id == persona.id, Prestamo.devuelto_at.is_(None))
    ).all()
    return [
        {
            "prestamo_id": p.id,
            "material": _describir_material(db, db.get(Material, p.material_id)),
            "vence_at": p.vence_at.isoformat() if p.vence_at else None,
        }
        for p in activos
    ]
