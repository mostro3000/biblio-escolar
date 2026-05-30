"""Rate limiting simple por IP, como dependency de FastAPI.

Backstop anti fuerza-bruta (login) y anti-enumeración/abuso (onboarding). Es
**en memoria y por worker**: con 2 workers de uvicorn el límite efectivo es ~2x.
No es un control exacto ni distribuido — para eso haría falta un store compartido
(Redis/DB), innecesario a esta escala. Sobrevive lo justo: se reinicia al reiniciar
el servicio (aceptable para un backstop).

El IP se toma de `X-Forwarded-For` (lo agrega Apache/mod_proxy_http; el **último**
valor es el peer real que vio Apache, a prueba del XFF que pueda mandar el cliente).
"""
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_hits: dict[str, deque] = defaultdict(deque)
_MAX_KEYS = 5000          # backstop de memoria: si crece de más, barrer
_SWEEP_MAX_AGE = 3600     # al barrer, descartar IPs sin hits en la última hora


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[-1].strip()
    return request.client.host if request.client else "desconocido"


def _sweep(ahora: float) -> None:
    for k in list(_hits.keys()):
        dq = _hits[k]
        while dq and dq[0] <= ahora - _SWEEP_MAX_AGE:
            dq.popleft()
        if not dq:
            del _hits[k]


def rate_limit(nombre: str, max_hits: int, ventana: int):
    """Devuelve un dependency que limita a `max_hits` requests por `ventana` seg por IP."""
    def dep(request: Request) -> None:
        ahora = time.monotonic()
        if len(_hits) > _MAX_KEYS:
            _sweep(ahora)
        key = f"{nombre}:{_client_ip(request)}"
        dq = _hits[key]
        while dq and dq[0] <= ahora - ventana:
            dq.popleft()
        if len(dq) >= max_hits:
            retry = max(1, int(ventana - (ahora - dq[0])) + 1)
            raise HTTPException(
                429, "Demasiados intentos. Esperá un momento e intentá de nuevo.",
                headers={"Retry-After": str(retry)},
            )
        dq.append(ahora)
    return dep
