#!/usr/bin/env python3
"""Avisos de vencimiento por Web Push (corre 1 vez al día desde un timer systemd).

Por cada usuario con préstamos abiertos que vencen HOY o que están ATRASADOS, manda un
push a sus dispositivos. Borra las suscripciones muertas (404/410). No manda mail.

Uso: /opt/biblio/venv/bin/python scripts/avisos_vencimiento.py
"""
import sys
from datetime import datetime

# Permite correrlo desde /opt/biblio (igual que el resto de scripts).
sys.path.insert(0, "/opt/biblio")

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    TIPO_LABEL,
    Material,
    Persona,
    Prestamo,
    PushSubscription,
    Titulo,
)
from app.push_send import enviar_push, push_configurado  # noqa: E402
from app.security import ARG_TZ  # noqa: E402


def _describir(db, m: Material) -> str:
    if m is None:
        return "un material"
    if m.titulo_id:
        t = db.get(Titulo, m.titulo_id)
        base = t.titulo if t else "libro"
        return f"{base} (copia {m.numero_copia})" if m.numero_copia else base
    return f"{TIPO_LABEL.get(m.tipo.value, m.tipo.value)} {m.codigo_interno or ''}".strip()


def _mensaje(hoy: list[str], atrasados: list[str]) -> str:
    nh, na = len(hoy), len(atrasados)
    if na and nh:
        return f"Tenés {na} material(es) atrasado(s) y {nh} que vence(n) hoy. Pasá por la biblioteca."
    if nh == 1:
        return f"Hoy vence: «{hoy[0]}». No te olvides de devolverlo."
    if nh:
        return f"Hoy vencen {nh} de tus préstamos. No te olvides de devolverlos."
    if na == 1:
        return f"Tenés atrasado: «{atrasados[0]}». Devolvelo apenas puedas."
    return f"Tenés {na} materiales atrasados. Devolvelos apenas puedas."


def main() -> int:
    if not push_configurado():
        print("Push NO configurado (faltan claves VAPID). Nada para hacer.")
        return 0

    db = SessionLocal()
    try:
        hoy_arg = datetime.now(ARG_TZ).date()

        # Préstamos abiertos (sin devolver) con vencimiento <= hoy ARG.
        abiertos = db.scalars(
            select(Prestamo).where(Prestamo.devuelto_at.is_(None))
        ).all()

        # por persona: {persona_id: {"hoy": [...], "atrasados": [...]}}
        por_persona: dict[int, dict[str, list[str]]] = {}
        for p in abiertos:
            if not p.vence_at:
                continue
            venc = p.vence_at.astimezone(ARG_TZ).date()
            if venc > hoy_arg:
                continue  # todavía no vence
            desc = _describir(db, db.get(Material, p.material_id))
            grupo = por_persona.setdefault(p.persona_id, {"hoy": [], "atrasados": []})
            (grupo["hoy"] if venc == hoy_arg else grupo["atrasados"]).append(desc)

        if not por_persona:
            print(f"[{hoy_arg}] Sin vencimientos hoy ni atrasados. Nada para avisar.")
            return 0

        total_personas = total_push = total_muertas = 0
        for persona_id, grupo in por_persona.items():
            subs = db.scalars(
                select(PushSubscription).where(PushSubscription.persona_id == persona_id)
            ).all()
            if not subs:
                continue  # esa persona no activó avisos en ningún dispositivo
            cuerpo = _mensaje(grupo["hoy"], grupo["atrasados"])
            enviado_a_alguien = False
            for s in subs:
                try:
                    vivo = enviar_push(s.endpoint, s.p256dh, s.auth, "📚 Biblioteca", cuerpo)
                except Exception as e:  # red/5xx: se reintenta mañana
                    print(f"  persona {persona_id} sub {s.id}: error {e!r}")
                    continue
                if vivo:
                    total_push += 1
                    enviado_a_alguien = True
                else:
                    db.delete(s)
                    total_muertas += 1
            if enviado_a_alguien:
                total_personas += 1
        db.commit()
        print(f"[{hoy_arg}] Avisos: {total_personas} persona(s), {total_push} push enviado(s), "
              f"{total_muertas} suscripción(es) muerta(s) borrada(s).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
