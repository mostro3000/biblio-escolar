"""Setea (o cambia) la contraseña de un usuario staff (encargado/admin).

Uso:
    /opt/biblio/venv/bin/python /opt/biblio/scripts/set_password.py <DNI> [contraseña]

Si se omite la contraseña, la pide por teclado (no queda en el historial).
La persona ya tiene que existir en el padrón (tabla persona).
"""
import getpass
import sys

sys.path.insert(0, "/opt/biblio")

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Persona  # noqa: E402
from app.security import hash_password  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("Uso: set_password.py <DNI> [contraseña]")
    dni = "".join(c for c in sys.argv[1] if c.isdigit())
    password = sys.argv[2] if len(sys.argv) > 2 else getpass.getpass("Nueva contraseña: ")
    if len(password) < 6:
        sys.exit("La contraseña debe tener al menos 6 caracteres.")

    with SessionLocal() as db:
        persona = db.scalar(select(Persona).where(Persona.dni == dni))
        if persona is None:
            sys.exit(f"No existe persona con DNI {dni} en el padrón.")
        persona.password_hash = hash_password(password)
        db.commit()
        print(f"OK: contraseña actualizada para DNI {dni} (rol {persona.rol.value}).")


if __name__ == "__main__":
    main()
