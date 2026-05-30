"""Schemas Pydantic (entrada/salida de la API)."""
from pydantic import BaseModel, field_validator


def normalizar_dni(v: str) -> str:
    """Acepta "46.332.978", "46 332 978", etc. y deja solo dígitos.

    Sin asumir rango nativo (hay DNIs de extranjeros); solo largo plausible.
    """
    digitos = "".join(c for c in v if c.isdigit())
    if not (6 <= len(digitos) <= 9):
        raise ValueError("DNI inválido")
    return digitos


class VerificarDniIn(BaseModel):
    dni: str

    @field_validator("dni")
    @classmethod
    def _norm(cls, v: str) -> str:
        return normalizar_dni(v)


class VerificarDniOut(BaseModel):
    dni: str
    existe: bool           # está en el padrón
    ya_registrado: bool    # ya completó el onboarding (estado activo)
    suspendido: bool
    puede_registrarse: bool
    mensaje: str


class EscanearDniIn(BaseModel):
    pdf417: str            # string crudo del PDF417 del dorso, decodificado en el cliente


class EscanearDniOut(BaseModel):
    dni: str
    existe: bool           # el DNI está en el padrón
    ya_registrado: bool
    suspendido: bool
    puede_continuar: bool  # pendiente -> nombre guardado, sigue a la selfie
    puede_relogin: bool = False  # ya activo + tiene biometría -> puede entrar con selfie
    nombre: str | None
    apellido: str | None
    mensaje: str


class ReloginIn(BaseModel):
    dni: str
    embedding_selfie: list[float]   # 128 floats de la selfie (se compara con el guardado)

    @field_validator("dni")
    @classmethod
    def _norm(cls, v: str) -> str:
        return normalizar_dni(v)

    @field_validator("embedding_selfie")
    @classmethod
    def _len_128(cls, v: list[float]) -> list[float]:
        if len(v) != 128:
            raise ValueError("el embedding debe tener exactamente 128 valores")
        return v


class BiometriaIn(BaseModel):
    dni: str
    embedding_dni: list[float]      # 128 floats del rostro en la foto del DNI
    embedding_selfie: list[float]   # 128 floats del rostro en la selfie

    @field_validator("dni")
    @classmethod
    def _norm(cls, v: str) -> str:
        return normalizar_dni(v)

    @field_validator("embedding_dni", "embedding_selfie")
    @classmethod
    def _len_128(cls, v: list[float]) -> list[float]:
        if len(v) != 128:
            raise ValueError("el embedding debe tener exactamente 128 valores")
        return v


class BiometriaOut(BaseModel):
    aprobado: bool
    resultado: str    # 'activo' | 'revision' | 'rechazado'
    distancia: float
    mensaje: str


class LibroMetadata(BaseModel):
    isbn: str
    encontrado: bool
    titulo: str | None
    autor: str | None
    editorial: str | None
    anio: int | None
    cover_url: str | None
    fuente: str       # 'openlibrary' | 'google' | 'no_encontrado' | 'error'


class LoginIn(BaseModel):
    dni: str
    password: str

    @field_validator("dni")
    @classmethod
    def _norm(cls, v: str) -> str:
        return normalizar_dni(v)


class MeOut(BaseModel):
    dni: str
    nombre: str | None
    apellido: str | None
    rol: str


class CrearLibroIn(BaseModel):
    isbn: str
    titulo: str
    autor: str | None = None
    editorial: str | None = None
    anio: int | None = None
    cover_url: str | None = None
    cover_base64: str | None = None   # foto de la portada (data URL) ya recortada en el navegador
    copias: int = 1

    @field_validator("titulo")
    @classmethod
    def _titulo(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("el título es obligatorio")
        return v

    @field_validator("copias")
    @classmethod
    def _copias(cls, v: int) -> int:
        if not (1 <= v <= 50):
            raise ValueError("la cantidad de copias debe estar entre 1 y 50")
        return v


class CrearLibroQrIn(BaseModel):
    """Libro viejo SIN ISBN: se carga como libro completo (título/autor/tapa) pero
    se identifica con un QR interno propio (LIB-NNN), igual que tecnología."""
    titulo: str
    autor: str | None = None
    editorial: str | None = None
    anio: int | None = None
    cover_base64: str | None = None   # foto de la portada (data URL) ya recortada en el navegador
    copias: int = 1
    prefijo: str | None = None        # default "LIB"

    @field_validator("titulo")
    @classmethod
    def _titulo(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("el título es obligatorio")
        return v

    @field_validator("copias")
    @classmethod
    def _copias(cls, v: int) -> int:
        if not (1 <= v <= 50):
            raise ValueError("la cantidad de copias debe estar entre 1 y 50")
        return v


class CrearLibroOut(BaseModel):
    titulo_id: int
    isbn: str | None              # None para libros sin ISBN (identificados por QR propio)
    titulo: str
    ya_existia: bool
    copias_agregadas: int
    copias_totales: int
    numeros_copia: list[int]
    codigos: list[str] | None = None   # códigos internos (LIB-NNN) si es libro sin ISBN
    mensaje: str


class PrestamoIn(BaseModel):
    persona_id: int           # resuelto al escanear el QR rotativo del alumno
    material_ids: list[int]
    dias: int | None = None   # override del vencimiento por defecto


class DevolucionIn(BaseModel):
    material_id: int
    condicion: str            # 'ok' | 'observacion'
    notas: str | None = None

    @field_validator("condicion")
    @classmethod
    def _cond(cls, v: str) -> str:
        if v not in ("ok", "observacion"):
            raise ValueError("condicion debe ser 'ok' u 'observacion'")
        return v


class CrearTechIn(BaseModel):
    tipo: str                  # 'netbook' | 'adaptador' | 'mapa' | 'otro' (NO libro)
    cantidad: int = 1
    prefijo: str | None = None # default según el tipo (NB/AD/MP/OT)
    etiqueta: str | None = None  # texto libre (ej. "Aula 3", "Lenovo ThinkPad")

    @field_validator("tipo")
    @classmethod
    def _t(cls, v: str) -> str:
        if v not in ("netbook", "adaptador", "raton", "raspberry", "mapa", "otro"):
            raise ValueError("tipo inválido (los libros se cargan por ISBN)")
        return v

    @field_validator("cantidad")
    @classmethod
    def _c(cls, v: int) -> int:
        if not (1 <= v <= 50):
            raise ValueError("la cantidad debe estar entre 1 y 50")
        return v


class CambiarEstadoMaterialIn(BaseModel):
    estado: str               # 'disponible' | 'en_reparacion' | 'baja'

    @field_validator("estado")
    @classmethod
    def _e(cls, v: str) -> str:
        if v not in ("disponible", "en_reparacion", "baja"):
            raise ValueError("estado inválido")
        return v


class CambiarEstadoPersonaIn(BaseModel):
    estado: str               # 'activo' | 'suspendido' (activo = aprobar/reactivar)

    @field_validator("estado")
    @classmethod
    def _e(cls, v: str) -> str:
        if v not in ("activo", "suspendido"):
            raise ValueError("estado inválido")
        return v


class ResolverIncidenteIn(BaseModel):
    resuelto: bool = True     # False = reabrir


class CambiarRolIn(BaseModel):
    rol: str                  # 'alumno' | 'docente' | 'encargado' | 'admin'

    @field_validator("rol")
    @classmethod
    def _r(cls, v: str) -> str:
        if v not in ("alumno", "docente", "encargado", "directivo", "admin"):
            raise ValueError("rol inválido")
        return v


class SetPasswordIn(BaseModel):
    password: str

    @field_validator("password")
    @classmethod
    def _p(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("la contraseña debe tener al menos 6 caracteres")
        return v


class CrearPersonaIn(BaseModel):
    dni: str
    rol: str = "alumno"

    @field_validator("dni")
    @classmethod
    def _norm(cls, v: str) -> str:
        return normalizar_dni(v)

    @field_validator("rol")
    @classmethod
    def _r(cls, v: str) -> str:
        if v not in ("alumno", "docente", "encargado", "directivo", "admin"):
            raise ValueError("rol inválido")
        return v
