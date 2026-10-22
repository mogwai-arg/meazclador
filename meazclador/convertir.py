"""Pasar los masters (WAV) a MP3 con las etiquetas del disco (título, número de tema, disco y artista),
o cargarle esas etiquetas a MP3 que ya existen."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .audio import Cancelado

CALIDADES = (320, 256, 192, 128)  # kbps
CARPETA_MP3 = "mp3"
SR_MP3 = (32000, 44100, 48000)  # las que admite un MP3 normal (MPEG-1)
NO_FINALES = {"premaster.wav", "master_anterior.wav"}  # en la carpeta 'mezcla' de un tema
_NUMERO = re.compile(r"^\s*(\d{1,3})\s*[-_.)\s]+\s*(.*)$")


@dataclass
class Tema:
    archivo: Path  # WAV para convertir o MP3 para etiquetar
    orden: int
    titulo: str


def wavs_en(carpeta: Path) -> list[Path]:
    """Los WAV de la carpeta. Si se elige la carpeta 'temas', se usan los de su subcarpeta 'masters'."""
    if not carpeta.is_dir():
        return []
    wavs = sorted(p for p in carpeta.iterdir() if p.is_file() and p.suffix.lower() == ".wav"
                  and not p.name.startswith(".") and p.name.lower() not in NO_FINALES)
    if not wavs and (carpeta / "masters").is_dir():
        return wavs_en(carpeta / "masters")
    return wavs


def mp3s_en(carpeta: Path) -> list[Path]:
    if not carpeta.is_dir():
        return []
    return sorted(p for p in carpeta.iterdir() if p.is_file() and p.suffix.lower() == ".mp3"
                  and not p.name.startswith(".") and not p.name.endswith(".parcial.mp3"))


def archivos_en(carpeta: Path) -> tuple[list[Path], str]:
    """(archivos, 'wav' o 'mp3'): con WAV se convierte; si sólo hay MP3, se les cargan los datos."""
    wavs = wavs_en(carpeta)
    if wavs:
        return wavs, "wav"
    mp3s = mp3s_en(carpeta)
    return (mp3s, "mp3") if mp3s else ([], "wav")


def leer_etiquetas(mp3: Path) -> dict:
    """Lo que ya tiene cargado un MP3: titulo, orden, disco y artista (vacío si no tiene)."""
    from mutagen.id3 import ID3, ID3NoHeaderError

    try:
        t = ID3(mp3)
    except (ID3NoHeaderError, OSError):
        return {"titulo": "", "orden": None, "disco": "", "artista": ""}

    def texto(clave: str) -> str:
        return str(t[clave].text[0]).strip() if clave in t and t[clave].text else ""

    numero = re.match(r"\s*(\d+)", texto("TRCK"))
    return {"titulo": texto("TIT2"), "orden": int(numero.group(1)) if numero else None,
            "disco": texto("TALB"), "artista": texto("TPE1") or texto("TPE2")}


def titulo_y_orden(nombre: str) -> tuple[str, int | None]:
    """'03_Help' -> ('Help', 3); 'Twist and shout' -> ('Twist and shout', None)."""
    m = _NUMERO.match(nombre)
    numero, resto = (int(m.group(1)), m.group(2)) if m and m.group(2).strip() else (None, nombre)
    titulo = re.sub(r"\s+", " ", resto.replace("_", " ")).strip()
    return titulo or nombre, numero


def temas_de(archivos: list[Path]) -> list[Tema]:
    """Título y número de cada tema: los que ya tiene cargados el MP3, o si no, los del nombre del
    archivo (o su lugar en la lista)."""
    temas = []
    for i, archivo in enumerate(archivos, 1):
        titulo, numero = titulo_y_orden(archivo.stem)
        if archivo.suffix.lower() == ".mp3":
            cargado = leer_etiquetas(archivo)
            titulo, numero = cargado["titulo"] or titulo, cargado["orden"] or numero
        temas.append(Tema(archivo, numero or i, titulo))
    return temas


def datos_comunes(mp3s: list[Path]) -> dict:
    """Disco y artista que comparten todos los MP3 (vacío si no tienen o si difieren)."""
    datos = [leer_etiquetas(m) for m in mp3s]
    comunes = {}
    for clave in ("disco", "artista"):
        valores = {d[clave] for d in datos}
        comunes[clave] = valores.pop() if len(valores) == 1 else ""
    return comunes


def etiquetar(mp3: Path, titulo: str, orden: int, total: int, disco: str = "", artista: str = "") -> None:
    """Carga título, número, disco y artista. Lo demás que tenga el MP3 (la tapa, el año...) se respeta;
    un disco o artista vacío deja el que ya tenía."""
    from mutagen.id3 import ID3, TALB, TIT2, TPE1, TPE2, TRCK, ID3NoHeaderError

    try:
        etiquetas = ID3(mp3)
    except ID3NoHeaderError:
        etiquetas = ID3()
    for clave in ("TIT2", "TRCK"):
        etiquetas.delall(clave)
    if disco:
        etiquetas.delall("TALB")
    if artista:
        etiquetas.delall("TPE1")
        etiquetas.delall("TPE2")
    etiquetas.add(TIT2(encoding=3, text=titulo))
    etiquetas.add(TRCK(encoding=3, text=f"{orden}/{total}"))
    if disco:
        etiquetas.add(TALB(encoding=3, text=disco))
    if artista:
        etiquetas.add(TPE1(encoding=3, text=artista))
        etiquetas.add(TPE2(encoding=3, text=artista))  # artista del disco: que no se separe en el celular
    etiquetas.save(mp3)


def a_mp3(wav: Path, mp3: Path, kbps: int = 320, cancelar=lambda: False) -> None:
    from pedalboard.io import AudioFile

    mp3.parent.mkdir(parents=True, exist_ok=True)
    temporal = mp3.with_name(mp3.stem + ".parcial.mp3")
    with AudioFile(str(wav)) as entrada:
        if entrada.samplerate not in SR_MP3:
            entrada = entrada.resampled_to(48000 if entrada.samplerate > 48000 else 44100)
        canales = min(entrada.num_channels, 2)
        try:
            with AudioFile(str(temporal), "w", entrada.samplerate, canales, quality=kbps) as salida:
                bloque = int(entrada.samplerate) * 10
                while entrada.tell() < entrada.frames:
                    if cancelar():
                        raise Cancelado()
                    audio = entrada.read(bloque)[:canales]
                    salida.write(np.clip(audio, -1.0, 1.0))
        except BaseException:
            temporal.unlink(missing_ok=True)
            raise
    temporal.replace(mp3)


def convertir(temas: list[Tema], destino: Path, kbps: int = 320, disco: str = "", artista: str = "",
              avisar=print, cancelar=lambda: False) -> list[Path]:
    if kbps not in CALIDADES:
        raise ValueError(f"Calidad {kbps} kbps no válida: usá {', '.join(map(str, CALIDADES))}")
    if not temas:
        raise ValueError("No hay archivos WAV para convertir")
    total = max(t.orden for t in temas)
    hechos = []
    for i, tema in enumerate(temas, 1):
        avisar(f"=== {tema.archivo.name} ({i}/{len(temas)}) ===")
        mp3 = destino / (tema.archivo.stem + ".mp3")
        a_mp3(tema.archivo, mp3, kbps, cancelar)
        etiquetar(mp3, tema.titulo, tema.orden, max(total, len(temas)), disco, artista)
        mb = mp3.stat().st_size / 1e6
        avisar(f"✔ {mp3}  ({mb:.1f} MB)")
        hechos.append(mp3)
    return hechos


def etiquetar_mp3s(temas: list[Tema], disco: str = "", artista: str = "", avisar=print,
                   cancelar=lambda: False) -> list[Path]:
    """Carga los datos del disco a MP3 que ya existen (no toca el audio)."""
    if not temas:
        raise ValueError("No hay archivos MP3")
    total = max(max(t.orden for t in temas), len(temas))
    for i, tema in enumerate(temas, 1):
        if cancelar():
            raise Cancelado()
        avisar(f"=== {tema.archivo.name} ({i}/{len(temas)}) ===")
        etiquetar(tema.archivo, tema.titulo, tema.orden, total, disco, artista)
        avisar(f"✔ {tema.archivo.name}: {tema.orden}. {tema.titulo}")
    return [t.archivo for t in temas]
