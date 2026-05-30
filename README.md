# Biblio — sistema de préstamos de biblioteca escolar

PWA + API para gestionar préstamos y devoluciones con **trazabilidad por ejemplar**
(quién tuvo la netbook 5, cuándo se prestó tal libro, etc.). Pensado para una escuela.

- **Identidad**: onboarding con DNI + biometría (foto del DNI vs selfie); credencial con
  **QR rotativo** (TOTP) para el día a día.
- **Materiales**: libros por **ISBN** (lookup Open Library/Google Books + lectura de tapa con
  IA opcional), y tecnología / libros sin ISBN con **QR interno propio** imprimible.
- **Mostrador**: préstamo y devolución por escaneo; **ficha** con historial e incidentes.
- **Avisos de vencimiento por Web Push** al celular (sin mail).
- **Roles**: alumno, docente, encargado, directivo, admin.

Stack: **FastAPI + PostgreSQL + Apache (proxy) + PWA** (HTML/JS sin framework). Probado en Debian 13.

👉 **Cómo se usa el día a día** (registro, préstamo/devolución, alta de materiales, admin): ver
[`GUIA_DE_USO.md`](GUIA_DE_USO.md).

## Instalación

Requisitos: Debian/Ubuntu con acceso a internet (para `apt` y `pip`).

### Opción A — instalador (tarball)

```bash
tar xzf biblio-1.0.0.tar.gz
cd biblio-1.0.0
sudo ./install.sh --nombre "Esc. Téc. N°5" --logo /ruta/al/logo.png --domain biblio.midominio.edu.ar --admin-dni 12345678
```

Todas las opciones son opcionales (lo que falte se pregunta o se hace después). Ver `./install.sh --help`.

### Opción B — paquete .deb

```bash
sudo apt install ./biblio_1.0.0_all.deb     # instala archivos y dependencias del sistema
sudo biblio-setup --nombre "Esc. Téc. N°5" --domain biblio.midominio.edu.ar
```

El instalador hace todo: usuario de servicio `biblio`, entorno Python, base de datos PostgreSQL
(rol+base con contraseña aleatoria), claves **VAPID** para el push, migraciones, servicios systemd
(app + timers de avisos y backup) y el vhost de Apache.

## Después de instalar

1. **Admin**: `sudo biblio-admin <DNI>` (crea el primer administrador; pide contraseña).
2. **HTTPS**: `sudo certbot --apache -d tu.dominio` (si configuraste el dominio).
3. **Padrón de alumnos**: poné un DNI por línea en `/opt/biblio/data/lista.txt` e importá:
   `sudo -u biblio /opt/biblio/venv/bin/python /opt/biblio/scripts/import_padron.py --file /opt/biblio/data/lista.txt`
   (para docentes: agregá `--rol docente`).
4. **Claves opcionales** en `/opt/biblio/.env` (después `sudo systemctl restart biblio`):
   - `GOOGLE_BOOKS_API_KEY` — mejora el lookup de ISBN (gratis, console.cloud.google.com).
   - `ANTHROPIC_API_KEY` — habilita leer la tapa con IA cuando el ISBN no aparece.

## Nombre y logo de la escuela

Configurables en cualquier momento:

```bash
sudo biblio-rebrand "Nombre de la escuela" /ruta/al/logo.png
```

El logo ideal es cuadrado (PNG). Si está instalado `imagemagick`, se generan los íconos de la PWA
(`icon-192/512`, `apple-touch-icon`, `favicon`). El crédito de versión aparece al tocar el logo en la portada.

## Datos sensibles / privacidad

- El **padrón** (`/opt/biblio/data/lista.txt`) y la base contienen datos personales (de menores):
  viven fuera del webroot, con permisos restrictivos. No se incluyen en el paquete.
- De la biometría se guarda **solo el vector facial** (embedding), nunca la foto.
- Secretos en `/opt/biblio/.env` (perms 600) y la clave privada VAPID en
  `/opt/biblio/vapid_private.pem`. **Nunca** se distribuyen.

## Licencia

GNU **GPL v3** (ver [`LICENSE`](LICENSE)). `SPDX-License-Identifier: GPL-3.0-or-later`.

Creado por **mt**.
