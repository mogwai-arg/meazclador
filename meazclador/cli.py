"""Línea de comandos.

    meazclador cortar SESION        separa una grabación larga en temas
    meazclador mezclar CARPETA      mezcla y masteriza un tema (o todos los de una carpeta)
    meazclador retocar TEMA --voz +2 --presencia 0.8   retoca una mezcla hecha, en segundos
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from .mezcla import ARCHIVO_RETOQUES, ESTILOS, GRUPOS_RETOQUE, Opciones, Retoques, listar_pistas, mezclar_y_guardar, retocar
from .sesion import a_reloj, cortar, detectar_temas, energia, escribir_lista, info_pistas, leer_cortes

CARPETAS_SALIDA = {"mezcla", "masters"}


def _opciones_mezcla() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    g = p.add_argument_group("mezcla")
    g.add_argument("--referencia", type=Path, help="tema de un disco que te guste: se imita su sonido y volumen")
    g.add_argument("--estilo", choices=list(ESTILOS), default="natural",
                   help="natural (limpio) o punk (crudo, estilo Ramones)")
    g.add_argument("--lufs", type=float, help="volumen final (-14 Spotify/YouTube, -10 rock fuerte; "
                   "por defecto lo decide el estilo)")
    g.add_argument("--afinar", type=float, metavar="FUERZA",
                   help="afinar voces y coros, de 0 a 1 (0 = no tocar; por defecto lo decide el estilo)")
    g.add_argument("--guitarras", choices=["auto", "directas", "amplificadas"], default="auto",
                   help="cómo se grabaron: directas (por línea/DI, se les simula el ampli) o amplificadas")
    g.add_argument("--sample-bombo", type=Path, help="WAV de un golpe de bombo para el sampler (estilo punk)")
    g.add_argument("--sample-caja", type=Path, help="WAV de un golpe de caja para el sampler (estilo punk)")
    g.add_argument("--tonalidad", help="tonalidad para afinar mejor, ej: Am, E, 'La menor' (sólo si mezclás un tema)")
    return p


def _temas_en(carpeta: Path) -> list[Path]:
    """Subcarpetas con pistas (lo que deja 'cortar')."""
    return sorted(d for d in carpeta.iterdir()
                  if d.is_dir() and d.name not in CARPETAS_SALIDA and listar_pistas(d))


def _mezclar_uno(carpeta: Path, opciones: Opciones, destino: Path) -> Path:
    rutas = mezclar_y_guardar(carpeta, opciones, destino)
    for ruta in rutas:
        print(f"✔ {ruta}")
    return rutas[0]


def cmd_mezclar(args) -> int:
    if args.afinar is not None and not 0 <= args.afinar <= 1:
        print("--afinar va de 0 a 1", file=sys.stderr)
        return 1
    opciones = Opciones(afinar=args.afinar, tonalidad=args.tonalidad, lufs=args.lufs, referencia=args.referencia,
                        estilo=args.estilo, sample_bombo=args.sample_bombo, sample_caja=args.sample_caja,
                        guitarras=args.guitarras)
    if listar_pistas(args.carpeta):
        _mezclar_uno(args.carpeta, opciones, args.salida or args.carpeta / "mezcla")
        return 0

    temas = _temas_en(args.carpeta)
    if not temas:
        print(f"No encontré pistas de audio en {args.carpeta} ni en sus subcarpetas.", file=sys.stderr)
        return 1
    if args.tonalidad:
        print("Aviso: --tonalidad se ignora al mezclar varios temas (cada uno puede estar en otra).")
        opciones.tonalidad = None
    masters = args.salida or args.carpeta / "masters"
    masters.mkdir(parents=True, exist_ok=True)
    for i, tema in enumerate(temas, 1):
        print(f"\n=== {tema.name} ({i}/{len(temas)}) ===")
        master = _mezclar_uno(tema, opciones, tema / "mezcla")
        shutil.copyfile(master, masters / f"{tema.name}.wav")
    print(f"\nTodos los masters juntos en {masters}")
    return 0


def cmd_retocar(args) -> int:
    destino = args.tema / "mezcla" if (args.tema / "mezcla").is_dir() else args.tema
    retoques = Retoques.cargar(destino / ARCHIVO_RETOQUES)  # se parte de los retoques anteriores
    for grupo in GRUPOS_RETOQUE:
        if getattr(args, grupo) is not None:
            setattr(retoques, grupo, getattr(args, grupo))
    if args.reverb is not None:
        retoques.reverb = args.reverb / 100
    if args.sala is not None:
        retoques.sala = args.sala / 100
    if args.voz_principal is not None:
        retoques.voz_principal = None if args.voz_principal.lower() in ("", "auto", "automatico") else args.voz_principal
    if args.presencia is not None:
        retoques.presencia = args.presencia
    if args.lufs is not None:
        retoques.lufs = args.lufs
    if args.desde_cero:
        retoques = Retoques()
    print(f"Retoques: {retoques.resumen()}")
    for ruta in retocar(destino, retoques):
        print(f"✔ {ruta}")
    if args.tema.parent.name and (args.tema.parent / "masters").is_dir():
        shutil.copyfile(destino / "master.wav", args.tema.parent / "masters" / f"{args.tema.name}.wav")
    return 0


def cmd_cortar(args) -> int:
    archivos = listar_pistas(args.sesion)
    if not archivos:
        print(f"No encontré pistas de audio en {args.sesion}", file=sys.stderr)
        return 1
    sr, duracion, avisos = info_pistas(archivos)
    print(f"{len(archivos)} pistas de {a_reloj(duracion)} a {sr} Hz.")
    for a in avisos:
        print(a)

    if args.cortes:
        ruta = Path(args.cortes)
        temas = leer_cortes(ruta.read_text(encoding="utf-8") if ruta.is_file() else args.cortes)
    else:
        print("Buscando dónde empieza y termina cada tema...")
        nivel = energia(archivos)
        temas, _ = detectar_temas(nivel, min_tema_s=args.min_tema, sensibilidad=args.sensibilidad)
        if not temas:
            print("No encontré temas. Probá bajar --sensibilidad o --min-tema, o pasá los tiempos con --cortes.")
            return 1

    destino = args.salida or args.sesion / "temas"
    destino.mkdir(parents=True, exist_ok=True)
    lista = destino / "temas.txt"
    escribir_lista(temas, lista)
    print(f"\n{len(temas)} temas:")
    for i, t in enumerate(temas, 1):
        print(f"  {i:2d}. {a_reloj(t.inicio):>6} a {a_reloj(t.fin):>6}  ({a_reloj(t.duracion)})  {t.nombre}")
    print(f"Lista guardada en {lista} (editala y usá --cortes para corregir).")

    if args.solo_mostrar:
        return 0
    print("\nCortando pistas...")
    cortar(archivos, temas, destino)
    print(f"✔ Temas en {destino}")

    if args.mezclar:
        args.carpeta, args.salida, args.tonalidad = destino, None, None
        return cmd_mezclar(args)
    print(f"\nSiguiente paso:  meazclador mezclar \"{destino}\"")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:  # sin argumentos: abrir la ventana
        from .gui import main as gui

        return gui()
    # Compatibilidad: 'meazclador CARPETA' sigue siendo mezclar.
    if argv and argv[0] not in ("cortar", "mezclar", "retocar", "-h", "--help"):
        argv.insert(0, "mezclar")

    mezcla = _opciones_mezcla()
    ap = argparse.ArgumentParser(prog="meazclador", description="Mezcla y masteriza las pistas de tu banda.")
    sub = ap.add_subparsers(dest="comando", required=True)

    pm = sub.add_parser("mezclar", parents=[mezcla], help="mezclar y masterizar un tema o una carpeta de temas")
    pm.add_argument("carpeta", type=Path, help="carpeta con las pistas de un tema, o con una subcarpeta por tema")
    pm.add_argument("-o", "--salida", type=Path, help="carpeta de salida")
    pm.set_defaults(func=cmd_mezclar)

    pc = sub.add_parser("cortar", parents=[mezcla], help="separar una grabación larga en temas")
    pc.add_argument("sesion", type=Path, help="carpeta con las pistas largas (una por micrófono/instrumento)")
    pc.add_argument("-o", "--salida", type=Path, help="dónde dejar los temas (por defecto: SESION/temas)")
    pc.add_argument("--cortes", help="tiempos a mano: archivo de texto o '0:12-4:05, 4:40-8:55'")
    pc.add_argument("--solo-mostrar", action="store_true", help="sólo detectar y listar los temas, sin cortar")
    pc.add_argument("--sensibilidad", type=float, default=0.45,
                    help="0..1: más bajo si junta dos temas o corta finales suaves, más alto si deja charla adentro")
    pc.add_argument("--min-tema", type=float, default=60, metavar="SEG", help="duración mínima de un tema (s)")
    pc.add_argument("--mezclar", action="store_true", help="después de cortar, mezclar todos los temas")
    pc.set_defaults(func=cmd_cortar)

    pr = sub.add_parser("retocar", help="retocar una mezcla ya hecha (rápido: no vuelve a procesar las pistas)")
    pr.add_argument("tema", type=Path, help="carpeta del tema (la que tiene la subcarpeta 'mezcla')")
    for grupo in GRUPOS_RETOQUE:
        pr.add_argument(f"--{grupo}", type=float, metavar="DB", help=f"subir/bajar {grupo} en dB (ej: +2, -1.5)")
    pr.add_argument("--reverb", type=float, metavar="%", help="cantidad de reverb: 0 = nada, 100 = la del estilo")
    pr.add_argument("--presencia", type=float, help="0..1: cuánto trae todo adelante el máster")
    pr.add_argument("--sala", type=float, metavar="%",
                    help="sacar sala: 0 = la habitación original, 100 = lo del estilo, 150 = más seco")
    pr.add_argument("--voz-principal", metavar="PISTA",
                    help="qué pista es la voz principal en este tema (ej: 'Coro 1.wav'); 'auto' = automático. "
                         "Vuelve a procesar sólo las voces")
    pr.add_argument("--lufs", type=float, help="volumen final")
    pr.add_argument("--desde-cero", action="store_true", help="olvidar los retoques anteriores")
    pr.set_defaults(func=cmd_retocar)

    args = ap.parse_args(argv)
    if args.comando == "mezclar" and not args.carpeta.is_dir():
        print(f"No existe la carpeta {args.carpeta}", file=sys.stderr)
        return 1
    if args.comando == "retocar" and not args.tema.is_dir():
        print(f"No existe la carpeta {args.tema}", file=sys.stderr)
        return 1
    if args.comando == "cortar" and not args.sesion.is_dir():
        print(f"No existe la carpeta {args.sesion}", file=sys.stderr)
        return 1
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
