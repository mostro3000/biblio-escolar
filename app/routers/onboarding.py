"""Onboarding de personas (alta de cuenta verificada).

Paso 1: verificar el DNI contra el padrón y el estado de la cuenta.
Los pasos siguientes (escaneo de DNI -> nombre+embedding, selfie+liveness,
comparación) se irán agregando acá.
"""
import logging
import math

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..dni import parse_pdf417
from ..ratelimit import rate_limit
from ..security import COOKIE, crear_sesion, fin_de_anio, nuevo_qr_token
from ..models import EstadoPersona, Persona
from ..schemas import (
    BiometriaIn,
    BiometriaOut,
    EscanearDniIn,
    EscanearDniOut,
    ReloginIn,
    VerificarDniIn,
    VerificarDniOut,
)

# Límite por IP compartido por las 3 rutas de onboarding (anti-enumeración/abuso).
_onb_rl = Depends(rate_limit("onboarding", settings.onboarding_rate_max, settings.onboarding_rate_window))

# Umbrales de distancia euclidiana entre descriptores de face-api.js.
# (misma persona suele dar < 0.5; distintas, > 0.6). Ajustables con datos reales.
UMBRAL_OK = 0.575   # <= -> aprobación automática (matches reales DNI-vs-selfie dieron 0.48 y 0.57)
UMBRAL_GRIS = 0.6   # <= -> zona gris (revisión manual); > -> rechazo

# uvicorn.error ya está conectado a la salida (journald); un logger propio no emitiría INFO.
log = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


@router.post("/verificar-dni", response_model=VerificarDniOut)
def verificar_dni(payload: VerificarDniIn, db: Session = Depends(get_db), _rl: None = _onb_rl) -> VerificarDniOut:
    """Decide qué puede hacer la PWA según el DNI ingresado.

    Nota: el padrón solo tiene DNIs (sin nombre), así que acá no saludamos por
    nombre — eso recién se sabe tras escanear el DNI.
    """
    persona = db.scalar(select(Persona).where(Persona.dni == payload.dni))

    if persona is None:
        return VerificarDniOut(
            dni=payload.dni,
            existe=False,
            ya_registrado=False,
            suspendido=False,
            puede_registrarse=False,
            mensaje="Tu DNI no figura en el padrón. Pedí en la biblioteca que te agreguen.",
        )

    if persona.estado == EstadoPersona.suspendido:
        return VerificarDniOut(
            dni=payload.dni,
            existe=True,
            ya_registrado=False,
            suspendido=True,
            puede_registrarse=False,
            mensaje="Tu cuenta está suspendida. Acercate a la biblioteca.",
        )

    if persona.estado == EstadoPersona.activo:
        return VerificarDniOut(
            dni=payload.dni,
            existe=True,
            ya_registrado=True,
            suspendido=False,
            puede_registrarse=False,
            mensaje="Ya estás registrado. Iniciá sesión.",
        )

    # estado pendiente: en el padrón pero sin cuenta -> puede arrancar el onboarding
    return VerificarDniOut(
        dni=payload.dni,
        existe=True,
        ya_registrado=False,
        suspendido=False,
        puede_registrarse=True,
        mensaje="Te encontramos en el padrón. Vamos a verificar tu identidad.",
    )


@router.post("/escanear-dni", response_model=EscanearDniOut)
def escanear_dni(payload: EscanearDniIn, db: Session = Depends(get_db), _rl: None = _onb_rl) -> EscanearDniOut:
    """Paso único: del PDF417 del dorso sacamos DNI + nombre, validamos contra el
    padrón y, si está pendiente, guardamos los datos oficiales. Sin tipear el DNI.
    """
    datos = parse_pdf417(payload.pdf417)
    if datos is None:
        # DEBUG temporal: capturar el formato del QR del DNI nuevo. Quitar tras calibrar.
        log.info("escanear-dni sin parsear (¿QR nuevo?). raw=%r", payload.pdf417[:300])
        raise HTTPException(
            422,
            "No pudimos leer el DNI. Reintentá enfocando bien el código del dorso o frente.",
        )

    dni = datos["dni"]
    persona = db.scalar(select(Persona).where(Persona.dni == dni))

    if persona is None:
        return EscanearDniOut(
            dni=dni, existe=False, ya_registrado=False, suspendido=False,
            puede_continuar=False, nombre=None, apellido=None,
            mensaje="Tu DNI no figura en el padrón. Pedí en la biblioteca que te agreguen.",
        )
    if persona.estado == EstadoPersona.suspendido:
        return EscanearDniOut(
            dni=dni, existe=True, ya_registrado=False, suspendido=True,
            puede_continuar=False, nombre=None, apellido=None,
            mensaje="Tu cuenta está suspendida. Acercate a la biblioteca.",
        )
    if persona.estado == EstadoPersona.activo:
        tiene_bio = persona.foto_embedding is not None
        return EscanearDniOut(
            dni=dni, existe=True, ya_registrado=True, suspendido=False,
            puede_continuar=False, puede_relogin=tiene_bio, nombre=None, apellido=None,
            mensaje="¡Hola de nuevo! Confirmá con una selfie para entrar." if tiene_bio
                    else "Ya estás registrado. Iniciá sesión.",
        )

    # pendiente: guardamos nombre/apellido oficiales y habilitamos la selfie
    persona.nombre = datos["nombre"]
    persona.apellido = datos["apellido"]
    db.commit()
    return EscanearDniOut(
        dni=dni, existe=True, ya_registrado=False, suspendido=False,
        puede_continuar=True, nombre=datos["nombre"], apellido=datos["apellido"],
        mensaje=f"¡Hola {datos['nombre'].title()}! Ahora una selfie para confirmar que sos vos.",
    )


@router.post("/biometria", response_model=BiometriaOut)
def biometria(payload: BiometriaIn, response: Response, db: Session = Depends(get_db), _rl: None = _onb_rl) -> BiometriaOut:
    """Paso 2: compara el rostro del DNI con la selfie y decide.

    Los embeddings se calculan en el cliente (face-api.js). Acá comparamos por
    distancia euclidiana. Se persiste SOLO el embedding de la selfie (nunca las
    imágenes), como referencia para el uso diario.
    """
    persona = db.scalar(select(Persona).where(Persona.dni == payload.dni))
    if persona is None:
        raise HTTPException(404, "El DNI no figura en el padrón.")
    if persona.estado == EstadoPersona.suspendido:
        raise HTTPException(409, "La cuenta está suspendida.")
    if persona.estado == EstadoPersona.activo:
        raise HTTPException(409, "Ya estás registrado. Iniciá sesión.")

    dist = math.sqrt(
        sum((a - b) ** 2 for a, b in zip(payload.embedding_dni, payload.embedding_selfie))
    )
    log.info("biometria dni=%s distancia=%.4f (umbrales ok<=%.2f gris<=%.2f)",
             payload.dni, dist, UMBRAL_OK, UMBRAL_GRIS)

    if dist <= UMBRAL_OK:
        persona.foto_embedding = payload.embedding_selfie
        persona.estado = EstadoPersona.activo
        if not persona.qr_token:
            persona.qr_token = nuevo_qr_token()
        db.commit()
        # El celu del alumno queda logueado hasta fin del año escolar (sin clave).
        # Cookie con fecha absoluta (Expires) en vez de contador: vence el 31/dic.
        exp = fin_de_anio()
        token = crear_sesion(db, persona, expira_at=exp)
        response.set_cookie(
            COOKIE, token, expires=exp,
            httponly=True, secure=True, samesite="strict", path="/",
        )
        return BiometriaOut(
            aprobado=True, resultado="activo", distancia=round(dist, 4),
            mensaje="¡Identidad verificada! Ya estás registrado.",
        )

    if dist <= UMBRAL_GRIS:
        # Zona gris: guardamos el embedding y queda pendiente de revisión manual.
        persona.foto_embedding = payload.embedding_selfie
        db.commit()
        return BiometriaOut(
            aprobado=False, resultado="revision", distancia=round(dist, 4),
            mensaje="Tu registro quedó en revisión. La biblioteca lo va a aprobar.",
        )

    return BiometriaOut(
        aprobado=False, resultado="rechazado", distancia=round(dist, 4),
        mensaje="Las caras no coinciden lo suficiente. Reintentá la selfie con buena luz.",
    )


@router.post("/relogin", response_model=BiometriaOut)
def relogin(payload: ReloginIn, response: Response, db: Session = Depends(get_db),
            _rl: None = _onb_rl) -> BiometriaOut:
    """Re-login de alumno/docente por selfie (sin contraseña): compara la selfie con
    el embedding guardado y, si coincide, abre una sesión nueva. Sirve para celular
    nuevo, cookies borradas, aprobación de zona gris, o el arranque del año escolar.
    """
    persona = db.scalar(select(Persona).where(Persona.dni == payload.dni))
    if persona is None:
        raise HTTPException(404, "El DNI no figura en el padrón.")
    if persona.estado == EstadoPersona.suspendido:
        raise HTTPException(409, "Tu cuenta está suspendida. Acercate a la biblioteca.")
    if persona.estado != EstadoPersona.activo:
        raise HTTPException(409, "Todavía no estás registrado. Registrate primero.")
    if not persona.foto_embedding:
        raise HTTPException(409, "Esta cuenta entra con contraseña (es de personal), no con selfie.")

    dist = math.sqrt(
        sum((a - b) ** 2 for a, b in zip(payload.embedding_selfie, persona.foto_embedding))
    )
    log.info("relogin dni=%s distancia=%.4f (umbral<=%.2f)", payload.dni, dist, UMBRAL_OK)

    if dist <= UMBRAL_OK:
        if not persona.qr_token:
            persona.qr_token = nuevo_qr_token()
            db.commit()
        exp = fin_de_anio()
        token = crear_sesion(db, persona, expira_at=exp)
        response.set_cookie(
            COOKIE, token, expires=exp,
            httponly=True, secure=True, samesite="strict", path="/",
        )
        return BiometriaOut(aprobado=True, resultado="activo", distancia=round(dist, 4),
                            mensaje="¡Listo, te reconocimos! Entrando…")
    return BiometriaOut(aprobado=False, resultado="rechazado", distancia=round(dist, 4),
                        mensaje="No coincidió con tu registro. Reintentá la selfie con buena luz.")
