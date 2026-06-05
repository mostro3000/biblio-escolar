#!/usr/bin/env python3
"""Reporte de intentos de alta (onboarding) que NO prosperaron.

Lee los logs del servicio (journalctl) y los cruza con la base para mostrar
QUIÉN intentó registrarse por DNI + rostro y no pudo. No modifica nada: es
solo una consulta, pensada para que la bibliotecaria/admin sepa a quién
contactar o aprobar a mano.

Detecta cuatro situaciones:
  1. Quisieron registrarse y NO pudieron  (la selfie no coincidió → siguen sin activar).
  2. Quedaron en revisión (zona gris)      (esperan aprobación manual en el panel).
  3. Ya registrados que no pudieron volver (re-login por cara fallido, p.ej. celu nuevo).
  4. No se pudo LEER el DNI                 (documento ilegible; no se sabe de quién).

Hay que correrlo como ROOT (el journal del servicio solo lo ven root / grupos
adm / systemd-journal):

    sudo /opt/biblio/venv/bin/python /opt/biblio/scripts/intentos_onboarding.py
    sudo /opt/biblio/venv/bin/python /opt/biblio/scripts/intentos_onboarding.py --dias 30
    sudo /opt/biblio/venv/bin/python /opt/biblio/scripts/intentos_onboarding.py --detalle

Limitación: journald ROTA (guarda algunos días). Lo que ya rotó no se puede
recuperar — este reporte ve solo lo que siga en el journal.
"""
import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime

# Permite correrlo apuntando a la app (igual que el resto de scripts).
sys.path.insert(0, "/opt/biblio")

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Persona  # noqa: E402
from app.security import ARG_TZ  # noqa: E402
# Umbrales REALES del onboarding (única fuente de verdad: si se ajustan allá,
# este reporte se ajusta solo).
from app.routers.onboarding import UMBRAL_OK, UMBRAL_GRIS  # noqa: E402

# biometria dni=12345678 distancia=0.7421 (umbrales ok<=0.61 gris<=0.64)
RE_BIO = re.compile(r"biometria dni=(\d+) distancia=([\d.]+)")
RE_RELOGIN = re.compile(r"relogin dni=(\d+) distancia=([\d.]+)")
RE_DNI_ILEGIBLE = re.compile(r"escanear-dni sin parsear")


def clasificar_alta(dist: float) -> str:
    """Resultado de un intento de ALTA por cara, según los umbrales del onboarding."""
    if dist <= UMBRAL_OK:
        return "aprobado"
    if dist <= UMBRAL_GRIS:
        return "revision"
    return "rechazo"


def leer_journal(unidad: str, dias: int | None) -> list[dict]:
    """Devuelve los registros del journal de `unidad` como dicts (-o json)."""
    cmd = ["journalctl", "-u", unidad, "-o", "json", "--no-pager"]
    if dias:
        cmd += ["--since", f"{dias} days ago"]
    try:
        salida = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    except FileNotFoundError:
        sys.exit("ERROR: no se encontró 'journalctl' (¿es un sistema con systemd?).")
    except subprocess.CalledProcessError as e:
        sys.exit(f"ERROR al leer el journal: {e.stderr.strip() or e}")
    regs = []
    for linea in salida.splitlines():
        if linea.strip():
            try:
                regs.append(json.loads(linea))
            except json.JSONDecodeError:
                pass
    return regs


def fecha(reg: dict) -> datetime | None:
    us = reg.get("__REALTIME_TIMESTAMP")
    if us is None:
        return None
    return datetime.fromtimestamp(int(us) / 1_000_000, tz=ARG_TZ)


def mensaje(reg: dict) -> str:
    m = reg.get("MESSAGE", "")
    # journald puede entregar MESSAGE como lista de bytes si no es UTF-8 limpio.
    if isinstance(m, list):
        try:
            return bytes(m).decode("utf-8", "replace")
        except Exception:
            return ""
    return m or ""


def f_corta(dt: datetime | None) -> str:
    return dt.strftime("%d/%m %H:%M") if dt else "—"


def nombre_de(p: Persona | None) -> str:
    if p is None:
        return "(no está en el padrón)"
    ap = (p.apellido or "").strip()
    no = (p.nombre or "").strip()
    return f"{ap}, {no}".strip(", ") or "(sin nombre)"


def main() -> None:
    ap = argparse.ArgumentParser(description="Intentos de onboarding que no prosperaron.")
    ap.add_argument("--unidad", default="biblio", help="servicio systemd (default: biblio)")
    ap.add_argument("--dias", type=int, default=None,
                    help="mirar solo los últimos N días (default: todo el journal)")
    ap.add_argument("--detalle", action="store_true",
                    help="listar cada intento (fecha y distancia), no solo el resumen")
    args = ap.parse_args()

    regs = leer_journal(args.unidad, args.dias)

    # dni -> lista de intentos {tipo, dist, resultado, dt}
    intentos: dict[str, list[dict]] = defaultdict(list)
    ilegibles: list[datetime | None] = []

    for r in regs:
        msg = mensaje(r)
        dt = fecha(r)
        m = RE_BIO.search(msg)
        if m:
            dist = float(m.group(2))
            intentos[m.group(1)].append(
                {"tipo": "alta", "dist": dist, "resultado": clasificar_alta(dist), "dt": dt})
            continue
        m = RE_RELOGIN.search(msg)
        if m:
            dist = float(m.group(2))
            res = "aprobado" if dist <= UMBRAL_OK else "rechazo"
            intentos[m.group(1)].append(
                {"tipo": "relogin", "dist": dist, "resultado": res, "dt": dt})
            continue
        if RE_DNI_ILEGIBLE.search(msg):
            ilegibles.append(dt)

    db = SessionLocal()

    no_pudieron, en_revision, relogin_fallido, entraron = [], [], [], []

    for dni, lista in intentos.items():
        p = db.scalar(select(Persona).where(Persona.dni == dni))
        altas = [i for i in lista if i["tipo"] == "alta"]
        relogins = [i for i in lista if i["tipo"] == "relogin"]
        activo_ahora = p is not None and p.estado.value == "activo"

        fila = {
            "dni": dni, "persona": p, "nombre": nombre_de(p),
            "rol": p.rol.value if p else "?",
            "estado": p.estado.value if p else "?",
            "n_alta": len(altas), "n_relogin": len(relogins),
            "intentos": lista,
            "mejor_alta": min((i["dist"] for i in altas), default=None),
            "ultimo": max((i["dt"] for i in lista if i["dt"]), default=None),
            "alguna_alta_ok": any(i["resultado"] == "aprobado" for i in altas),
            "algun_relogin_ok": any(i["resultado"] == "aprobado" for i in relogins),
        }

        if altas and not fila["alguna_alta_ok"] and not activo_ahora:
            # Intentó darse de alta por cara y hoy sigue sin estar activo.
            mejor = fila["mejor_alta"]
            fila["sub"] = "revision" if mejor is not None and mejor <= UMBRAL_GRIS else "rechazo"
            (en_revision if fila["sub"] == "revision" else no_pudieron).append(fila)
        elif relogins and not fila["algun_relogin_ok"]:
            # Ya está registrado pero no logró volver a entrar por cara.
            relogin_fallido.append(fila)
        elif fila["alguna_alta_ok"]:
            entraron.append(fila)

    no_pudieron.sort(key=lambda f: f["ultimo"] or datetime.min.replace(tzinfo=ARG_TZ), reverse=True)
    en_revision.sort(key=lambda f: f["ultimo"] or datetime.min.replace(tzinfo=ARG_TZ), reverse=True)

    # ---- salida ----
    ventana = f"últimos {args.dias} días" if args.dias else "todo el journal disponible"
    print(f"=== Intentos de alta por cara — servicio '{args.unidad}' ({ventana}) ===")
    if regs:
        prim = next((fecha(r) for r in regs if fecha(r)), None)
        ult = next((fecha(r) for r in reversed(regs) if fecha(r)), None)
        print(f"    logs desde {f_corta(prim)} hasta {f_corta(ult)} "
              f"(journald rota: lo anterior ya no está)\n")

    def imprimir_fila(f, pista):
        marca = {"rechazo": "rechazo (la cara no coincide)",
                 "revision": "quedó en zona gris (revisión)"}.get(f.get("sub"), "")
        mejor = f"{f['mejor_alta']:.3f}" if f["mejor_alta"] is not None else "—"
        print(f"  DNI {f['dni']}  {f['nombre']}  [{f['rol']}]")
        det = f"{f['n_alta']} intento(s) de selfie · mejor coincidencia {mejor}"
        if marca:
            det += f" · {marca}"
        print(f"      {det} · último {f_corta(f['ultimo'])}")
        print(f"      estado actual: {f['estado']} → {pista}")
        if args.detalle:
            for i in sorted((x for x in f["intentos"]), key=lambda x: x["dt"] or datetime.min.replace(tzinfo=ARG_TZ)):
                print(f"         {f_corta(i['dt'])}  {i['tipo']:7} dist={i['dist']:.4f}  {i['resultado']}")

    print("— Quisieron registrarse y NO pudieron (siguen sin activar):")
    if no_pudieron:
        for f in no_pudieron:
            imprimir_fila(f, "activala a mano desde el panel, o pedile una selfie nueva con buena luz "
                             "(sin anteojos, de frente). Si su foto de DNI es muy vieja puede no bajar nunca del umbral.")
    else:
        print("  (ninguno)")

    print("\n— Quedaron en revisión (intentaron y esperan tu OK en el panel):")
    if en_revision:
        for f in en_revision:
            imprimir_fila(f, "aprobala en Admin → 'En revisión' (la selfie quedó guardada).")
    else:
        print("  (ninguno)")

    print("\n— Ya registrados que NO pudieron volver a entrar por cara (re-login):")
    if relogin_fallido:
        for f in relogin_fallido:
            mejor = min((i["dist"] for i in f["intentos"] if i["tipo"] == "relogin"), default=None)
            mejor = f"{mejor:.3f}" if mejor is not None else "—"
            print(f"  DNI {f['dni']}  {f['nombre']}  [{f['rol']}]")
            print(f"      {f['n_relogin']} re-login(s) fallido(s) · mejor {mejor} · último {f_corta(f['ultimo'])}")
            print("      → pedile una selfie con buena luz; si no, re-credencialala desde el panel.")
    else:
        print("  (ninguno)")

    print("\n— No se pudo LEER el DNI (documento ilegible; no se sabe de quién):")
    if ilegibles:
        cuando = ", ".join(f_corta(d) for d in sorted((x for x in ilegibles if x)))
        print(f"  {len(ilegibles)} vez/veces: {cuando}")
        print("      (el código del DNI no se decodificó: gastado, mala luz o modelo nuevo)")
    else:
        print("  (ninguno)")

    multi = [f for f in entraron if f["n_alta"] > 1]
    print(f"\n— Entraron OK por cara: {len(entraron)}"
          + (f" (de los cuales {len(multi)} necesitaron más de un intento)" if entraron else ""))

    print(f"\nResumen: {len(no_pudieron)} no pudieron · {len(en_revision)} en revisión · "
          f"{len(relogin_fallido)} sin poder re-loguear · {len(ilegibles)} DNIs ilegibles.")
    if not (no_pudieron or en_revision or relogin_fallido or ilegibles):
        print("Nada para revisar: ningún intento fallido en la ventana.")

    db.close()


if __name__ == "__main__":
    main()
