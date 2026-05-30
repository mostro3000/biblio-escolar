"""Importa un padrón a la tabla `persona`, tomando SOLO el DNI.

De cada línea toma el primer token (el DNI). El nombre y el apellido NO se parsean:
se completan en el onboarding desde el escaneo del DNI. Idempotente: salta los DNIs
que ya existen, así se puede re-correr sin duplicar.

Por defecto importa el padrón de alumnos (`data/lista.txt` como `rol=alumno`). Para
otro padrón (p.ej. docentes) pasar `--file` y `--rol`:

    runuser -u biblio -- /opt/biblio/venv/bin/python /opt/biblio/scripts/import_padron.py
    runuser -u biblio -- /opt/biblio/venv/bin/python /opt/biblio/scripts/import_padron.py \\
        --file /opt/biblio/data/docentes.txt --rol docente

OJO: si un DNI ya existe (p.ej. cargado como alumno) NO se le cambia el rol — se
salta. Si hubiera solapamiento real alumno/docente, ajustarlo a mano.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, "/opt/biblio")

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import EstadoPersona, Persona, Rol  # noqa: E402

LISTA_DEFAULT = "/opt/biblio/data/lista.txt"


def extraer_dni(linea: str) -> str | None:
    """El DNI es el primer token; el resto (nombre crudo) se ignora a propósito."""
    linea = linea.strip()
    if not linea:
        return None
    token = linea.split()[0]
    return token if token.isdigit() else None


def main() -> None:
    ap = argparse.ArgumentParser(description="Importa un padrón (solo DNI) a persona.")
    ap.add_argument("--file", default=LISTA_DEFAULT, help="archivo del padrón (default: lista.txt)")
    ap.add_argument("--rol", default="alumno", choices=[r.value for r in Rol],
                    help="rol a asignar a los DNIs nuevos (default: alumno)")
    args = ap.parse_args()

    if SessionLocal is None:
        sys.exit("DATABASE_URL no configurada (revisar /opt/biblio/.env)")

    ruta = Path(args.file)
    if not ruta.exists():
        sys.exit(f"No existe el archivo: {ruta}")
    rol = Rol(args.rol)

    total = invalidas = 0
    dnis: set[str] = set()
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if not linea.strip():
            continue
        total += 1
        dni = extraer_dni(linea)
        if dni is None:
            invalidas += 1
            print(f"  ⚠ línea sin DNI válido: {linea!r}")
            continue
        dnis.add(dni)

    insertados = saltados = 0
    with SessionLocal() as db:
        existentes = set(db.scalars(select(Persona.dni)).all())
        for dni in sorted(dnis):
            if dni in existentes:
                saltados += 1
                continue
            db.add(Persona(dni=dni, rol=rol, estado=EstadoPersona.pendiente))
            insertados += 1
        db.commit()

    print(
        f"\narchivo:              {ruta}"
        f"\nrol asignado:         {rol.value}"
        f"\nlíneas leídas:        {total}"
        f"\nDNIs únicos válidos:  {len(dnis)}"
        f"\nlíneas inválidas:     {invalidas}"
        f"\ninsertados:           {insertados}"
        f"\nya existían (saltados): {saltados}"
    )


if __name__ == "__main__":
    main()
