"""Línea de comandos: python -m meazclador CARPETA_DE_PISTAS"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .mezcla import Opciones, exportar, mezclar


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="meazclador",
        description="Mezcla y masteriza automáticamente las pistas WAV de tu banda.",
    )
    ap.add_argument("carpeta", type=Path, help="carpeta con una pista WAV por instrumento/voz")
    ap.add_argument("-o", "--salida", type=Path, help="carpeta de salida (por defecto: CARPETA/mezcla)")
    ap.add_argument("--referencia", type=Path, help="tema de un disco que te guste: se imita su sonido y volumen")
    ap.add_argument("--lufs", type=float, default=-14.0, help="volumen final (-14 Spotify/YouTube, -9 muy fuerte)")
    ap.add_argument("--afinar", type=float, default=0.0, metavar="FUERZA",
                    help="afinar voces y coros, de 0 a 1 (recomendado 0.5; 0 = no tocar)")
    ap.add_argument("--tonalidad", help="tonalidad del tema para afinar mejor, ej: Am, E, 'La menor'")
    args = ap.parse_args(argv)

    if not args.carpeta.is_dir():
        print(f"No existe la carpeta {args.carpeta}", file=sys.stderr)
        return 1
    if not 0 <= args.afinar <= 1:
        print("--afinar va de 0 a 1", file=sys.stderr)
        return 1

    opciones = Opciones(afinar=args.afinar, tonalidad=args.tonalidad, lufs=args.lufs, referencia=args.referencia)
    resultado = mezclar(args.carpeta, opciones)
    destino = args.salida or args.carpeta / "mezcla"
    for ruta in exportar(resultado, destino):
        print(f"✔ {ruta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
