"""Lookup de metadata de libros por ISBN.

Open Library primero (gratis, sin key), fallback a Google Books. Solo stdlib
para no agregar dependencias; las llamadas son bloqueantes pero el endpoint
corre en threadpool (def sync), así que no traba el event loop.
"""
import json
import os
import re
import urllib.request

TIMEOUT = 6  # segundos por API
_UA = "biblio-escolar/1.0 (+https://example.org)"
# Opcional: con una API key propia (gratis en Google Cloud), Google Books deja de dar 429
# por cuota anónima compartida. Si está vacía, se consulta igual (cuota compartida).
_GOOGLE_KEY = os.getenv("GOOGLE_BOOKS_API_KEY", "").strip()


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _anio(texto: str | None) -> int | None:
    if not texto:
        return None
    m = re.search(r"\d{4}", texto)
    return int(m.group()) if m else None


def normalizar_isbn(s: str) -> str:
    return "".join(c for c in s if c.isdigit() or c in "Xx").upper()


def isbn_valido(s: str) -> bool:
    """Valida el dígito verificador de un ISBN-13 o ISBN-10."""
    isbn = normalizar_isbn(s)
    if len(isbn) == 13 and isbn.isdigit():
        total = sum((1 if i % 2 == 0 else 3) * int(d) for i, d in enumerate(isbn))
        return total % 10 == 0
    if len(isbn) == 10:
        total = 0
        for i, ch in enumerate(isbn):
            if ch == "X":
                v = 10
            elif ch.isdigit():
                v = int(ch)
            else:
                return False
            total += (10 - i) * v
        return total % 11 == 0
    return False


def _open_library(isbn: str) -> dict | None:
    url = f"https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data"
    item = _get_json(url).get(f"ISBN:{isbn}")
    if not item:
        return None
    autores = ", ".join(a["name"] for a in item.get("authors", []) if a.get("name"))
    editoriales = ", ".join(p["name"] for p in item.get("publishers", []) if p.get("name"))
    cover = item.get("cover") or {}
    return {
        "titulo": item.get("title"),
        "autor": autores or None,
        "editorial": editoriales or None,
        "anio": _anio(item.get("publish_date")),
        "cover_url": cover.get("large") or cover.get("medium") or cover.get("small"),
        "fuente": "openlibrary",
    }


def _google_books(isbn: str) -> dict | None:
    url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}&country=AR"
    if _GOOGLE_KEY:
        url += f"&key={_GOOGLE_KEY}"
    items = _get_json(url).get("items") or []
    if not items:
        return None
    vi = items[0].get("volumeInfo", {})
    cover = (vi.get("imageLinks") or {}).get("thumbnail")
    if cover:
        cover = cover.replace("http://", "https://")
    return {
        "titulo": vi.get("title"),
        "autor": ", ".join(vi.get("authors", [])) or None,
        "editorial": vi.get("publisher"),
        "anio": _anio(vi.get("publishedDate")),
        "cover_url": cover,
        "fuente": "google",
    }


def buscar_libro(isbn_raw: str) -> dict:
    """Devuelve metadata del libro.

    - encontrado=True con datos, o
    - encontrado=False con fuente='no_encontrado' (las APIs respondieron sin match), o
    - encontrado=False con fuente='error' (no se pudieron consultar: timeout, 429, red).
    Así la UI distingue "no existe" de "reintentá".
    """
    isbn = normalizar_isbn(isbn_raw)
    hubo_error = False
    for buscar in (_open_library, _google_books):
        try:
            r = buscar(isbn)
        except Exception:
            hubo_error = True
            r = None
        if r and r.get("titulo"):
            return {**r, "isbn": isbn, "encontrado": True}
    return {
        "isbn": isbn, "encontrado": False, "titulo": None, "autor": None,
        "editorial": None, "anio": None, "cover_url": None,
        "fuente": "error" if hubo_error else "no_encontrado",
    }
