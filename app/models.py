"""Modelos SQLAlchemy del sistema de biblioteca.

Reflejan el modelo de datos de DISEÑO.md:
Persona, Titulo, Material, Prestamo, Incidente, Sesion.
"""
import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Rol(str, enum.Enum):
    alumno = "alumno"
    docente = "docente"
    encargado = "encargado"
    directivo = "directivo"
    admin = "admin"


class EstadoPersona(str, enum.Enum):
    pendiente = "pendiente"
    activo = "activo"
    suspendido = "suspendido"


class TipoMaterial(str, enum.Enum):
    libro = "libro"
    netbook = "netbook"
    adaptador = "adaptador"
    raton = "raton"
    raspberry = "raspberry"
    mapa = "mapa"
    otro = "otro"


# Etiqueta linda para mostrar (el valor del enum es ASCII/corto; acá el nombre real).
TIPO_LABEL = {
    "libro": "libro", "netbook": "netbook", "adaptador": "adaptador",
    "raton": "ratón", "raspberry": "Raspberry Pi 400", "mapa": "mapa", "otro": "otro",
}


class TipoCodigo(str, enum.Enum):
    isbn_copia = "isbn_copia"
    interno = "interno"


class EstadoMaterial(str, enum.Enum):
    disponible = "disponible"
    prestado = "prestado"
    en_reparacion = "en_reparacion"
    baja = "baja"


class CondicionDevolucion(str, enum.Enum):
    ok = "ok"
    observacion = "observacion"


class Severidad(str, enum.Enum):
    baja = "baja"
    media = "media"
    alta = "alta"


def _creado_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Persona(Base):
    __tablename__ = "persona"

    id: Mapped[int] = mapped_column(primary_key=True)
    dni: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    # nombre/apellido quedan NULL hasta el onboarding: el padrón aporta SOLO el DNI.
    # Se completan al escanear el DNI (el PDF417 del dorso trae apellido y nombre en
    # campos separados, así que no hay que adivinar dónde corta cada uno).
    nombre: Mapped[str | None] = mapped_column(String(120))
    apellido: Mapped[str | None] = mapped_column(String(120))
    rol: Mapped[Rol] = mapped_column(Enum(Rol, name="rol"), default=Rol.alumno)
    # curso/division descartados: mantenerlos al día año a año no compensa para el
    # caso de uso. Fácil de re-agregar si hicieran falta reportes por curso.
    mail: Mapped[str | None] = mapped_column(String(160))
    telefono: Mapped[str | None] = mapped_column(String(40))
    # Solo para staff (encargado/admin): login por DNI + contraseña. Alumnos usan QR.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    # True cuando la clave es temporal (= DNI, recién creada): obliga a cambiarla al entrar.
    debe_cambiar_password: Mapped[bool] = mapped_column(default=False, server_default="false")
    # Token opaco y estable del QR personal (se genera al activarse en el onboarding).
    qr_token: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)
    # Embedding facial (128 floats). Solo la selfie, nunca la foto. Nullable hasta el onboarding.
    foto_embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float))
    estado: Mapped[EstadoPersona] = mapped_column(
        Enum(EstadoPersona, name="estado_persona"), default=EstadoPersona.pendiente
    )
    creado_at: Mapped[datetime] = _creado_at()

    prestamos: Mapped[list["Prestamo"]] = relationship(
        back_populates="persona", foreign_keys="Prestamo.persona_id"
    )


class Titulo(Base):
    """Agrupa las copias de un libro (1 fila por ISBN)."""

    __tablename__ = "titulo"

    id: Mapped[int] = mapped_column(primary_key=True)
    isbn: Mapped[str | None] = mapped_column(String(20), unique=True, index=True)
    titulo: Mapped[str] = mapped_column(String(300))
    autor: Mapped[str | None] = mapped_column(String(200))
    editorial: Mapped[str | None] = mapped_column(String(160))
    anio: Mapped[int | None] = mapped_column(Integer)
    cover_url: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)
    creado_at: Mapped[datetime] = _creado_at()

    materiales: Mapped[list["Material"]] = relationship(back_populates="titulo")


class Material(Base):
    """Ejemplar físico individual."""

    __tablename__ = "material"
    __table_args__ = (
        # (titulo + numero_copia) único para libros; codigo_interno único para el resto.
        UniqueConstraint("titulo_id", "numero_copia", name="uq_material_titulo_copia"),
        UniqueConstraint("codigo_interno", name="uq_material_codigo_interno"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[TipoMaterial] = mapped_column(Enum(TipoMaterial, name="tipo_material"))
    tipo_codigo: Mapped[TipoCodigo] = mapped_column(Enum(TipoCodigo, name="tipo_codigo"))
    titulo_id: Mapped[int | None] = mapped_column(ForeignKey("titulo.id"))
    numero_copia: Mapped[int | None] = mapped_column(Integer)
    codigo_interno: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)
    estado: Mapped[EstadoMaterial] = mapped_column(
        Enum(EstadoMaterial, name="estado_material"), default=EstadoMaterial.disponible
    )
    creado_at: Mapped[datetime] = _creado_at()

    titulo: Mapped["Titulo | None"] = relationship(back_populates="materiales")
    prestamos: Mapped[list["Prestamo"]] = relationship(back_populates="material")


class Prestamo(Base):
    __tablename__ = "prestamo"

    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("material.id"), index=True)
    persona_id: Mapped[int] = mapped_column(ForeignKey("persona.id"), index=True)
    prestado_at: Mapped[datetime] = _creado_at()
    vence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    devuelto_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    condicion_devolucion: Mapped[CondicionDevolucion | None] = mapped_column(
        Enum(CondicionDevolucion, name="condicion_devolucion")
    )
    checklist_json: Mapped[dict | None] = mapped_column(JSONB)
    notas: Mapped[str | None] = mapped_column(Text)
    encargado_prestamo_id: Mapped[int | None] = mapped_column(ForeignKey("persona.id"))
    encargado_devolucion_id: Mapped[int | None] = mapped_column(ForeignKey("persona.id"))

    material: Mapped["Material"] = relationship(back_populates="prestamos")
    persona: Mapped["Persona"] = relationship(
        back_populates="prestamos", foreign_keys=[persona_id]
    )


class Incidente(Base):
    __tablename__ = "incidente"

    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("material.id"), index=True)
    prestamo_id: Mapped[int | None] = mapped_column(ForeignKey("prestamo.id"))
    descripcion: Mapped[str] = mapped_column(Text)
    severidad: Mapped[Severidad] = mapped_column(
        Enum(Severidad, name="severidad"), default=Severidad.media
    )
    creado_at: Mapped[datetime] = _creado_at()
    resuelto_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    creado_por_id: Mapped[int | None] = mapped_column(ForeignKey("persona.id"))


class IsbnCache(Base):
    """Caché de lookups de ISBN online (Open Library / Google Books).

    Evita re-consultar afuera el mismo ISBN (menos 429, funciona offline). Guarda solo
    lookups EXITOSOS. Es independiente del catálogo (`Titulo`): un ISBN puede estar acá
    aunque nunca se haya dado de alta como libro.
    """

    __tablename__ = "isbn_cache"

    isbn: Mapped[str] = mapped_column(String(20), primary_key=True)  # ISBN normalizado
    titulo: Mapped[str | None] = mapped_column(String(300))
    autor: Mapped[str | None] = mapped_column(String(200))
    editorial: Mapped[str | None] = mapped_column(String(160))
    anio: Mapped[int | None] = mapped_column(Integer)
    cover_url: Mapped[str | None] = mapped_column(Text)
    fuente: Mapped[str | None] = mapped_column(String(20))  # openlibrary | google
    creado_at: Mapped[datetime] = _creado_at()


class PushSubscription(Base):
    """Suscripción Web Push de un dispositivo (para avisos de vencimiento al celular).

    Una persona puede tener varias (un celu, una tablet…). Se identifican por su
    `endpoint` (único). Si un envío devuelve 404/410, la suscripción está muerta y se borra.
    """

    __tablename__ = "push_subscription"

    id: Mapped[int] = mapped_column(primary_key=True)
    persona_id: Mapped[int] = mapped_column(ForeignKey("persona.id"), index=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(Text)    # clave pública del cliente (cifrado del payload)
    auth: Mapped[str] = mapped_column(Text)      # secreto de auth del cliente
    user_agent: Mapped[str | None] = mapped_column(String(300))
    creado_at: Mapped[datetime] = _creado_at()


class Sesion(Base):
    """Sesión de auth de la PWA (token opaco en cookie)."""

    __tablename__ = "sesion"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # token aleatorio
    persona_id: Mapped[int] = mapped_column(ForeignKey("persona.id"), index=True)
    creado_at: Mapped[datetime] = _creado_at()
    expira_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revocada: Mapped[bool] = mapped_column(default=False)
