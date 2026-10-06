"""Afinación natural de voces.

No es un auto-tune "robot": corrige el centro de cada nota hacia la nota correcta,
pero conserva el vibrato, los deslizamientos y la expresión. Usa el vocoder WORLD,
que cambia la altura sin cambiar el timbre de la voz (los formantes).
"""

from __future__ import annotations

import numpy as np
import pyworld as pw
from scipy.ndimage import median_filter, uniform_filter1d

from .audio import SR_TRABAJO, a_mono, rms_corto

NOTAS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11,
         "DO": 0, "RE": 2, "MI": 4, "FA": 5, "SOL": 7, "LA": 9, "SI": 11}
MAYOR = [0, 2, 4, 5, 7, 9, 11]
MENOR = [0, 2, 3, 5, 7, 8, 10]
PERIODO_MS = 5.0


def escala(tonalidad: str | None) -> list[int] | None:
    """'Am', 'F#', 'La menor', 'Sol mayor', 'Bb' -> clases de nota permitidas. None = cromática."""
    if not tonalidad:
        return None
    t = tonalidad.strip().upper().replace("♯", "#").replace("♭", "B")
    partes = t.split()
    raiz_txt = partes[0]
    menor = "MENOR" in partes or "MINOR" in partes
    if not menor and raiz_txt.endswith("M") and len(raiz_txt) > 1:
        raiz_txt, menor = raiz_txt[:-1], True
    alteracion = 0
    if raiz_txt.endswith("#"):
        raiz_txt, alteracion = raiz_txt[:-1], 1
    elif len(raiz_txt) > 1 and raiz_txt.endswith("B") and raiz_txt[:-1] in NOTAS:
        raiz_txt, alteracion = raiz_txt[:-1], -1
    if raiz_txt not in NOTAS:
        raise ValueError(f"No entiendo la tonalidad '{tonalidad}'. Ejemplos: Am, F#, 'La menor', 'Sol mayor'.")
    raiz = (NOTAS[raiz_txt] + alteracion) % 12
    return [(raiz + i) % 12 for i in (MENOR if menor else MAYOR)]


def _nota_mas_cercana(midi: np.ndarray, permitidas: list[int] | None) -> np.ndarray:
    if permitidas is None:
        return np.round(midi)
    candidatos = np.arange(0, 128)
    candidatos = candidatos[np.isin(candidatos % 12, permitidas)]
    idx = np.abs(midi[:, None] - candidatos[None, :]).argmin(axis=1)
    return candidatos[idx].astype(float)


def _regiones(mono: np.ndarray, sr: int, max_seg: float = 12.0) -> list[tuple[int, int]]:
    """Frases donde la voz suena, para procesar por partes (menos memoria, más rápido)."""
    ventana = int(sr * 0.05)
    r = rms_corto(mono[None, :], sr, 50)
    activo = uniform_filter1d((r > -45).astype(float), 6) > 0
    regiones, inicio = [], None
    for i, a in enumerate(np.append(activo, False)):
        if a and inicio is None:
            inicio = i
        elif not a and inicio is not None:
            a0, a1 = max(0, (inicio - 2) * ventana), min(len(mono), (i + 2) * ventana)
            paso = int(max_seg * sr)
            for s in range(a0, a1, paso):
                regiones.append((s, min(a1, s + paso)))
            inicio = None
    return regiones


def _afinar_region(x: np.ndarray, sr: int, fuerza: float, permitidas: list[int] | None) -> tuple[np.ndarray, list[float]]:
    f0, t = pw.dio(x, sr, f0_floor=65, f0_ceil=1100, frame_period=PERIODO_MS)
    f0 = pw.stonemask(x, f0, t, sr)
    sonoro = f0 > 0
    if sonoro.sum() < 10:
        return x, []
    midi = np.zeros_like(f0)
    midi[sonoro] = 69 + 12 * np.log2(f0[sonoro] / 440)

    # El "centro" de la nota ignora el vibrato (mediana de ~300 ms, más de un ciclo).
    centro = midi.copy()
    centro[sonoro] = median_filter(midi[sonoro], size=61, mode="nearest")
    objetivo = _nota_mas_cercana(centro[sonoro], permitidas)
    desvio = np.zeros_like(f0)
    desvio[sonoro] = objetivo - centro[sonoro]
    desvio[np.abs(desvio) < 0.1] = 0  # menos de 10 cents: se deja como está
    desvio = uniform_filter1d(desvio, size=24) * sonoro  # transiciones de ~120 ms
    if not np.any(np.abs(desvio) > 0.05):
        return x, []

    f0_nuevo = f0 * 2 ** (fuerza * desvio / 12)
    sp = pw.cheaptrick(x, f0, t, sr)
    ap = pw.d4c(x, f0, t, sr)
    y = pw.synthesize(f0_nuevo, sp, ap, sr, frame_period=PERIODO_MS)[: len(x)]
    y = np.pad(y, (0, len(x) - len(y)))

    # Sólo se reemplaza donde hubo corrección: consonantes y respiraciones quedan originales.
    usa = uniform_filter1d((np.abs(desvio) > 0.05).astype(float), size=6)
    curva = np.interp(np.arange(len(x)), t * sr, usa)
    return (1 - curva) * x + curva * y, list(np.abs(desvio[desvio != 0]) * 100)


def afinar(audio: np.ndarray, fuerza: float = 0.6, tonalidad: str | None = None, sr: int = SR_TRABAJO
           ) -> tuple[np.ndarray, str]:
    """fuerza 0..1 (0 = nada, 1 = al centro exacto de la nota). Devuelve (audio, resumen)."""
    permitidas = escala(tonalidad)
    mono = a_mono(audio).astype(np.float64)
    salida = mono.copy()
    cents: list[float] = []
    for a, b in _regiones(mono, sr):
        tramo, c = _afinar_region(np.ascontiguousarray(mono[a:b]), sr, fuerza, permitidas)
        salida[a:b] = tramo
        cents.extend(c)
    if audio.shape[0] == 2:
        # conserva la imagen estéreo original sumando la corrección a ambos canales
        resultado = audio + (salida - mono)[None, :].astype(np.float32)
    else:
        resultado = salida[None, :].astype(np.float32)
    if cents:
        resumen = (f"Afinación natural (fuerza {fuerza:.0%}): desafinación media {np.mean(cents):.0f} cents, "
                   f"máxima {np.max(cents):.0f} cents. Vibrato y expresión conservados.")
    else:
        resumen = "Afinación: la voz ya estaba afinada, no se tocó."
    return resultado.astype(np.float32), resumen
