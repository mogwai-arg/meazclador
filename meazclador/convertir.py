"""Pasar los masters (WAV) a MP3 con las etiquetas del disco: título, número de tema, disco y artista."""

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
    wav: Path
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


def titulo_y_orden(nombre: str) -> tuple[str, int | None]:
    """'03_Help' -> ('Help', 3); 'Twist and shout' -> ('Twist and shout', None)."""
    m = _NUMERO.match(nombre)
    numero, resto = (int(m.group(1)), m.group(2)) if m and m.group(2).strip() else (None, nombre)
    titulo = re.sub(r"\s+", " ", resto.replace("_", " ")).strip()
    return titulo or nombre, numero


def temas_de(wavs: list[Path]) -> list[Tema]:
    """Título y número de orden sacados del nombre de cada archivo (o de su lugar en la lista)."""
    temas = []
    for i, wav in enumerate(wavs, 1):
        titulo, numero = titulo_y_orden(wav.stem)
        temas.append(Tema(wav, numero or i, titulo))
    return temas


def etiquetar(mp3: Path, titulo: str, orden: int, total: int, disco: str = "", artista: str = "") -> None:
    from mutagen.id3 import ID3, TALB, TIT2, TPE1, TPE2, TRCK

    etiquetas = ID3()
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
        avisar(f"=== {tema.wav.name} ({i}/{len(temas)}) ===")
        mp3 = destino / (tema.wav.stem + ".mp3")
        a_mp3(tema.wav, mp3, kbps, cancelar)
        etiquetar(mp3, tema.titulo, tema.orden, max(total, len(temas)), disco, artista)
        mb = mp3.stat().st_size / 1e6
        avisar(f"✔ {mp3}  ({mb:.1f} MB)")
        hechos.append(mp3)
    return hechos
