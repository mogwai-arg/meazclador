"""Punto de entrada del ejecutable (Meazclador.exe / Meazclador.app).

Sin argumentos abre la ventana. Con argumentos se comporta como la línea de comandos.
'--prueba' mezcla una banda sintética, la pasa a MP3 y sale con código 0 si todo funcionó
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
        ok = True
        for estilo in ("natural", "punk"):
            codigo = cli(["mezclar", str(pistas), "--estilo", estilo, "--afinar", "0.5", "--tonalidad", "Am"])
            ok = ok and codigo == 0 and (pistas / "mezcla" / "master.wav").stat().st_size > 100_000
        # Pasar a MP3 con etiquetas (el codificador y mutagen tienen que venir dentro del ejecutable).
        codigo = cli(["convertir", str(pistas / "mezcla"), "--disco", "Prueba", "--artista", "Meazclador"])
        mp3 = pistas / "mezcla" / "mp3" / "master.mp3"
        ok = ok and codigo == 0 and mp3.is_file() and mp3.stat().st_size > 50_000
    from .reproductor import Reproductor

    # En Windows y Mac PortAudio viene dentro del paquete: si no carga, el empaquetado está mal.
    # (No se exige una placa de sonido: las máquinas de compilación no tienen.)
    audio_ok = Reproductor()._sd is not None
    print(f"Reproducción de audio: {'disponible' if audio_ok else 'no disponible'}")
    if sys.platform in ("win32", "darwin"):
        ok = ok and audio_ok
    print("AUTOPRUEBA OK" if ok else "AUTOPRUEBA FALLÓ")
    return 0 if ok else 1


def main() -> int:
    # En el ejecutable con ventana (sin consola) no hay salida estándar.
    for nombre in ("stdout", "stderr"):
        if getattr(sys, nombre) is None:
            setattr(sys, nombre, open(os.devnull, "w", encoding="utf-8"))
    # Cuando la ventana lanza un trabajo como proceso aparte, lee su salida línea por línea:
    # UTF-8 (Windows usaría cp1252 y fallaría con acentos y símbolos) y sin demoras.
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except (AttributeError, ValueError):
            pass
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
