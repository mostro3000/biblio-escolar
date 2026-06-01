# Guía de uso — Biblio

Cómo se usa el sistema en el día a día. (La **instalación** está en [`README.md`](README.md).)

Todo se accede desde el navegador del celular o la compu, en la dirección de tu escuela
(ej. `https://biblio.tuescuela.edu.ar`). Conviene **agregarlo a la pantalla de inicio**
(se comporta como una app y, en iPhone, es lo que habilita los avisos).

## Roles

| Rol | Quién | Qué puede hacer |
|-----|-------|-----------------|
| **Alumno / Docente** | usuarios de la biblioteca | Registrarse, mostrar su credencial (QR), ver disponibilidad, recibir avisos. |
| **Encargado** | bibliotecario/a | Prestar y devolver, dar de alta materiales, ver fichas, resolver incidentes. |
| **Directivo** | dirección | Ver reportes y operar el mostrador (no da de alta ni administra personas). |
| **Admin** | responsable del sistema | Todo lo anterior + aprobar registros, gestionar personas y roles. |

---

## Para el alumno / docente

### 1. Registrarse (una sola vez)
1. Entrar a la portada → **📷 Registrarme**.
2. **Escanear el DNI** (código de la parte de atrás): saca DNI, nombre y apellido solos.
3. **Sacar una selfie**: se compara con la foto del DNI para confirmar identidad.
   - Si coincide → queda **activo** al instante.
   - Si hay duda → queda **en revisión** (lo aprueba un admin desde el panel).
4. Listo: ya tenés tu credencial.

> El DNI tiene que estar en el **padrón** que cargó la escuela. De la cara solo se guarda un
> "código matemático" (vector), **nunca la foto**.

### 2. Tu credencial
- En la portada → **🪪 Mi credencial**. Muestra un **QR que cambia cada ~30 segundos** + tu nombre
  y tus préstamos activos. Funciona **sin internet** (el código se calcula en el celu).
- Para pedir prestado, le mostrás ese QR al encargado. (Como rota, una captura vieja no sirve.)

### 3. ¿Hay material disponible?
- Desde la credencial → **📦 ¿Hay material disponible?**. Buscás por título/autor (libros) o ves
  los conteos de tecnología ("netbooks: 2 de 5"). Solo dice **cuántos hay libres**, nunca quién los tiene.

### 4. Activar los avisos de vencimiento
- En la credencial, botón **🔔 Activar avisos** → aceptás el permiso de notificaciones.
- Te llega un push al celular cuando un préstamo **vence hoy** o quedó **atrasado**.
- **iPhone**: primero "Agregar a inicio" y abrir desde el ícono (el push web en iOS solo anda con la app instalada). En Android funciona directo.

---

## Para el encargado (mostrador)

### Prestar — `Préstamo`
1. **Escanear el QR del alumno** (con que esté a la vista alcanza).
2. Aparecen sus datos, préstamos activos y alertas (atrasos, suspensión).
3. **Escanear cada material**: el código de barras (ISBN) del libro o el QR interno.
   - Si el libro tiene varias copias, el sistema pregunta cuál (1, 2, 3…).
   - Al escanear un libro se muestra su **tapa**, para verificar que leyó bien.
4. **Confirmar préstamo**. El vencimiento se calcula según tipo y rol (libro 7 días alumno / 14 docente, etc.).

### Devolver — `Devolución`
1. Escanear el material que se devuelve.
2. Marcar la condición: **OK** o **con observación** (la observación crea un **incidente**).
3. El material vuelve a quedar disponible.

### Ficha de un material — `Ficha`
- Escaneás o tipeás el código (ISBN o interno) y ves **toda la historia del ejemplar**: estado,
  quién lo tiene ahora, historial de préstamos (quién, cuándo, qué encargado), e incidentes.
- Responde "¿quién tuvo la netbook 5?". Desde acá también se cambia el estado (en reparación / baja)
  y se imprime el QR de esa copia.

---

## Alta de materiales

### Libros con ISBN — `Libros`
1. **Escanear el código de barras** (ISBN) de la contratapa, o tipearlo.
2. El sistema busca los datos online (título/autor/tapa). Revisás y ponés cuántas **copias**.
3. **Guardar**. Si el ISBN ya existía, suma copias (numeradas 1, 2, 3…).
   - **No se imprime QR**: el libro se identifica por su ISBN + el número de copia escrito a mano.
   - Si el ISBN no aparece online, podés **sacarle una foto a la tapa** y la IA lee título y autor
     (requiere configurar `ANTHROPIC_API_KEY`; si no, lo cargás a mano).

### Libros viejos SIN ISBN — `Libros` → "📕 El libro no tiene ISBN"
1. Sacás foto de la tapa (la IA lee el título) o cargás los datos a mano.
2. Ponés cuántas copias y **Crear y generar QR**.
3. Se imprime una etiqueta con **QR propio** (`LIB-001`, `LIB-002`…) para pegar en cada copia.
4. A partir de ahí se presta/devuelve escaneando ese QR, como cualquier libro.

### Tecnología y mapas — `Tecnología`
- Netbooks, adaptadores, mapas, etc.: se les genera un **código interno** (`NB-001`, `MP-001`…) y
  una **etiqueta con QR** imprimible. El QR se escanea igual en el mostrador.

### Reimprimir etiquetas QR
- **Catálogo** → pestaña Libros: el botón 🖨️ junto a un libro sin ISBN reimprime **todas** sus copias.
- **Catálogo** → pestaña Tecnología: seleccionás ítems y reimprimís.
- **Ficha**: botón "🖨️ Imprimir QR" para esa copia puntual.

---

## Catálogo — `Catálogo`
- **Libros**: agrupados por título, con copias totales y disponibles. Buscador por título/autor/ISBN.
- **Tecnología**: ítems con su código y estado. Click en cualquiera → su ficha.

---

## Panel de administración — `Admin` (solo admin)

- **Zona gris**: registros que quedaron "en revisión" → **Aprobar / Rechazar**.
- **Personas**: listar/buscar, **crear** (DNI + rol), **suspender/reactivar** (suspender corta la sesión
  al instante), **cambiar rol** (p.ej. hacer encargada a la bibliotecaria) y **poner/cambiar contraseña** de staff.
- **Incidentes**: marcar resueltos. **Materiales fuera de servicio**: reactivar.
- **Reportes** (directivo/admin, pestaña aparte): préstamos, atrasos, más prestados, por tipo, por mes, etc.

### Alta de staff (encargado / directivo / admin) — primer ingreso

Cuando el admin **crea** un usuario de staff (o le **cambia el rol** a staff) sin ponerle clave,
el sistema le asigna como **contraseña inicial su propio DNI**. En su primer ingreso:

1. Entra en **Ingresar (personal)** con **DNI** y, como contraseña, **el mismo DNI**.
2. El sistema lo lleva a una pantalla de **cambio obligatorio** y no lo deja operar hasta elegir
   una contraseña nueva (distinta del DNI).

> Recomendación de seguridad: como el DNI no es secreto, conviene **dar de alta al encargado y que
> cambie la clave en el momento** (o ponerle vos una clave con 🔑 y comunicársela). Si el admin fija
> la clave con 🔑, no se pide el cambio obligatorio.

---

## Operación y mantenimiento (consola del servidor)

```bash
# Importar el padrón de alumnos (un DNI por línea en data/lista.txt)
sudo -u biblio /opt/biblio/venv/bin/python /opt/biblio/scripts/import_padron.py --file /opt/biblio/data/lista.txt
#   docentes:  ... import_padron.py --file /opt/biblio/data/docentes.txt --rol docente

# Crear o cambiar un admin
sudo biblio-admin <DNI>

# Cambiar el nombre y/o logo de la escuela
sudo biblio-rebrand "Nombre de la escuela" /ruta/al/logo.png

# Estado del backend y logs
systemctl status biblio
journalctl -u biblio -f
sudo systemctl restart biblio      # tras editar /opt/biblio/.env

# Avisos de vencimiento: corren solos a las 08:00. Para probar a mano:
sudo systemctl start biblio-avisos.service && journalctl -u biblio-avisos -n 20

# Backups: corren solos (diario). Quedan en /opt/biblio/backups/
```

**Claves opcionales** en `/opt/biblio/.env` (después `sudo systemctl restart biblio`):
- `GOOGLE_BOOKS_API_KEY` — mejora el lookup de ISBN online (gratis).
- `ANTHROPIC_API_KEY` — habilita leer la tapa con IA cuando el ISBN no aparece.

---

## Privacidad

El padrón y la base tienen datos de menores: viven fuera del webroot, con permisos restrictivos.
De la biometría se guarda solo el vector facial, nunca la foto. Los secretos están en `/opt/biblio/.env`.

---

_Sistema bajo licencia [GPL v3](LICENSE). Creado por mt._
