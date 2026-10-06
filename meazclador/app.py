"""Punto de entrada del ejecutable (Meazclador.exe / Meazclador.app).

Sin argumentos abre la ventana. Con argumentos se comporta como la línea de comandos.
'--prueba' mezcla una banda sintética y sale con código 0 si todo funcionó
(lo usa la compilación automática para verificar el ejecutable).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def autoprueba() -> int:
    from . import demo
    from .cli import main as cli

    with tempfile.TemporaryDirectory() as tmp:
        pistas = Path(tmp) / "pistas"
        demo.main(pistas)
        codigo = cli(["mezclar", str(pistas), "--afinar", "0.5", "--tonalidad", "Am"])
        ok = codigo == 0 and (pistas / "mezcla" / "master.wav").stat().st_size > 100_000
    print("AUTOPRUEBA OK" if ok else "AUTOPRUEBA FALLÓ")
    return 0 if ok else 1


def main() -> int:
    # En el ejecutable con ventana (sin consola) no hay salida estándar.
    for nombre in ("stdout", "stderr"):
        if getattr(sys, nombre) is None:
            setattr(sys, nombre, open(os.devnull, "w", encoding="utf-8"))
    args = sys.argv[1:]
    if args == ["--prueba"]:
        return autoprueba()
    if args and not args[0].startswith("-psn"):  # macOS agrega -psn_... al abrir con doble clic
        from .cli import main as cli

        return cli(args)
    from .gui import main as gui

    return gui()


if __name__ == "__main__":
    sys.exit(main())
