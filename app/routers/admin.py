"""Panel de administración: incidentes, estado de materiales y de personas.

Dos niveles de permiso:
- **Operativo** (encargado + admin): resolver incidentes y marcar materiales
  `en_reparacion`/`baja`/`disponible` (tareas del día a día de la biblioteca).
- **Admin** (solo admin): gestión de personas — aprobar la "zona gris" del
  onboarding, suspender/reactivar cuentas — y el resumen del panel.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    EstadoMaterial,
    EstadoPersona,
    Incidente,
    Material,
    Persona,
    Prestamo,
    Rol,
    Sesion,
    Titulo,
)
from ..schemas import (
    CambiarEstadoMaterialIn,
    CambiarEstadoPersonaIn,
    CambiarRolIn,
    CrearPersonaIn,
    ResolverIncidenteIn,
    SetPasswordIn,
)
from ..security import hash_password, requiere_rol

router = APIRouter(prefix="/api/admin", tags=["admin"])

Oper = Depends(requiere_rol(Rol.encargado, Rol.admin))   # operativo
AdminOnly = Depends(requiere_rol(Rol.admin))             # solo admin

# Zona gris = quedó pendiente PERO ya hizo la biometría (tiene embedding guardado).
# Se distingue así del padrón importado, que está pendiente sin embedding ni nombre.
_EN_REVISION = (Persona.estado == EstadoPersona.pendiente, Persona.foto_embedding.is_not(None))


def _describir(db: Session, m: Material) -> str:
    if m.titulo_id:
        t = db.get(Titulo, m.titulo_id)
        base = t.titulo if t else "libro"
        return f"{base} (copia {m.numero_copia})" if m.numero_copia else base
    return f"{m.tipo.value} {m.codigo_interno or ''}".strip()


def _nombre(p: Persona | None) -> str | None:
    if p is None:
        return None
    return " ".join(x for x in (p.nombre, p.apellido) if x) or ("DNI " + p.dni)


# ---------------------------------------------------------------- resumen ----
@router.get("/resumen")
def resumen(db: Session = Depends(get_db), _: Persona = AdminOnly) -> dict:
    """Contadores para el tablero del panel."""
    ahora = datetime.now(timezone.utc)
    n = lambda q: db.scalar(q) or 0
    return {
        "incidentes_abiertos": n(select(func.count()).select_from(Incidente).where(Incidente.resuelto_at.is_(None))),
        "materiales_en_reparacion": n(select(func.count()).select_from(Material).where(Material.estado == EstadoMaterial.en_reparacion)),
        "materiales_baja": n(select(func.count()).select_from(Material).where(Material.estado == EstadoMaterial.baja)),
        "revision_pendiente": n(select(func.count()).select_from(Persona).where(*_EN_REVISION)),
        "suspendidos": n(select(func.count()).select_from(Persona).where(Persona.estado == EstadoPersona.suspendido)),
        "prestamos_atrasados": n(select(func.count()).select_from(Prestamo).where(
            Prestamo.devuelto_at.is_(None), Prestamo.vence_at < ahora)),
    }


# ----------------------------------------------------- zona gris / personas ---
@router.get("/revision")
def en_revision(db: Session = Depends(get_db), _: Persona = AdminOnly) -> list[dict]:
    """Onboardings que cayeron en zona gris y esperan aprobación manual."""
    rows = db.scalars(select(Persona).where(*_EN_REVISION).order_by(Persona.creado_at)).all()
    return [{"id": p.id, "dni": p.dni, "nombre": p.nombre, "apellido": p.apellido,
             "rol": p.rol.value, "creado_at": p.creado_at.isoformat() if p.creado_at else None}
            for p in rows]


@router.get("/personas")
def buscar_personas(q: str = "", estado: str | None = None, rol: str | None = None,
                    offset: int = 0, limit: int = 50,
                    db: Session = Depends(get_db), _: Persona = AdminOnly) -> dict:
    """Lista/busca personas con filtros y paginado. Sin `q` lista todo (filtrable
    por rol/estado). Devuelve `{total, offset, limit, items}` para paginar."""
    cond = []
    q = q.strip()
    if q:
        like = f"%{q}%"
        cond.append(or_(Persona.dni.ilike(like), Persona.nombre.ilike(like),
                        Persona.apellido.ilike(like)))
    if estado in ("pendiente", "activo", "suspendido"):
        cond.append(Persona.estado == EstadoPersona(estado))
    if rol in ("alumno", "docente", "encargado", "admin"):
        cond.append(Persona.rol == Rol(rol))

    total = db.scalar(select(func.count()).select_from(Persona).where(*cond)) or 0
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    rows = db.scalars(
        select(Persona).where(*cond)
        .order_by(Persona.apellido, Persona.dni).offset(offset).limit(limit)
    ).all()
    return {
        "total": total, "offset": offset, "limit": limit,
        "items": [{"id": p.id, "dni": p.dni, "nombre": p.nombre, "apellido": p.apellido,
                   "rol": p.rol.value, "estado": p.estado.value} for p in rows],
    }


@router.post("/personas")
def crear_persona(payload: CrearPersonaIn,
                  db: Session = Depends(get_db), _: Persona = AdminOnly) -> dict:
    """Crea una persona por DNI + rol (para staff fuera del padrón, o altas sueltas).

    Staff (encargado/admin) → queda `activo` (después se le pone clave). Alumno/docente
    → queda `pendiente` (completa nombre/apellido al registrarse en el onboarding).
    """
    if db.scalar(select(Persona).where(Persona.dni == payload.dni)):
        raise HTTPException(409, f"Ya existe una persona con DNI {payload.dni}.")
    rol = Rol(payload.rol)
    es_staff = rol in (Rol.encargado, Rol.admin)
    p = Persona(dni=payload.dni, rol=rol,
                estado=EstadoPersona.activo if es_staff else EstadoPersona.pendiente)
    db.add(p)
    db.commit()
    nota = " Ponele una contraseña (🔑)." if es_staff else " Completará sus datos al registrarse."
    return {"id": p.id, "dni": p.dni, "rol": p.rol.value, "estado": p.estado.value,
            "mensaje": f"Persona creada: DNI {p.dni} ({rol.value}).{nota}"}


@router.post("/personas/{persona_id}/estado")
def cambiar_estado_persona(persona_id: int, payload: CambiarEstadoPersonaIn,
                           db: Session = Depends(get_db), actor: Persona = AdminOnly) -> dict:
    """Aprueba (activo) o suspende una persona. Al suspender, revoca sus sesiones."""
    p = db.get(Persona, persona_id)
    if p is None:
        raise HTTPException(404, "Persona no encontrada.")
    if p.id == actor.id and payload.estado == "suspendido":
        raise HTTPException(409, "No podés suspenderte a vos mismo.")
    if payload.estado == "activo":
        p.estado = EstadoPersona.activo
        if not p.qr_token:
            from ..security import nuevo_qr_token
            p.qr_token = nuevo_qr_token()
        accion = "activada"
    else:
        p.estado = EstadoPersona.suspendido
        # cortar el acceso ya: invalidar sus sesiones abiertas
        for s in db.scalars(select(Sesion).where(Sesion.persona_id == p.id, Sesion.revocada == False)).all():  # noqa: E712
            s.revocada = True
        accion = "suspendida"
    db.commit()
    return {"id": p.id, "estado": p.estado.value,
            "mensaje": f"Cuenta de {_nombre(p)} {accion}."}


@router.post("/personas/{persona_id}/rol")
def cambiar_rol(persona_id: int, payload: CambiarRolIn,
                db: Session = Depends(get_db), actor: Persona = AdminOnly) -> dict:
    """Cambia el rol de una persona (p.ej. hacerla `encargado` para el mostrador).

    No te podés cambiar tu propio rol (evita auto-bloqueo). Al pasar a staff
    (encargado/admin) se activa la cuenta para que pueda trabajar.
    """
    p = db.get(Persona, persona_id)
    if p is None:
        raise HTTPException(404, "Persona no encontrada.")
    if p.id == actor.id:
        raise HTTPException(409, "No podés cambiar tu propio rol.")
    nuevo = Rol(payload.rol)
    p.rol = nuevo
    es_staff = nuevo in (Rol.encargado, Rol.admin)
    if es_staff and p.estado == EstadoPersona.pendiente:
        p.estado = EstadoPersona.activo
    db.commit()
    extra = " (activado)" if es_staff and p.estado == EstadoPersona.activo else ""
    nota = " — falta ponerle contraseña" if es_staff and not p.password_hash else ""
    return {"id": p.id, "rol": p.rol.value, "estado": p.estado.value,
            "mensaje": f"{_nombre(p)} ahora es {nuevo.value}{extra}.{nota}"}


@router.post("/personas/{persona_id}/password")
def set_password_staff(persona_id: int, payload: SetPasswordIn,
                       db: Session = Depends(get_db), _: Persona = AdminOnly) -> dict:
    """Setea/cambia la contraseña de un usuario de staff (solo encargado/admin usan clave)."""
    p = db.get(Persona, persona_id)
    if p is None:
        raise HTTPException(404, "Persona no encontrada.")
    if p.rol not in (Rol.encargado, Rol.admin):
        raise HTTPException(409, "Solo los usuarios de staff (encargado/admin) usan contraseña. Cambiá el rol primero.")
    p.password_hash = hash_password(payload.password)
    db.commit()
    return {"id": p.id, "mensaje": f"Contraseña actualizada para {_nombre(p)}."}


# --------------------------------------------------------------- incidentes ---
@router.get("/incidentes")
def listar_incidentes(estado: str = "abiertos", db: Session = Depends(get_db),
                      _: Persona = Oper) -> list[dict]:
    """Incidentes (por defecto solo los abiertos), del más reciente al más viejo."""
    stmt = select(Incidente).order_by(Incidente.creado_at.desc())
    if estado == "abiertos":
        stmt = stmt.where(Incidente.resuelto_at.is_(None))
    rows = db.scalars(stmt.limit(200)).all()
    autores = {i.creado_por_id: db.get(Persona, i.creado_por_id) for i in rows if i.creado_por_id}
    out = []
    for i in rows:
        m = db.get(Material, i.material_id)
        out.append({
            "id": i.id, "material_id": i.material_id,
            "material": _describir(db, m) if m else f"material {i.material_id}",
            "descripcion": i.descripcion, "severidad": i.severidad.value,
            "creado_at": i.creado_at.isoformat() if i.creado_at else None,
            "creado_por": _nombre(autores.get(i.creado_por_id)),
            "resuelto": i.resuelto_at is not None,
            "resuelto_at": i.resuelto_at.isoformat() if i.resuelto_at else None,
        })
    return out


@router.post("/incidentes/{incidente_id}/resolver")
def resolver_incidente(incidente_id: int, payload: ResolverIncidenteIn,
                       db: Session = Depends(get_db), _: Persona = Oper) -> dict:
    """Marca un incidente como resuelto (o lo reabre con resuelto=false)."""
    i = db.get(Incidente, incidente_id)
    if i is None:
        raise HTTPException(404, "Incidente no encontrado.")
    i.resuelto_at = datetime.now(timezone.utc) if payload.resuelto else None
    db.commit()
    return {"id": i.id, "resuelto": i.resuelto_at is not None,
            "mensaje": "Incidente resuelto." if payload.resuelto else "Incidente reabierto."}


# ------------------------------------------------------- estado de material ---
@router.get("/materiales_fuera")
def materiales_fuera(db: Session = Depends(get_db), _: Persona = Oper) -> list[dict]:
    """Materiales fuera de servicio (en reparación o de baja), para reactivarlos."""
    rows = db.scalars(
        select(Material).where(Material.estado.in_(
            (EstadoMaterial.en_reparacion, EstadoMaterial.baja)))
    ).all()
    return [{"id": m.id, "descripcion": _describir(db, m), "estado": m.estado.value} for m in rows]


@router.post("/material/{material_id}/estado")
def cambiar_estado_material(material_id: int, payload: CambiarEstadoMaterialIn,
                            db: Session = Depends(get_db), _: Persona = Oper) -> dict:
    """Marca un material `disponible` / `en_reparacion` / `baja`.

    No se puede tocar un material `prestado` (primero hay que devolverlo).
    """
    m = db.get(Material, material_id)
    if m is None:
        raise HTTPException(404, "Material no encontrado.")
    if m.estado == EstadoMaterial.prestado:
        raise HTTPException(409, "Está prestado: primero registrá la devolución.")
    m.estado = EstadoMaterial(payload.estado)
    db.commit()
    return {"id": m.id, "estado": m.estado.value,
            "mensaje": f"{_describir(db, m)} → {m.estado.value}."}
