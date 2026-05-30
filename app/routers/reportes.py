"""Reportes de uso para el rol directivo (y admin). Solo lectura/auditoría.

Agrega datos de préstamos, devoluciones, incidentes (roturas) e inventario para
el panel de gráficos `/reportes.html`.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
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
    Titulo,
)
from ..security import requiere_rol

router = APIRouter(prefix="/api/reportes", tags=["reportes"])

# Directivo audita; admin ve todo. (El encargado no necesita reportes.)
Audit = Depends(requiere_rol(Rol.directivo, Rol.admin))


def _descr(db: Session, m: Material | None) -> str:
    if m is None:
        return "?"
    if m.titulo_id:
        t = db.get(Titulo, m.titulo_id)
        base = t.titulo if t else "libro"
        return f"{base} (copia {m.numero_copia})" if m.numero_copia else base
    return f"{TIPO_LABEL.get(m.tipo.value, m.tipo.value)} {m.codigo_interno or ''}".strip()


@router.get("/resumen")
def resumen(db: Session = Depends(get_db), _: Persona = Audit) -> dict:
    """Todas las métricas del panel directivo en una sola llamada."""
    ahora = datetime.now(timezone.utc)
    n = lambda q: db.scalar(q) or 0

    total = n(select(func.count()).select_from(Prestamo))
    activos = n(select(func.count()).select_from(Prestamo).where(Prestamo.devuelto_at.is_(None)))
    atrasados = n(select(func.count()).select_from(Prestamo).where(
        Prestamo.devuelto_at.is_(None), Prestamo.vence_at < ahora))
    dev_ok = n(select(func.count()).select_from(Prestamo).where(
        Prestamo.condicion_devolucion == CondicionDevolucion.ok))
    dev_obs = n(select(func.count()).select_from(Prestamo).where(
        Prestamo.condicion_devolucion == CondicionDevolucion.observacion))

    inc_total = n(select(func.count()).select_from(Incidente))
    inc_abiertos = n(select(func.count()).select_from(Incidente).where(Incidente.resuelto_at.is_(None)))
    inc_sev = {s.value: 0 for s in Severidad}
    for sev, cnt in db.execute(select(Incidente.severidad, func.count()).group_by(Incidente.severidad)).all():
        inc_sev[sev.value] = cnt

    # Top 10 ejemplares más prestados.
    top = [{"material": _descr(db, db.get(Material, mid)), "prestamos": cnt}
           for mid, cnt in db.execute(
               select(Prestamo.material_id, func.count().label("c"))
               .group_by(Prestamo.material_id).order_by(func.count().desc()).limit(10)).all()]

    # Préstamos por tipo de material (join prestamo→material).
    por_tipo = [{"tipo": tipo.value, "tipo_label": TIPO_LABEL.get(tipo.value, tipo.value), "prestamos": cnt}
                for tipo, cnt in db.execute(
                    select(Material.tipo, func.count(Prestamo.id))
                    .join(Prestamo, Prestamo.material_id == Material.id)
                    .group_by(Material.tipo).order_by(func.count(Prestamo.id).desc())).all()]

    # Préstamos por mes (últimos 12 meses), eje temporal para la tendencia.
    mes = func.to_char(func.date_trunc("month", Prestamo.prestado_at), "YYYY-MM")
    por_mes = [{"mes": m, "prestamos": cnt}
               for m, cnt in db.execute(select(mes, func.count()).group_by(mes).order_by(mes)).all()][-12:]

    # Inventario por estado.
    inv = {e.value: 0 for e in EstadoMaterial}
    for est, cnt in db.execute(select(Material.estado, func.count()).group_by(Material.estado)).all():
        inv[est.value] = cnt

    return {
        "prestamos": {"total": total, "activos": activos, "atrasados": atrasados,
                      "devueltos": total - activos},
        "devoluciones": {"ok": dev_ok, "observacion": dev_obs},
        "incidentes": {"total": inc_total, "abiertos": inc_abiertos, "por_severidad": inc_sev},
        "top_materiales": top,
        "por_tipo": por_tipo,
        "por_mes": por_mes,
        "inventario": {"total": sum(inv.values()), **inv},
        "personas_activas": n(select(func.count()).select_from(Persona).where(
            Persona.estado == EstadoPersona.activo)),
    }
