"""Lo que la ventana recuerda entre usos (las últimas carpetas elegidas)."""

from __future__ import annotations

import json
import os
from pathlib import Path


def _ruta() -> Path:
    return Path(os.environ.get("MEAZCLADOR_PREFERENCIAS", Path.home() / ".meazclador.json"))


def cargar() -> dict:
    try:
        return json.loads(_ruta().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def guardar(**valores) -> None:
    datos = cargar()
    datos.update({k: v for k, v in valores.items() if v is not None})
    try:
        _ruta().write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # no poder recordar una carpeta nunca tiene que romper la ventana
