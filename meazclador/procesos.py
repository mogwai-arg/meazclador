"""Cadena de procesamiento por instrumento: limpieza, ecualización y compresión.

Cada pista llega ya nivelada a -18 dBFS RMS (en sus partes activas), así los umbrales
de compresión son comparables entre pistas y entre canciones.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from pedalboard import (
    Compressor,
    HighpassFilter,
    HighShelfFilter,
    LowpassFilter,
    PeakFilter,
    Pedalboard,
)

from .analisis import Pista
from .audio import SR_TRABAJO, desde_db, nivel_activo, rms_corto
from .dinamica import de_esser, expansor, saturacion

NIVEL_TRABAJO_DB = -18.0


@dataclass
class Receta:
    """Decisiones de mezcla típicas para un instrumento (punto de partida de un ingeniero)."""

    paso_alto: float
    paso_bajo: float | None = None
    eq: list[tuple[str, float, float, float]] = field(default_factory=list)  # (tipo, Hz, dB, Q)
    compresion: list[tuple[float, float, float, float]] = field(default_factory=list)  # (dB bajo picos, ratio, at, rel)
    de_esser: bool = False
    expansor: bool = False
    saturacion: float = 0.0
    reverb: float = 0.0


RECETAS: dict[str, Receta] = {
    "bombo": Receta(
        paso_alto=30,
        eq=[("pico", 60, 2.0, 1.0), ("pico", 380, -4.0, 1.4), ("pico", 4000, 3.0, 1.0)],
        compresion=[(6, 4.0, 15, 90)],
        expansor=True,
        saturacion=0.15,
    ),
    "caja": Receta(
        paso_alto=80,
        eq=[("pico", 200, 2.0, 1.2), ("pico", 900, -2.5, 1.5), ("agudos", 6000, 2.5, 0.7)],
        compresion=[(6, 4.0, 8, 120)],
        saturacion=0.15,
        reverb=0.16,
    ),
    "hihat": Receta(paso_alto=300, eq=[("pico", 600, -2.0, 1.0), ("agudos", 10000, 1.5, 0.7)], compresion=[(4, 2.0, 5, 80)]),
    "toms": Receta(
        paso_alto=60,
        eq=[("pico", 100, 2.0, 1.0), ("pico", 450, -4.0, 1.2), ("pico", 4000, 2.0, 1.0)],
        compresion=[(6, 4.0, 10, 150)],
        expansor=True,
        reverb=0.10,
    ),
    "overheads": Receta(
        paso_alto=120,
        eq=[("pico", 400, -2.5, 1.0), ("agudos", 10000, 2.0, 0.7)],
        compresion=[(4, 2.0, 20, 200)],
        reverb=0.05,
    ),
    "bajo": Receta(
        paso_alto=35,
        paso_bajo=9000,
        eq=[("pico", 250, -2.5, 1.2), ("pico", 800, 2.0, 1.2)],
        compresion=[(8, 4.0, 20, 160), (4, 2.0, 5, 80)],
        saturacion=0.3,
    ),
    "guitarra": Receta(
        paso_alto=90,
        paso_bajo=12000,
        eq=[("pico", 300, -2.5, 1.0), ("pico", 3000, 1.0, 1.0)],
        compresion=[(5, 2.5, 20, 150)],
        reverb=0.08,
    ),
    "teclado": Receta(
        paso_alto=70,
        eq=[("pico", 300, -2.0, 1.0)],
        compresion=[(4, 2.0, 20, 200)],
        reverb=0.10,
    ),
    "voz": Receta(
        paso_alto=85,
        eq=[("pico", 250, -2.5, 1.0), ("pico", 3000, 2.0, 0.9), ("agudos", 10000, 2.5, 0.7)],
        compresion=[(8, 3.0, 8, 90), (4, 2.0, 2, 60)],
        de_esser=True,
        saturacion=0.1,
        reverb=0.18,
    ),
    "coros": Receta(
        paso_alto=150,
        eq=[("pico", 300, -3.5, 1.0), ("agudos", 10000, 2.0, 0.7)],
        compresion=[(10, 4.0, 5, 100)],
        de_esser=True,
        reverb=0.28,
    ),
    "otros": Receta(paso_alto=40, eq=[("pico", 300, -1.5, 1.0)], compresion=[(4, 2.0, 20, 150)], reverb=0.08),
}


def nivelar(audio: np.ndarray, objetivo_db: float = NIVEL_TRABAJO_DB) -> tuple[np.ndarray, float]:
    ganancia_db = objetivo_db - nivel_activo(audio)
    return (audio * desde_db(ganancia_db)).astype(np.float32), ganancia_db


def _nivel_picos(audio: np.ndarray) -> float:
    """Nivel de las partes fuertes (percentil 90 del RMS corto activo)."""
    r = rms_corto(audio)
    activos = r[r > -50]
    return float(np.percentile(activos, 90)) if len(activos) else NIVEL_TRABAJO_DB


def procesar_pista(pista: Pista, recortes_extra: list[tuple[float, float, float]] | None = None) -> np.ndarray:
    """Aplica la receta del instrumento + correcciones detectadas. Anota todo en pista.notas."""
    receta = RECETAS.get(pista.rol, RECETAS["otros"])
    audio, g = nivelar(pista.audio)
    pista.notas.append(f"Nivel de entrada ajustado {g:+.1f} dB para trabajar con margen.")

    if receta.expansor:
        audio = expansor(audio)
        pista.notas.append("Expansor suave: baja el sonido de otros tambores que se cuela en este micrófono.")

    filtros = [HighpassFilter(cutoff_frequency_hz=receta.paso_alto)]
    pista.notas.append(f"Filtro paso alto en {receta.paso_alto:.0f} Hz: quita retumbe y graves inútiles.")
    if receta.paso_bajo:
        filtros.append(LowpassFilter(cutoff_frequency_hz=receta.paso_bajo))

    # Primero cortar lo que molesta (resonancias), después dar color.
    for hz, exceso in pista.resonancias:
        corte = -min(exceso * 0.5, 4.0)
        filtros.append(PeakFilter(cutoff_frequency_hz=hz, gain_db=corte, q=5.0))
        pista.notas.append(f"Resonancia en {hz:.0f} Hz ({exceso:.1f} dB de más): recorte estrecho de {corte:.1f} dB.")

    for tipo, hz, ganancia, q in receta.eq:
        if tipo == "agudos":
            filtros.append(HighShelfFilter(cutoff_frequency_hz=hz, gain_db=ganancia, q=q))
        else:
            filtros.append(PeakFilter(cutoff_frequency_hz=hz, gain_db=ganancia, q=q))

    for hz, ganancia, q in recortes_extra or []:
        filtros.append(PeakFilter(cutoff_frequency_hz=hz, gain_db=ganancia, q=q))

    audio = Pedalboard(filtros)(audio, SR_TRABAJO)

    for i, (debajo, ratio, ataque, liberacion) in enumerate(receta.compresion):
        umbral = _nivel_picos(audio) - debajo
        audio = Pedalboard(
            [Compressor(threshold_db=umbral, ratio=ratio, attack_ms=ataque, release_ms=liberacion)]
        )(audio, SR_TRABAJO)
        etapa = "Compresión" if i == 0 else "Segunda compresión (más rápida, controla picos)"
        pista.notas.append(f"{etapa}: {ratio:.1f}:1 desde {umbral:.1f} dBFS, ataque {ataque:.0f} ms.")

    if receta.de_esser:
        audio, red = de_esser(audio)
        if red > 0:
            pista.notas.append(f"De-esser: suaviza las 'eses' ({red:.1f} dB de reducción media cuando actúa).")

    if receta.saturacion:
        audio = saturacion(audio, receta.saturacion)
        pista.notas.append("Saturación suave: más cuerpo y presencia sin subir el volumen.")

    pista.envio_reverb = receta.reverb
    audio, _ = nivelar(audio)
    return audio
