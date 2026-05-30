"""Web Push: clave pública VAPID + suscribir/baja + prueba. Cualquier sesión válida."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Persona, PushSubscription
from ..push_send import enviar_push, push_configurado
from ..security import usuario_actual

router = APIRouter(prefix="/api/push", tags=["push"])

Yo = Depends(usuario_actual)


@router.get("/clave")
def clave(_: Persona = Yo) -> dict:
    """Clave pública VAPID para que el navegador se suscriba (no es secreta)."""
    return {"clave_publica": settings.vapid_public_key, "habilitado": push_configurado()}


class SuscribirIn(BaseModel):
    endpoint: str
    p256dh: str
    auth: str
    user_agent: str | None = None


@router.post("/suscribir")
def suscribir(payload: SuscribirIn, db: Session = Depends(get_db), persona: Persona = Yo) -> dict:
    """Guarda (o reasigna) la suscripción del dispositivo a esta persona."""
    sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint))
    if sub is None:
        sub = PushSubscription(endpoint=payload.endpoint)
        db.add(sub)
    sub.persona_id = persona.id
    sub.p256dh = payload.p256dh
    sub.auth = payload.auth
    sub.user_agent = (payload.user_agent or "")[:300] or None
    db.commit()
    return {"ok": True}


class BajaIn(BaseModel):
    endpoint: str


@router.post("/baja")
def baja(payload: BajaIn, db: Session = Depends(get_db), persona: Persona = Yo) -> dict:
    """Borra la suscripción de este dispositivo (el usuario apaga los avisos)."""
    db.query(PushSubscription).filter(
        PushSubscription.endpoint == payload.endpoint,
        PushSubscription.persona_id == persona.id,
    ).delete()
    db.commit()
    return {"ok": True}


@router.post("/probar")
async def probar(db: Session = Depends(get_db), persona: Persona = Yo) -> dict:
    """Envía un push de prueba a los dispositivos del usuario (para verificar que llega)."""
    if not push_configurado():
        raise HTTPException(503, "Push no configurado en el servidor.")
    subs = db.scalars(select(PushSubscription).where(PushSubscription.persona_id == persona.id)).all()
    if not subs:
        raise HTTPException(404, "No tenés ningún dispositivo con avisos activados.")
    enviados, muertas = 0, []
    for s in subs:
        try:
            vivo = await run_in_threadpool(
                enviar_push, s.endpoint, s.p256dh, s.auth,
                "📚 Biblioteca", "¡Listo! Los avisos están activados.", "/credencial.html")
            if vivo:
                enviados += 1
            else:
                muertas.append(s.id)
        except Exception:
            pass
    if muertas:
        db.query(PushSubscription).filter(PushSubscription.id.in_(muertas)).delete(synchronize_session=False)
        db.commit()
    return {"enviados": enviados, "mensaje": f"Aviso de prueba enviado a {enviados} dispositivo(s)."}
