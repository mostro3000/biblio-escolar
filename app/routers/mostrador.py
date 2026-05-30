"""Mostrador: préstamo (y luego devolución). Solo encargado/admin."""
from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..isbn import normalizar_isbn
from .. import qr_totp
from ..models import (
    TIPO_LABEL,
    CondicionDevolucion,
    EstadoMaterial,
    EstadoPersona,
    Incidente,
    Material,
    Persona,
    Prestamo,
    Rol,
    Severidad,
    TipoMaterial,
    Titulo,
)
from ..schemas import DevolucionIn, PrestamoIn
from ..security import ARG_TZ, requiere_rol

router = APIRouter(prefix="/api/mostrador", tags=["mostrador"])

Staff = Depends(requiere_rol(Rol.encargado, Rol.admin, Rol.directivo))

# Días de préstamo por tipo y rol (tabla del diseño; configurable a futuro).
DIAS_PRESTAMO = {
    TipoMaterial.libro: {"docente": 14, "_": 7},
    TipoMaterial.netbook: {"_": 0},
    TipoMaterial.adaptador: {"_": 0},
    TipoMaterial.raton: {"_": 0},
    TipoMaterial.raspberry: {"_": 0},
    TipoMaterial.mapa: {"docente": 3, "_": 1},
    TipoMaterial.otro: {"_": 7},
}


def _vencimiento(tipo: TipoMaterial, rol: Rol, override: int | None) -> datetime:
    cfg = DIAS_PRESTAMO.get(tipo, {"_": 7})
    dias = override if override is not None else cfg.get(rol.value, cfg["_"])
    # En hora local ARG: "hoy ARG" + días, fin de ese día (23:59:59 ARG), guardado
    # como UTC. Evita el corrimiento de ~3h y que de noche salte al día siguiente.
    fecha = (datetime.now(ARG_TZ) + timedelta(days=dias)).date()
    return datetime.combine(fecha, time(23, 59, 59), tzinfo=ARG_TZ).astimezone(timezone.utc)


def _describir(db: Session, m: Material) -> str:
    if m.titulo_id:
        t = db.get(Titulo, m.titulo_id)
        return f"{t.titulo} (copia {m.numero_copia})" if t else f"libro copia {m.numero_copia}"
    return f"{TIPO_LABEL.get(m.tipo.value, m.tipo.value)} {m.codigo_interno or ''}".strip()


@router.get("/persona/{codigo}")
def persona_por_qr(codigo: str, db: Session = Depends(get_db), _: Persona = Staff) -> dict:
    """El encargado escanea el QR rotativo del usuario: ficha + préstamos + alertas.

    `codigo` es el TOTP del momento (no un token fijo). Se resuelve a la persona
    validando contra la ventana actual ±1. El `persona_id` devuelto es lo que se
    usa para confirmar el préstamo (el código ya habrá rotado para entonces).
    """
    p = qr_totp.resolver_persona(db, codigo)
    if p is None:
        raise HTTPException(404, "QR no reconocido o vencido.")
    ahora = datetime.now(timezone.utc)
    activos = db.scalars(
        select(Prestamo).where(Prestamo.persona_id == p.id, Prestamo.devuelto_at.is_(None))
    ).all()
    alertas = []
    if p.estado == EstadoPersona.suspendido:
        alertas.append("⚠ Cuenta suspendida.")
    atrasados = [pr for pr in activos if pr.vence_at and pr.vence_at < ahora]
    if atrasados:
        alertas.append(f"⚠ {len(atrasados)} material(es) atrasado(s).")
    return {
        "persona_id": p.id, "dni": p.dni, "nombre": p.nombre, "apellido": p.apellido,
        "rol": p.rol.value, "estado": p.estado.value, "alertas": alertas,
        "prestamos_activos": [
            {"prestamo_id": pr.id, "material": _describir(db, db.get(Material, pr.material_id)),
             "vence_at": pr.vence_at.isoformat() if pr.vence_at else None,
             "atrasado": bool(pr.vence_at and pr.vence_at < ahora)}
            for pr in activos
        ],
    }


@router.get("/material")
def resolver_material(codigo: str, para: str = "prestamo", db: Session = Depends(get_db), _: Persona = Staff) -> dict:
    """Resuelve un código escaneado: código interno (un material) o ISBN (elegir copia).

    `para='prestamo'` busca copias disponibles; `para='devolucion'`, las prestadas.
    """
    objetivo = EstadoMaterial.prestado if para == "devolucion" else EstadoMaterial.disponible
    codigo = codigo.strip()
    m = db.scalar(select(Material).where(Material.codigo_interno == codigo))
    if m:
        # Libro sin ISBN (QR propio): adjuntar la tapa para verificar visualmente el escaneo.
        cover = db.get(Titulo, m.titulo_id).cover_url if m.titulo_id else None
        return {"kind": "material", "material": {
            "id": m.id, "descripcion": _describir(db, m), "estado": m.estado.value,
            "cover_url": cover, "seleccionable": m.estado == objetivo}}
    t = db.scalar(select(Titulo).where(Titulo.isbn == normalizar_isbn(codigo)))
    if t:
        copias = db.scalars(
            select(Material).where(Material.titulo_id == t.id).order_by(Material.numero_copia)
        ).all()
        sel = [c for c in copias if c.estado == objetivo]
        return {"kind": "libro", "titulo": t.titulo, "total": len(copias), "para": para,
                "cover_url": t.cover_url,
                "copias": [{"id": c.id, "numero_copia": c.numero_copia} for c in sel]}
    return {"kind": "no", "mensaje": "No se encontró ningún material con ese código."}


@router.post("/prestamo")
def crear_prestamo(payload: PrestamoIn, db: Session = Depends(get_db), encargado: Persona = Staff) -> dict:
    """Registra el préstamo de uno o más materiales a un usuario.

    Recibe el `persona_id` resuelto al escanear (no el código rotativo, que ya
    expiró mientras se cargaban los materiales en el mostrador).
    """
    alumno = db.get(Persona, payload.persona_id)
    if alumno is None:
        raise HTTPException(404, "Usuario no encontrado.")
    if alumno.estado == EstadoPersona.suspendido:
        raise HTTPException(409, "El usuario está suspendido.")
    if not payload.material_ids:
        raise HTTPException(422, "No hay materiales para prestar.")

    creados, errores = [], []
    for mid in payload.material_ids:
        m = db.get(Material, mid)
        if m is None:
            errores.append(f"material {mid} inexistente")
            continue
        if m.estado != EstadoMaterial.disponible:
            errores.append(f"{_describir(db, m)} no está disponible ({m.estado.value})")
            continue
        vence = _vencimiento(m.tipo, alumno.rol, payload.dias)
        db.add(Prestamo(material_id=m.id, persona_id=alumno.id, vence_at=vence,
                        encargado_prestamo_id=encargado.id))
        m.estado = EstadoMaterial.prestado
        creados.append({"material": _describir(db, m), "vence_at": vence.isoformat()})

    if errores and not creados:
        db.rollback()
        raise HTTPException(409, "; ".join(errores))
    db.commit()
    quien = alumno.nombre or ("DNI " + alumno.dni)
    return {
        "prestados": creados, "errores": errores,
        "mensaje": f"{len(creados)} material(es) prestado(s) a {quien}."
                   + (f" {len(errores)} con problema." if errores else ""),
    }


@router.post("/devolucion")
def devolver(payload: DevolucionIn, db: Session = Depends(get_db), encargado: Persona = Staff) -> dict:
    """Cierra el préstamo abierto de un material y lo deja disponible.

    Si la condición es 'observacion', registra un incidente vinculado al préstamo.
    """
    m = db.get(Material, payload.material_id)
    if m is None:
        raise HTTPException(404, "Material inexistente.")
    prestamo = db.scalar(
        select(Prestamo).where(Prestamo.material_id == m.id, Prestamo.devuelto_at.is_(None))
    )
    if prestamo is None:
        raise HTTPException(409, f"{_describir(db, m)} no figura como prestado.")

    quien = db.get(Persona, prestamo.persona_id)
    prestamo.devuelto_at = datetime.now(timezone.utc)
    prestamo.condicion_devolucion = (
        CondicionDevolucion.ok if payload.condicion == "ok" else CondicionDevolucion.observacion
    )
    prestamo.encargado_devolucion_id = encargado.id
    if payload.notas:
        prestamo.notas = payload.notas
    m.estado = EstadoMaterial.disponible

    incidente_creado = False
    if payload.condicion == "observacion":
        db.add(Incidente(
            material_id=m.id, prestamo_id=prestamo.id,
            descripcion=payload.notas or "Observación en la devolución",
            severidad=Severidad.media, creado_por_id=encargado.id,
        ))
        incidente_creado = True

    db.commit()
    return {
        "material": _describir(db, m),
        "devuelto_por": (quien.nombre or ("DNI " + quien.dni)) if quien else "?",
        "condicion": payload.condicion,
        "incidente_creado": incidente_creado,
        "mensaje": f"Devuelto: {_describir(db, m)}." + (" Se registró un incidente." if incidente_creado else ""),
    }
