#!/usr/bin/env bash
# Instalador de Biblio — sistema de préstamos de biblioteca escolar.
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Uso (como root, en Debian/Ubuntu):
#   sudo ./install.sh [opciones]
#
# Opciones:
#   --nombre "Esc. Téc. N°5"   Nombre de la escuela (default: "Biblioteca Escolar")
#   --logo  /ruta/logo.png     Logo (genera íconos PWA si está imagemagick)
#   --domain biblio.midominio  Dominio para el vhost de Apache (si se omite, lo pregunta)
#   --admin-dni 12345678       Crea el admin inicial con ese DNI (pide la contraseña)
#   --no-apache                No tocar Apache
#   --skip-deps                No instalar paquetes del sistema (apt)
#   -y, --yes                  No preguntar nada (modo desatendido)
#   -h, --help                 Esta ayuda
set -euo pipefail

NOMBRE="Biblioteca Escolar"; LOGO=""; DOMAIN=""; ADMIN_DNI=""
DO_APACHE=1; DO_DEPS=1; ASSUME_YES=0

usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; }
while [ $# -gt 0 ]; do
  case "$1" in
    --nombre) NOMBRE="$2"; shift 2;;
    --logo) LOGO="$2"; shift 2;;
    --domain) DOMAIN="$2"; shift 2;;
    --admin-dni) ADMIN_DNI="$2"; shift 2;;
    --no-apache) DO_APACHE=0; shift;;
    --skip-deps) DO_DEPS=0; shift;;
    -y|--yes) ASSUME_YES=1; shift;;
    -h|--help) usage; exit 0;;
    *) echo "Opción desconocida: $1"; usage; exit 1;;
  esac
done

[ "$(id -u)" -eq 0 ] || { echo "ERROR: ejecutá como root (sudo)."; exit 1; }

SRC="$(cd "$(dirname "$0")" && pwd)"
APP=/opt/biblio
WEB=/var/www/html/biblio
PRISTINE=/usr/share/biblio/web

echo "==> Biblio — instalación / configuración"

# 1) Paquetes del sistema
if [ "$DO_DEPS" -eq 1 ]; then
  echo "==> Instalando dependencias del sistema (apt)…"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq || true
  apt-get install -y python3 python3-venv python3-pip postgresql apache2 openssl
fi

# 2) Usuario de servicio
id biblio >/dev/null 2>&1 || adduser --system --group --home "$APP" --no-create-home --disabled-login biblio

# 3) Copiar archivos (si no estamos corriendo ya desde /opt/biblio, p.ej. desde el tarball)
mkdir -p "$APP" "$PRISTINE"
if [ "$SRC" != "$APP" ]; then
  echo "==> Copiando archivos a $APP …"
  cp -a "$SRC/app" "$SRC/alembic" "$SRC/scripts" "$APP/"
  cp -a "$SRC/alembic.ini" "$SRC/requirements.txt" "$SRC/.env.example" "$SRC/VERSION" "$SRC/install.sh" "$APP/"
  cp -a "$SRC/LICENSE" "$SRC/README.md" "$APP/" 2>/dev/null || true
  cp -a "$SRC/systemd" "$SRC/apache" "$APP/"
fi
# Front "pristino" (con el token @@ESCUELA@@) → /usr/share/biblio/web
if [ -d "$SRC/web" ]; then
  rm -rf "$PRISTINE"; mkdir -p "$PRISTINE"; cp -a "$SRC/web/." "$PRISTINE/"
fi
[ -n "$(ls -A "$PRISTINE" 2>/dev/null || true)" ] || { echo "ERROR: falta el front en $PRISTINE"; exit 1; }

# Comandos auxiliares
if [ -d "$SRC/bin" ]; then install -m 0755 "$SRC"/bin/* /usr/sbin/; fi

mkdir -p "$APP/data/covers" "$APP/backups"

# 4) Entorno Python
if [ ! -x "$APP/venv/bin/python" ]; then
  echo "==> Creando entorno virtual…"
  python3 -m venv "$APP/venv"
fi
echo "==> Instalando dependencias Python…"
"$APP/venv/bin/pip" install --quiet --upgrade pip wheel
"$APP/venv/bin/pip" install --quiet -r "$APP/requirements.txt"

# 5) PostgreSQL: rol + base de datos
echo "==> Configurando PostgreSQL…"
systemctl start postgresql 2>/dev/null || true
DBPASS=""
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='biblio'" 2>/dev/null | grep -q 1; then
  DBPASS="$(openssl rand -hex 24)"
  sudo -u postgres psql -qc "CREATE ROLE biblio LOGIN PASSWORD '${DBPASS}'"
fi
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='biblio'" 2>/dev/null | grep -q 1; then
  sudo -u postgres createdb -O biblio biblio
fi

# 6) .env (solo si no existe; no pisar uno existente)
if [ ! -f "$APP/.env" ]; then
  echo "==> Generando .env…"
  cp "$APP/.env.example" "$APP/.env"
  if [ -n "$DBPASS" ]; then
    sed -i "s#^DATABASE_URL=.*#DATABASE_URL=postgresql+psycopg://biblio:${DBPASS}@localhost:5432/biblio#" "$APP/.env"
  fi
  ESCN="$(printf '%s' "$NOMBRE" | sed 's/[&/\]/\\&/g')"
  sed -i "s/^BIBLIO_NOMBRE=.*/BIBLIO_NOMBRE=${ESCN}/" "$APP/.env"
fi

# 7) Claves VAPID (Web Push) si faltan
if ! grep -q '^VAPID_PUBLIC_KEY=..' "$APP/.env"; then
  echo "==> Generando claves VAPID (Web Push)…"
  PUB="$("$APP/venv/bin/python" - <<'PY'
import base64
from py_vapid import Vapid01
from cryptography.hazmat.primitives import serialization
v = Vapid01(); v.generate_keys(); v.save_key("/opt/biblio/vapid_private.pem")
raw = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
print(base64.urlsafe_b64encode(raw).rstrip(b'=').decode())
PY
)"
  sed -i "s#^VAPID_PUBLIC_KEY=.*#VAPID_PUBLIC_KEY=${PUB}#" "$APP/.env"
fi

# 8) Permisos (el servicio corre como 'biblio')
chown -R biblio:biblio "$APP"
chmod 600 "$APP/.env"
[ -f "$APP/vapid_private.pem" ] && chmod 600 "$APP/vapid_private.pem"
chmod 750 "$APP/data"; chmod 700 "$APP/backups"

# 9) Migraciones (crean el esquema en la base vacía)
echo "==> Aplicando migraciones de la base…"
( cd "$APP" && sudo -u biblio "$APP/venv/bin/alembic" upgrade head )

# 10) systemd (servicio + timers de avisos y backup)
echo "==> Instalando servicios systemd…"
cp "$APP"/systemd/*.service "$APP"/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now biblio.service
systemctl enable --now biblio-avisos.timer biblio-backup.timer 2>/dev/null || true

# 11) Front: aplicar nombre y logo de la escuela
echo "==> Aplicando branding (nombre/logo)…"
if [ -n "$LOGO" ]; then /opt/biblio/scripts/rebrand.sh "$NOMBRE" "$LOGO"; else /opt/biblio/scripts/rebrand.sh "$NOMBRE"; fi

# 12) Apache
if [ "$DO_APACHE" -eq 1 ]; then
  if [ -z "$DOMAIN" ] && [ "$ASSUME_YES" -eq 0 ] && [ -t 0 ]; then
    printf "   Dominio para Apache (Enter para configurar después): "; read -r DOMAIN || true
  fi
  if [ -n "$DOMAIN" ]; then
    a2enmod proxy proxy_http headers >/dev/null 2>&1 || true
    sed "s/__DOMAIN__/${DOMAIN}/g" "$APP/apache/biblio.conf.example" > /etc/apache2/sites-available/biblio.conf
    a2ensite biblio.conf >/dev/null 2>&1 || true
    systemctl reload apache2 2>/dev/null || systemctl restart apache2 2>/dev/null || true
    echo "   Apache OK → http://${DOMAIN}   (HTTPS: certbot --apache -d ${DOMAIN})"
  else
    echo "   Apache: sin dominio. Editá $APP/apache/biblio.conf.example y activalo cuando quieras."
  fi
fi

# 13) Admin inicial
if [ -n "$ADMIN_DNI" ]; then
  echo "==> Creando admin inicial (DNI ${ADMIN_DNI})…"
  "$APP/venv/bin/python" "$APP/scripts/crear_admin.py" "$ADMIN_DNI"
fi

cat <<FIN

============================================================
 Biblio instalado.  Backend escuchando en 127.0.0.1:8091.

 Faltan estos pasos manuales:
   1) Admin:   sudo biblio-admin <DNI>        (si no lo creaste con --admin-dni)
   2) Dominio: configurá Apache + HTTPS (certbot) si no pusiste --domain
   3) Padrón:  poné los DNIs en $APP/data/lista.txt y corré
               sudo -u biblio $APP/venv/bin/python $APP/scripts/import_padron.py --file $APP/data/lista.txt
   4) (Opcional) claves en $APP/.env: GOOGLE_BOOKS_API_KEY, ANTHROPIC_API_KEY
      (después de editar: sudo systemctl restart biblio)

 Cambiar nombre/logo cuando quieras:
   sudo biblio-rebrand "Nombre nuevo" [/ruta/logo.png]
============================================================
FIN
