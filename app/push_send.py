"""Envío de notificaciones Web Push (avisos de vencimiento al celular).

Usa pywebpush con las claves VAPID del .env. El payload va cifrado (lo hace pywebpush);
el service worker lo recibe en el evento `push` y muestra la notificación.
"""
import json

from pywebpush import WebPushException, webpush

from .config import settings


def push_configurado() -> bool:
    return bool(settings.vapid_public_key and settings.vapid_private_key_file)


def enviar_push(endpoint: str, p256dh: str, auth: str,
                titulo: str, cuerpo: str, url: str = "/credencial.html") -> bool:
    """Envía un push a una suscripción. Devuelve:
      - True  si se envió OK.
      - False si la suscripción está MUERTA (404/410) → el llamador la borra.
    Lanza WebPushException para otros errores (red, 5xx, etc.).
    """
    try:
        webpush(
            subscription_info={"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}},
            data=json.dumps({"title": titulo, "body": cuerpo, "url": url}),
            vapid_private_key=settings.vapid_private_key_file,
            vapid_claims={"sub": settings.vapid_subject},
            ttl=86400,  # el push service guarda el aviso hasta 24 h si el celu está offline
        )
        return True
    except WebPushException as e:
        code = getattr(e.response, "status_code", None)
        if code in (404, 410):
            return False
        raise
