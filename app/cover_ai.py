"""Lectura de la tapa de un libro con la API de Claude (visión).

Fallback para cuando el ISBN no aparece en ningún catálogo online: se manda SOLO la
foto de la tapa (sin datos personales) y Claude devuelve titulo/autor/editorial/anio
como salida estructurada (forced tool use). Solo stdlib (urllib), igual que isbn.py;
el endpoint que la usa la corre en threadpool para no trabar el event loop.

Config por entorno (en /opt/biblio/.env, requiere reiniciar el servicio):
- ANTHROPIC_API_KEY : clave de la API de Claude (obligatoria; si falta → fuente='no_config').
- COVER_AI_MODEL    : modelo a usar (def. claude-haiku-4-5: barato y suficiente para OCR de tapa).
"""
import base64
import json
import os
import urllib.error
import urllib.request

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
MODEL = os.getenv("COVER_AI_MODEL", "").strip() or "claude-haiku-4-5"
TIMEOUT = 30  # segundos
_URL = "https://api.anthropic.com/v1/messages"

# Forzamos a Claude a llamar a esta herramienta → la respuesta trae los campos ya parseados.
_TOOL = {
    "name": "registrar_libro",
    "description": "Registra los datos del libro leídos de la foto de su tapa o contratapa.",
    "input_schema": {
        "type": "object",
        "properties": {
            "titulo": {"type": ["string", "null"], "description": "Título principal del libro"},
            "autor": {"type": ["string", "null"], "description": "Autor o autores; null si no se ve"},
            "editorial": {"type": ["string", "null"], "description": "Editorial; null si no se ve"},
            "anio": {"type": ["integer", "null"], "description": "Año de edición si aparece; si no, null"},
        },
        "required": ["titulo"],
    },
}

_PROMPT = (
    "Esta es la foto de la tapa de un libro. Identificá el título, el autor, la editorial y el año "
    "de edición si aparecen. Si algún dato no se ve con claridad, dejalo en null — no inventes. "
    "Devolvé los datos llamando a la herramienta registrar_libro."
)

_VACIO = {"titulo": None, "autor": None, "editorial": None, "anio": None}

# A veces el modelo escribe un marcador en vez de null; lo tratamos como "no hay dato".
_PLACEHOLDERS = {"", "unknown", "desconocido", "n/a", "na", "no visible", "no se ve",
                 "ninguno", "sin titulo", "sin título", "sin datos"}


def _limpio(v):
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s or s.lower() in _PLACEHOLDERS or (s.startswith("<") and s.endswith(">")):
        return None
    return s


def leer_tapa(image_bytes: bytes, media_type: str = "image/jpeg") -> dict:
    """Lee la tapa con Claude. Devuelve dict con:
    {encontrado: bool, fuente: 'ia'|'no_config'|'error', titulo, autor, editorial, anio, [detalle]}.
    """
    if not ANTHROPIC_KEY:
        return {"encontrado": False, "fuente": "no_config", **_VACIO}

    b64 = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "model": MODEL,
        "max_tokens": 512,
        "tools": [_TOOL],
        "tool_choice": {"type": "tool", "name": "registrar_libro"},
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": _PROMPT},
            ],
        }],
    }
    req = urllib.request.Request(
        _URL, data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        cuerpo = e.read().decode("utf-8", "ignore")[:300]
        return {"encontrado": False, "fuente": "error", "detalle": f"HTTP {e.code}: {cuerpo}", **_VACIO}
    except Exception as e:  # red, timeout, json
        return {"encontrado": False, "fuente": "error", "detalle": str(e)[:200], **_VACIO}

    # Extraer el bloque tool_use forzado.
    campos = None
    for block in data.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "registrar_libro":
            campos = block.get("input") or {}
            break
    if campos is None:
        return {"encontrado": False, "fuente": "error", "detalle": "respuesta sin tool_use", **_VACIO}

    titulo = _limpio(campos.get("titulo"))
    anio = campos.get("anio")
    return {
        "encontrado": bool(titulo),
        "fuente": "ia",
        "titulo": titulo,
        "autor": _limpio(campos.get("autor")),
        "editorial": _limpio(campos.get("editorial")),
        "anio": anio if isinstance(anio, int) else None,
    }
