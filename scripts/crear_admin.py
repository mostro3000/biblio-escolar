#!/usr/bin/env python3
"""Crea (o promueve) un usuario ADMIN y le pone contraseña.

Sirve para bootstrapear una instalación nueva: cuando todavía no hay ningún admin,
no se puede usar el panel web para crear el primero (huevo y gallina), así que se
crea por consola.

Uso:
    /opt/biblio/venv/bin/python /opt/biblio/scripts/crear_admin.py <DNI> [contraseña]

Si se omite la contraseña, se pide por teclado (no queda en el historial).
"""
import getpass
import sys

sys.path.insert(0, "/opt/biblio")

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import EstadoPersona, Persona, Rol  # noqa: E402
from app.security import hash_password  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("Uso: crear_admin.py <DNI> [contraseña]")
    dni = "".join(c for c in sys.argv[1] if c.isdigit())
    if not (6 <= len(dni) <= 9):
        sys.exit("DNI inválido (6 a 9 dígitos).")
    password = sys.argv[2] if len(sys.argv) > 2 else getpass.getpass("Contraseña del admin: ")
    if len(password) < 6:
        sys.exit("La contraseña debe tener al menos 6 caracteres.")

    with SessionLocal() as db:
        p = db.scalar(select(Persona).where(Persona.dni == dni))
        creado = p is None
        if p is None:
            p = Persona(dni=dni)
            db.add(p)
        p.rol = Rol.admin
        p.estado = EstadoPersona.activo
        p.password_hash = hash_password(password)
        db.commit()
        verbo = "creado" if creado else "actualizado"
        print(f"OK: admin {verbo} (DNI {dni}). Entrá en /login.html con ese DNI y la contraseña.")


if __name__ == "__main__":
    main()
