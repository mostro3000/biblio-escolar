"""Materiales: alta, catálogo y ficha con historial. Solo staff (encargado/admin)."""
import base64
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..cover_ai import leer_tapa
from ..db import get_db
from ..isbn import buscar_libro, isbn_valido, normalizar_isbn
from ..models import (
    TIPO_LABEL,
    EstadoMaterial,
    Incidente,
    IsbnCache,
    Material,
    Persona,
    Prestamo,
    Rol,
    Severidad,
    TipoCodigo,
    TipoMaterial,
    Titulo,
)
from ..schemas import CrearLibroIn, CrearLibroOut, CrearLibroQrIn, CrearTechIn, LibroMetadata
from ..security import requiere_rol, usuario_actual

# Prefijo por defecto del código interno según el tipo (editable en el alta).
PREFIJO_TIPO = {"netbook": "NB", "cargador_netbook": "CN", "adaptador": "AD", "raton": "RT",
                "raspberry": "RPI", "mapa": "MP", "otro": "OT"}
# Prefijo por defecto para libros viejos sin ISBN (QR interno propio).
PREFIJO_LIBRO = "LIB"

router = APIRouter(prefix="/api/materiales", tags=["materiales"])

# Escritura (alta de material): encargado o admin.
StaffDep = Depends(requiere_rol(Rol.encargado, Rol.admin))
# Lectura (lookup, catálogo, ficha): + directivo, que audita sin poder dar de alta.
ReadDep = Depends(requiere_rol(Rol.encargado, Rol.admin, Rol.directivo))
# Cualquier sesión válida (alumno/docente/staff): ver la tapa de un libro.
AnyDep = Depends(usuario_actual)

# Las tapas se guardan como ARCHIVO (fuera de la base, así no la inflan); la DB guarda solo
# la URL en Titulo.cover_url. Vive en /opt/biblio/data (mismo lugar que el padrón, propiedad biblio).
COVERS_DIR = os.path.join(os.getenv("BIBLIO_DATA_DIR", "/opt/biblio/data"), "covers")


def _guardar_tapa(isbn: str, data_url: str) -> str | None:
    """Guarda la foto de la portada (data URL base64) como covers/<isbn>.jpg.
    Devuelve la URL servible por la app, o None si la imagen no es válida."""
    raw = (data_url or "").strip()
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        data = base64.b64decode(raw)
    except Exception:
        return None
    if not data or len(data) > 4 * 1024 * 1024:   # la del navegador ya viene reducida (<~150 KB)
        return None
    os.makedirs(COVERS_DIR, exist_ok=True)
    with open(os.path.join(COVERS_DIR, f"{isbn}.jpg"), "wb") as f:
        f.write(data)
    return f"/api/materiales/cover/{isbn}"


def _describir(db: Session, m: Material) -> str:
    if m.titulo_id:
        t = db.get(Titulo, m.titulo_id)
        base = t.titulo if t else "libro"
        return f"{base} (copia {m.numero_copia})" if m.numero_copia else base
    return f"{TIPO_LABEL.get(m.tipo.value, m.tipo.value)} {m.codigo_interno or ''}".strip()


def _nombre(p: Persona | None) -> str | None:
    if p is None:
        return None
    return " ".join(x for x in (p.nombre, p.apellido) if x) or ("DNI " + p.dni)


@router.get("/isbn/{isbn}", response_model=LibroMetadata)
def lookup_isbn(isbn: str, db: Session = Depends(get_db), _: Persona = ReadDep) -> LibroMetadata:
    """Busca metadata por ISBN en 3 capas, de la más barata a la más cara:
      1) **catálogo LOCAL** (`Titulo`): reconoce libros ya cargados (aunque sus copias estén de baja).
      2) **caché de lookups** (`IsbnCache`): ISBN ya consultado online antes, aunque no se haya cargado.
      3) **APIs online** (Open Library / Google Books); si encuentra, guarda en la caché.
    Así un mismo ISBN no se vuelve a pedir afuera (menos 429, anda sin internet)."""
    norm = normalizar_isbn(isbn)
    candidatos = {norm}
    if isbn_valido(norm):
        candidatos.add(_a_isbn13(norm))   # ISBN-10 escaneado vs ISBN-13 guardado

    # 1) catálogo local
    t = db.scalar(select(Titulo).where(Titulo.isbn.in_(candidatos)))
    if t:
        return LibroMetadata(isbn=t.isbn, encontrado=True, titulo=t.titulo, autor=t.autor,
                             editorial=t.editorial, anio=t.anio, cover_url=t.cover_url, fuente="catalogo")

    # 2) caché de lookups previos
    c = db.scalar(select(IsbnCache).where(IsbnCache.isbn.in_(candidatos)))
    if c:
        return LibroMetadata(isbn=c.isbn, encontrado=True, titulo=c.titulo, autor=c.autor,
                             editorial=c.editorial, anio=c.anio, cover_url=c.cover_url, fuente="cache")

    # 3) online; si hay match, cachear para la próxima
    res = buscar_libro(isbn)
    if res.get("encontrado"):
        cisbn = res["isbn"]
        if not db.get(IsbnCache, cisbn):
            db.add(IsbnCache(isbn=cisbn, titulo=res.get("titulo"), autor=res.get("autor"),
                             editorial=res.get("editorial"), anio=res.get("anio"),
                             cover_url=res.get("cover_url"), fuente=res.get("fuente")))
            db.commit()
    return LibroMetadata(**res)


# Tipos de imagen que la API de Claude acepta como base64.
_MEDIA_OK = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_MAX_IMG = 8 * 1024 * 1024  # 8 MB (el front ya reduce la foto a ~1024px)


class TapaIn(BaseModel):
    imagen_base64: str            # base64 (acepta data URL "data:image/...;base64,XXXX")
    media_type: str | None = None


@router.post("/tapa")
async def leer_tapa_endpoint(payload: TapaIn, _: Persona = StaffDep) -> dict:
    """Lee la tapa de un libro con IA (Claude) cuando el ISBN no aparece online.
    Recibe la foto (base64) y devuelve titulo/autor/editorial/anio para prellenar el alta.
    Solo se envía la imagen de la tapa (sin datos personales)."""
    raw = (payload.imagen_base64 or "").strip()
    if raw.startswith("data:") and "," in raw:   # data URL → quedarse con el base64
        raw = raw.split(",", 1)[1]
    try:
        data = base64.b64decode(raw)
    except Exception:
        raise HTTPException(422, "Imagen inválida.")
    if not data:
        raise HTTPException(422, "No se recibió ninguna imagen.")
    if len(data) > _MAX_IMG:
        raise HTTPException(413, "La imagen es muy grande (máx 8 MB).")
    media = payload.media_type if payload.media_type in _MEDIA_OK else "image/jpeg"
    res = await run_in_threadpool(leer_tapa, data, media)  # urllib bloqueante → threadpool
    if res.get("fuente") == "no_config":
        raise HTTPException(503, "La lectura por IA no está configurada (falta ANTHROPIC_API_KEY).")
    if res.get("fuente") == "error":
        raise HTTPException(502, "No se pudo leer la tapa con IA. Probá de nuevo o cargá a mano.")
    return res


@router.get("/cover/{isbn}")
def cover(isbn: str, _: Persona = AnyDep) -> FileResponse:
    """Sirve la tapa guardada de un libro (la ven staff y alumnos logueados)."""
    safe = "".join(c for c in isbn if c.isalnum())   # evita path traversal
    ruta = os.path.join(COVERS_DIR, f"{safe}.jpg")
    if not safe or not os.path.isfile(ruta):
        raise HTTPException(404, "Sin tapa.")
    # no-cache → revalida por ETag/Last-Modified: si se reemplaza la tapa, se ve la nueva.
    return FileResponse(ruta, media_type="image/jpeg",
                        headers={"Cache-Control": "no-cache"})


class CoverIn(BaseModel):
    cover_base64: str   # foto de la portada (data URL) ya recortada en el navegador


@router.post("/{material_id}/cover")
def cambiar_cover(material_id: int, payload: CoverIn, db: Session = Depends(get_db),
                  _: Persona = StaffDep) -> dict:
    """Cambia la portada de un libro YA cargado (sin agregar copias). La usa el botón de la ficha."""
    m = db.get(Material, material_id)
    if m is None or not m.titulo_id:
        raise HTTPException(404, "No es un libro o no existe.")
    t = db.get(Titulo, m.titulo_id)
    # La tapa se nombra por ISBN; los libros sin ISBN usan una clave por título (t<id>).
    url = _guardar_tapa(t.isbn or f"t{t.id}", payload.cover_base64)
    if not url:
        raise HTTPException(422, "Imagen inválida.")
    t.cover_url = url
    db.commit()
    return {"cover_url": url, "mensaje": "Portada actualizada."}


def _siguiente_codigos(db: Session, prefijo: str, cantidad: int) -> list[str]:
    """Devuelve `cantidad` códigos `PREFIJO-NNN` correlativos, continuando desde el
    mayor sufijo numérico ya usado con ese prefijo (compartido entre tech y libros)."""
    usados = db.scalars(
        select(Material.codigo_interno).where(Material.codigo_interno.like(f"{prefijo}-%"))
    ).all()
    max_n = 0
    for c in usados:
        sufijo = c[len(prefijo) + 1:]
        if sufijo.isdigit():
            max_n = max(max_n, int(sufijo))
    return [f"{prefijo}-{max_n + 1 + i:03d}" for i in range(cantidad)]


def _sanear_prefijo(valor: str | None, default: str) -> str:
    return "".join(c for c in (valor or default).upper() if c.isalnum())[:8] or default


def _a_isbn13(isbn: str) -> str:
    """Convierte un ISBN-10 a ISBN-13 (prefijo 978 + dígito verificador EAN). Deja un
    ISBN-13 tal cual. Así lo guardado coincide con el EAN-13 que se escanea en el mostrador."""
    if len(isbn) != 10:
        return isbn
    core = "978" + isbn[:9]
    s = sum((1 if i % 2 == 0 else 3) * int(d) for i, d in enumerate(core))
    return core + str((10 - s % 10) % 10)


@router.post("/libros", response_model=CrearLibroOut)
def crear_libro(payload: CrearLibroIn, db: Session = Depends(get_db), _: Persona = StaffDep) -> CrearLibroOut:
    """Crea (o reusa) un Titulo por ISBN y le agrega N copias numeradas."""
    isbn = normalizar_isbn(payload.isbn)
    if not isbn_valido(isbn):
        raise HTTPException(422, "El ISBN no es válido (dígito verificador incorrecto).")
    isbn = _a_isbn13(isbn)  # guardar siempre en formato EAN-13 (el que se escanea en préstamos)

    # Tapa: si vino una foto (cover_base64) la guardamos como archivo y usamos su URL;
    # si no, queda la URL del lookup online (OpenLibrary/Google), si la hubo.
    cover_url = payload.cover_url
    if payload.cover_base64:
        cover_url = _guardar_tapa(isbn, payload.cover_base64) or cover_url

    titulo = db.scalar(select(Titulo).where(Titulo.isbn == isbn))
    ya_existia = titulo is not None
    if titulo is None:
        titulo = Titulo(
            isbn=isbn, titulo=payload.titulo, autor=payload.autor,
            editorial=payload.editorial, anio=payload.anio, cover_url=cover_url,
        )
        db.add(titulo)
        db.flush()  # asigna titulo.id
    elif payload.cover_base64 and cover_url:
        titulo.cover_url = cover_url  # foto nueva explícita → reemplaza la tapa anterior
    elif cover_url and not titulo.cover_url:
        titulo.cover_url = cover_url  # el título ya existía sin tapa y ahora tenemos una (p.ej. online)

    # Numerar las copias nuevas continuando desde el máximo existente (1, 2, 3...).
    max_copia = db.scalar(
        select(func.max(Material.numero_copia)).where(Material.titulo_id == titulo.id)
    ) or 0
    nuevos = list(range(max_copia + 1, max_copia + 1 + payload.copias))
    for n in nuevos:
        db.add(Material(
            tipo=TipoMaterial.libro, tipo_codigo=TipoCodigo.isbn_copia,
            titulo_id=titulo.id, numero_copia=n, estado=EstadoMaterial.disponible,
        ))
    db.commit()

    total = db.scalar(
        select(func.count()).select_from(Material).where(Material.titulo_id == titulo.id)
    )
    mensaje = (
        f"Agregadas {len(nuevos)} copia(s) a «{titulo.titulo}» (ahora {total} en total)."
        if ya_existia else
        f"«{titulo.titulo}» creado con {len(nuevos)} copia(s)."
    )
    return CrearLibroOut(
        titulo_id=titulo.id, isbn=isbn, titulo=titulo.titulo, ya_existia=ya_existia,
        copias_agregadas=len(nuevos), copias_totales=total, numeros_copia=nuevos, mensaje=mensaje,
    )


@router.post("/libros-qr", response_model=CrearLibroOut)
def crear_libro_qr(payload: CrearLibroQrIn, db: Session = Depends(get_db), _: Persona = StaffDep) -> CrearLibroOut:
    """Da de alta un libro viejo SIN ISBN como libro completo (título/autor/tapa) pero
    identificado con un QR interno propio (LIB-NNN) por cada copia.

    Aparece en el catálogo de libros y en la búsqueda del alumno, se presta 7/14 días
    como cualquier libro, y el QR imprimible resuelve igual que el de tecnología.
    """
    prefijo = _sanear_prefijo(payload.prefijo, PREFIJO_LIBRO)

    titulo = Titulo(titulo=payload.titulo, autor=payload.autor,
                    editorial=payload.editorial, anio=payload.anio)
    db.add(titulo)
    db.flush()  # asigna titulo.id (clave de la tapa para libros sin ISBN)

    if payload.cover_base64:
        url = _guardar_tapa(f"t{titulo.id}", payload.cover_base64)
        if url:
            titulo.cover_url = url

    codigos = _siguiente_codigos(db, prefijo, payload.copias)
    for n, codigo in enumerate(codigos, start=1):
        db.add(Material(
            tipo=TipoMaterial.libro, tipo_codigo=TipoCodigo.interno,
            titulo_id=titulo.id, numero_copia=n, codigo_interno=codigo,
            estado=EstadoMaterial.disponible,
        ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Algún código ya existía. Reintentá (se reusó un número).")

    return CrearLibroOut(
        titulo_id=titulo.id, isbn=None, titulo=titulo.titulo, ya_existia=False,
        copias_agregadas=len(codigos), copias_totales=len(codigos),
        numeros_copia=list(range(1, len(codigos) + 1)), codigos=codigos,
        mensaje=f"«{titulo.titulo}» creado con {len(codigos)} copia(s): "
                f"{codigos[0]} … {codigos[-1]}." if len(codigos) > 1
                else f"«{titulo.titulo}» creado con código {codigos[0]}.",
    )


@router.post("/tech")
def crear_tech(payload: CrearTechIn, db: Session = Depends(get_db), _: Persona = StaffDep) -> dict:
    """Da de alta N materiales sin ISBN (netbook/adaptador/mapa/otro) con código interno propio.

    Genera códigos `PREFIJO-NNN` correlativos (continúa desde el máximo existente para ese
    prefijo). El QR imprimible codifica ese código, así el escaneo en mostrador/ficha ya resuelve.
    """
    tipo = TipoMaterial(payload.tipo)
    prefijo = _sanear_prefijo(payload.prefijo, PREFIJO_TIPO[payload.tipo])
    etiqueta = (payload.etiqueta or "").strip() or None

    creados = []
    for codigo in _siguiente_codigos(db, prefijo, payload.cantidad):
        m = Material(
            tipo=tipo, tipo_codigo=TipoCodigo.interno, codigo_interno=codigo,
            estado=EstadoMaterial.disponible,
            metadata_json={"etiqueta": etiqueta} if etiqueta else None,
        )
        db.add(m)
        creados.append(m)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Algún código ya existía. Reintentá (se reusó un número).")

    return {
        "creados": [{"id": m.id, "codigo": m.codigo_interno, "tipo": tipo.value,
                     "etiqueta": etiqueta} for m in creados],
        "mensaje": f"Se crearon {len(creados)} {tipo.value}(s): "
                   f"{creados[0].codigo_interno} … {creados[-1].codigo_interno}."
                   if len(creados) > 1 else f"Se creó {creados[0].codigo_interno}.",
    }


@router.get("/catalogo")
def catalogo(clase: str = "libros", q: str = "", tipo: str | None = None,
             db: Session = Depends(get_db), _: Persona = ReadDep) -> dict:
    """Lista lo cargado: `clase=libros` (agrupados por título con conteo de copias)
    o `clase=tech` (materiales con código interno: netbooks, adaptadores, mapas…).

    `q` busca (título/autor/ISBN para libros; código/etiqueta para tech); `tipo` filtra tech.
    """
    q = q.strip()
    if clase == "tech":
        # Solo tech/mapas: los libros sin ISBN también tienen código interno, pero van
        # en la pestaña de libros (no acá).
        stmt = select(Material).where(Material.tipo_codigo == TipoCodigo.interno,
                                      Material.tipo != TipoMaterial.libro)
        if tipo in PREFIJO_TIPO:
            stmt = stmt.where(Material.tipo == TipoMaterial(tipo))
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(
                Material.codigo_interno.ilike(like),
                Material.metadata_json["etiqueta"].astext.ilike(like),
            ))
        rows = db.scalars(stmt.order_by(Material.codigo_interno).limit(500)).all()
        return {"clase": "tech", "total": len(rows), "items": [
            {"id": m.id, "codigo": m.codigo_interno, "tipo": m.tipo.value,
             "tipo_label": TIPO_LABEL.get(m.tipo.value, m.tipo.value),
             "etiqueta": (m.metadata_json or {}).get("etiqueta"), "estado": m.estado.value}
            for m in rows]}

    # libros: agrupados por título, con total de copias y cuántas disponibles
    stmt = select(Titulo)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Titulo.titulo.ilike(like), Titulo.autor.ilike(like),
                              Titulo.isbn.ilike(like)))
    titulos = db.scalars(stmt.order_by(Titulo.titulo).limit(500)).all()
    ids = [t.id for t in titulos]
    cont: dict[int, tuple[int, int]] = {}
    cod_min: dict[int, str | None] = {}
    if ids:
        for tid, total, disp, cmin in db.execute(
            select(Material.titulo_id, func.count(),
                   func.count().filter(Material.estado == EstadoMaterial.disponible),
                   func.min(Material.codigo_interno))
            .where(Material.titulo_id.in_(ids)).group_by(Material.titulo_id)
        ).all():
            cont[tid] = (total, disp)
            cod_min[tid] = cmin
    return {"clase": "libros", "total": len(titulos), "items": [
        {"titulo_id": t.id, "isbn": t.isbn, "titulo": t.titulo, "autor": t.autor,
         # código para abrir la ficha: ISBN si tiene, o el código interno de una copia.
         "codigo": t.isbn or cod_min.get(t.id),
         "total": cont.get(t.id, (0, 0))[0], "disponibles": cont.get(t.id, (0, 0))[1]}
        for t in titulos]}


@router.get("/buscar")
def buscar(codigo: str, db: Session = Depends(get_db), _: Persona = ReadDep) -> dict:
    """Resuelve un código (interno o ISBN) a uno o varios ejemplares para ver su ficha.

    A diferencia del resolver del mostrador, devuelve **todas** las copias sin importar
    el estado (la ficha sirve para auditar cualquier ejemplar, prestado o no).
    """
    codigo = codigo.strip()
    m = db.scalar(select(Material).where(Material.codigo_interno == codigo))
    if m:
        return {"kind": "material", "material_id": m.id,
                "descripcion": _describir(db, m), "estado": m.estado.value}
    t = db.scalar(select(Titulo).where(Titulo.isbn == normalizar_isbn(codigo)))
    if t:
        copias = db.scalars(
            select(Material).where(Material.titulo_id == t.id).order_by(Material.numero_copia)
        ).all()
        return {"kind": "libro", "titulo": t.titulo, "isbn": t.isbn,
                "copias": [{"material_id": c.id, "numero_copia": c.numero_copia,
                            "estado": c.estado.value} for c in copias]}
    return {"kind": "no", "mensaje": "No se encontró ningún material con ese código."}


@router.get("/titulo/{titulo_id}/copias")
def copias_titulo(titulo_id: int, db: Session = Depends(get_db), _: Persona = ReadDep) -> dict:
    """Copias de un título con su código interno, para **reimprimir las etiquetas QR**
    de un libro viejo sin ISBN (las copias con QR propio). Devuelve solo las que tienen
    código interno (los libros por ISBN no llevan QR propio)."""
    t = db.get(Titulo, titulo_id)
    if t is None:
        raise HTTPException(404, "Título inexistente.")
    copias = db.scalars(
        select(Material).where(Material.titulo_id == titulo_id,
                               Material.codigo_interno.isnot(None))
        .order_by(Material.numero_copia)
    ).all()
    return {"titulo": t.titulo, "isbn": t.isbn, "copias": [
        {"numero_copia": m.numero_copia, "codigo": m.codigo_interno, "estado": m.estado.value}
        for m in copias]}


@router.get("/{material_id}/ficha")
def ficha(material_id: int, db: Session = Depends(get_db), _: Persona = ReadDep) -> dict:
    """Ficha de trazabilidad de un ejemplar: estado, préstamo actual, historial e incidentes.

    Responde "¿quién tuvo este ejemplar?": lista cada préstamo (quién, fechas, condición,
    qué encargado lo dio/recibió) del más reciente al más viejo, más todos los incidentes.
    """
    m = db.get(Material, material_id)
    if m is None:
        raise HTTPException(404, "Material inexistente.")
    ahora = datetime.now(timezone.utc)
    t = db.get(Titulo, m.titulo_id) if m.titulo_id else None

    prestamos = db.scalars(
        select(Prestamo).where(Prestamo.material_id == m.id).order_by(Prestamo.prestado_at.desc())
    ).all()

    # Cargar de una vez las personas referenciadas (dueño + encargados) para no consultar en loop.
    pids: set[int] = set()
    for p in prestamos:
        pids.add(p.persona_id)
        if p.encargado_prestamo_id:
            pids.add(p.encargado_prestamo_id)
        if p.encargado_devolucion_id:
            pids.add(p.encargado_devolucion_id)
    personas = {pid: db.get(Persona, pid) for pid in pids}

    historial, prestamo_actual = [], None
    for p in prestamos:
        due = personas.get(p.persona_id)
        abierto = p.devuelto_at is None
        item = {
            "prestamo_id": p.id,
            "persona": _nombre(due),
            "dni": due.dni if due else None,
            "rol": due.rol.value if due else None,
            "prestado_at": p.prestado_at.isoformat() if p.prestado_at else None,
            "vence_at": p.vence_at.isoformat() if p.vence_at else None,
            "devuelto_at": p.devuelto_at.isoformat() if p.devuelto_at else None,
            "condicion": p.condicion_devolucion.value if p.condicion_devolucion else None,
            "abierto": abierto,
            "atrasado": bool(abierto and p.vence_at and p.vence_at < ahora),
            "encargado_prestamo": _nombre(personas.get(p.encargado_prestamo_id)),
            "encargado_devolucion": _nombre(personas.get(p.encargado_devolucion_id)),
            "notas": p.notas,
        }
        historial.append(item)
        if abierto and prestamo_actual is None:
            prestamo_actual = item

    inc_rows = db.scalars(
        select(Incidente).where(Incidente.material_id == m.id).order_by(Incidente.creado_at.desc())
    ).all()
    cpersonas = {i.creado_por_id: db.get(Persona, i.creado_por_id)
                 for i in inc_rows if i.creado_por_id}
    incidentes = [{
        "id": i.id, "descripcion": i.descripcion, "severidad": i.severidad.value,
        "creado_at": i.creado_at.isoformat() if i.creado_at else None,
        "resuelto": i.resuelto_at is not None,
        "resuelto_at": i.resuelto_at.isoformat() if i.resuelto_at else None,
        "creado_por": _nombre(cpersonas.get(i.creado_por_id)),
        "prestamo_id": i.prestamo_id,
    } for i in inc_rows]

    codigo = m.codigo_interno or (f"ISBN {t.isbn} · copia {m.numero_copia}" if t else "—")
    return {
        "material": {
            "id": m.id, "tipo": m.tipo.value, "descripcion": _describir(db, m),
            "codigo": codigo, "estado": m.estado.value,
            "isbn": t.isbn if t else None, "titulo": t.titulo if t else None,
            "autor": t.autor if t else None, "numero_copia": m.numero_copia,
            "cover_url": t.cover_url if t else None,
            "etiqueta": (m.metadata_json or {}).get("etiqueta"),
            "creado_at": m.creado_at.isoformat() if m.creado_at else None,
        },
        "prestamo_actual": prestamo_actual,
        "historial": historial,
        "incidentes": incidentes,
        "stats": {
            "total_prestamos": len(historial),
            "incidentes_abiertos": sum(1 for i in incidentes if not i["resuelto"]),
        },
    }


class IncidenteIn(BaseModel):
    descripcion: str
    severidad: str = "media"   # baja | media | alta


@router.post("/{material_id}/incidente")
def crear_incidente(material_id: int, payload: IncidenteIn, db: Session = Depends(get_db),
                    encargado: Persona = StaffDep) -> dict:
    """Registra un incidente sobre un ejemplar en cualquier momento (no solo al devolver).
    P.ej. una netbook que se rompió guardada. No cambia el estado del material (eso se hace
    aparte con En reparación / Dar de baja)."""
    m = db.get(Material, material_id)
    if m is None:
        raise HTTPException(404, "Material inexistente.")
    desc = (payload.descripcion or "").strip()
    if not desc:
        raise HTTPException(422, "Describí el incidente.")
    try:
        sev = Severidad(payload.severidad)
    except ValueError:
        sev = Severidad.media
    db.add(Incidente(material_id=m.id, descripcion=desc, severidad=sev,
                     creado_por_id=encargado.id))
    db.commit()
    return {"ok": True, "mensaje": f"Incidente registrado para {_describir(db, m)}."}
