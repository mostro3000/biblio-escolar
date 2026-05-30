#!/usr/bin/env bash
# Backup de la base PostgreSQL de biblio (pg_dump, formato custom comprimido).
# Corre como usuario `biblio` (disparado por biblio-backup.timer). Rota: conserva
# los últimos RETENTION dumps. La contraseña va por env (PGPASSWORD), nunca en la
# línea de comando (no aparece en `ps`).
#
# Restaurar un dump:
#   pg_restore -d "postgresql://biblio@localhost/biblio" --clean --if-exists ARCHIVO.dump
set -euo pipefail

BACKUP_DIR="/opt/biblio/backups"
RETENTION="${BACKUP_RETENTION:-14}"   # cuántos dumps conservar

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

# Extraer host/puerto/usuario/db/pass desde DATABASE_URL (.env) sin exponer la pass.
eval "$(/opt/biblio/venv/bin/python - <<'PY'
import shlex, sys
sys.path.insert(0, "/opt/biblio")
from sqlalchemy.engine import make_url
from app.config import settings
u = make_url(settings.database_url)
print(f"export PGHOST={shlex.quote(u.host or 'localhost')}")
print(f"export PGPORT={u.port or 5432}")
print(f"export PGUSER={shlex.quote(u.username or 'biblio')}")
print(f"export PGDATABASE={shlex.quote(u.database or 'biblio')}")
print(f"export PGPASSWORD={shlex.quote(u.password or '')}")
PY
)"

TS="$(date +%Y%m%d-%H%M%S)"
OUT="$BACKUP_DIR/biblio-$TS.dump"

# -Fc = formato custom (comprimido y restaurable selectivamente con pg_restore)
pg_dump -Fc -f "$OUT"
chmod 600 "$OUT"

# Rotación: borrar los más viejos más allá de RETENTION (por fecha de modificación).
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'biblio-*.dump' -printf '%T@\t%p\n' \
  | sort -rn | tail -n +"$((RETENTION + 1))" | cut -f2- \
  | while read -r viejo; do rm -f "$viejo"; done

echo "backup OK: $OUT ($(du -h "$OUT" | cut -f1)) — conservando últimos $RETENTION"
