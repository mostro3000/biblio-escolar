"""Parser del PDF417 del dorso del DNI argentino.

El barcode trae los campos separados por `@`. El formato varía un poco entre
versiones de tarjeta (algunas agregan un campo al principio), pero la secuencia
relativa siempre es:  ... APELLIDO @ NOMBRE @ SEXO @ NRO_DNI @ ...

Anclamos en el campo SEXO (un solo carácter M/F/X) seguido del número de DNI, y
leemos el resto por posición relativa. Así no dependemos de índices fijos ni de
que el usuario tipee el DNI: lo sacamos del propio documento.

Nota: si el QR del DNI nuevo trae el mismo payload `@`-delimitado, este parser lo
lee igual. Si trajera otro formato (JSON/URL), extender acá — el endpoint
`escanear-dni` deja en el log el contenido crudo para poder verlo.
"""
SEXOS = {"M", "F", "X"}


def parse_pdf417(raw: str) -> dict | None:
    """Devuelve {'dni','apellido','nombre','sexo'} o None si no se pudo leer."""
    if not raw or "@" not in raw:
        return None

    partes = [p.strip() for p in raw.split("@")]

    for i, p in enumerate(partes):
        # Ancla: SEXO (1 char M/F/X), con APELLIDO y NOMBRE antes y el DNI después.
        if p.upper() in SEXOS and i >= 2 and i + 1 < len(partes):
            dni = "".join(c for c in partes[i + 1] if c.isdigit())
            apellido = partes[i - 2]
            nombre = partes[i - 1]
            if 6 <= len(dni) <= 9 and apellido and nombre:
                return {"dni": dni, "apellido": apellido, "nombre": nombre, "sexo": p.upper()}

    return None
