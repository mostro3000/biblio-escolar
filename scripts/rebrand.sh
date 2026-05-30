#!/bin/sh
# Aplica el NOMBRE y (opcional) el LOGO de la escuela al frontend.
#
# Uso:  biblio-rebrand ["Nombre de la escuela"] [/ruta/al/logo.png]
#   - Sin nombre: usa BIBLIO_NOMBRE del .env (o "Biblioteca Escolar").
#   - Con logo: lo copia y, si está imagemagick, regenera los íconos de la PWA.
#
# Regenera /var/www/html/biblio desde la copia "pristina" /usr/share/biblio/web
# (que conserva el token @@ESCUELA@@), así se puede recambiar cuantas veces se quiera.
set -e

PRISTINE=/usr/share/biblio/web
SERVED=/var/www/html/biblio
ENV=/opt/biblio/.env

[ -d "$PRISTINE" ] || { echo "ERROR: no existe $PRISTINE (¿está instalado el paquete?)."; exit 1; }

NOMBRE="$1"
if [ -z "$NOMBRE" ] && [ -f "$ENV" ]; then
  NOMBRE=$(grep '^BIBLIO_NOMBRE=' "$ENV" 2>/dev/null | head -1 | cut -d= -f2-)
fi
[ -z "$NOMBRE" ] && NOMBRE="Biblioteca Escolar"
LOGO="$2"

# 1) regenerar el front desde la copia pristina y aplicar el nombre
mkdir -p "$SERVED"
cp -a "$PRISTINE/." "$SERVED/"
# escapar caracteres especiales de sed en el nombre (& / \)
ESC=$(printf '%s' "$NOMBRE" | sed -e 's/[&/\]/\\&/g')
grep -rIl '@@ESCUELA@@' "$SERVED" 2>/dev/null | while IFS= read -r f; do
  sed -i "s/@@ESCUELA@@/$ESC/g" "$f"
done

# versión del sistema (crédito del logo en la portada)
VER=$(cat /opt/biblio/VERSION 2>/dev/null || echo "1.0.0")
grep -rIl '@@VERSION@@' "$SERVED" 2>/dev/null | while IFS= read -r f; do
  sed -i "s/@@VERSION@@/$VER/g" "$f"
done

# 2) logo (opcional)
if [ -n "$LOGO" ]; then
  [ -f "$LOGO" ] || { echo "ERROR: no existe el logo $LOGO"; exit 1; }
  cp "$LOGO" "$SERVED/logo.jpg"
  if command -v convert >/dev/null 2>&1; then
    convert "$LOGO" -resize 192x192 "$SERVED/icon-192.png"
    convert "$LOGO" -resize 512x512 "$SERVED/icon-512.png"
    convert "$LOGO" -resize 180x180 "$SERVED/apple-touch-icon.png"
    convert "$LOGO" -resize 64x64   "$SERVED/favicon.png"
    echo "Logo e íconos de la PWA regenerados."
  else
    cp "$LOGO" "$SERVED/favicon.png"
    echo "Logo aplicado. (Instalá 'imagemagick' y volvé a correr con --logo para regenerar icon-192/512 y apple-touch-icon.)"
  fi
fi

# 3) recordar el nombre en el .env (para sobrevivir upgrades)
if [ -f "$ENV" ]; then
  if grep -q '^BIBLIO_NOMBRE=' "$ENV"; then
    ESC_ENV=$(printf '%s' "$NOMBRE" | sed -e 's/[&/\]/\\&/g')
    sed -i "s/^BIBLIO_NOMBRE=.*/BIBLIO_NOMBRE=$ESC_ENV/" "$ENV"
  else
    printf 'BIBLIO_NOMBRE=%s\n' "$NOMBRE" >> "$ENV"
  fi
fi

chmod -R a+rX "$SERVED"
echo "OK. Front actualizado con «$NOMBRE» en $SERVED"
