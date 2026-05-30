"""QR rotativo (TOTP) de la credencial del alumno.

El `persona.qr_token` deja de mostrarse como QR fijo y pasa a ser el **secreto**.
La credencial muestra un código que cambia cada `settings.qr_step_seconds`:

    código = HMAC-SHA256(qr_token, floor(unix / STEP))  → hex, primeros 12 chars

Se calcula igual en el celular (Web Crypto, ver `credencial.html`) y en el server.
Como el secreto no viaja en el QR, una captura de pantalla caduca en ~1-2 ventanas
y no se puede compartir. El server valida contra la ventana actual ±1 para tolerar
el desfase de reloj entre el celular del alumno y el del mostrador.

Resolver un código = iterar las personas con credencial (≈530) por 3 ventanas:
~1600 HMAC, instantáneo. No hace falta que el QR identifique a la persona, lo que
además es bueno para la privacidad (el código no revela de quién es).
"""
import hashlib
import hmac
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Persona

CODE_HEX_LEN = 12  # 48 bits: suficiente, colisión entre 530 personas ~ nula


def _codigo(secret: str, contador: int) -> str:
    """HMAC-SHA256(secret, contador de 8 bytes big-endian) → primeros 12 hex."""
    msg = contador.to_bytes(8, "big")
    dig = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    return dig[:CODE_HEX_LEN]


def codigo_actual(secret: str, ahora: float | None = None) -> str:
    """Código de la ventana actual (para tests / debug)."""
    step = settings.qr_step_seconds
    contador = int((time.time() if ahora is None else ahora) // step)
    return _codigo(secret, contador)


def resolver_persona(db: Session, codigo: str) -> Persona | None:
    """Dado un código escaneado, devuelve la persona dueña (o None).

    Prueba la ventana actual y las adyacentes (±1) contra cada persona con
    credencial. Usa `compare_digest` para no filtrar por timing.
    """
    codigo = (codigo or "").strip().lower()
    if len(codigo) != CODE_HEX_LEN:
        return None
    step = settings.qr_step_seconds
    actual = int(time.time() // step)
    ventanas = (actual - 1, actual, actual + 1)
    personas = db.scalars(select(Persona).where(Persona.qr_token.is_not(None))).all()
    for p in personas:
        for w in ventanas:
            if hmac.compare_digest(_codigo(p.qr_token, w), codigo):
                return p
    return None
