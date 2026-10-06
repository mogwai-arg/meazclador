"""Carga, guardado y utilidades de nivel de audio."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from scipy.signal import resample_poly

SR_TRABAJO = 48000


def cargar(ruta: Path, sr_destino: int = SR_TRABAJO) -> np.ndarray:
    """Lee un WAV y lo devuelve como float32 (canales, muestras) a sr_destino."""
    datos, sr = sf.read(str(ruta), dtype="float32", always_2d=True)
    datos = datos.T  # (canales, muestras)
    if datos.shape[0] > 2:
        datos = datos[:2]
    if sr != sr_destino:
        f = Fraction(sr_destino, sr).limit_denominator(1000)
        datos = resample_poly(datos, f.numerator, f.denominator, axis=1).astype(np.float32)
    return np.ascontiguousarray(datos)


def guardar(ruta: Path, audio: np.ndarray, sr: int = SR_TRABAJO, bits: int = 24) -> None:
    subtipo = {16: "PCM_16", 24: "PCM_24", 32: "FLOAT"}[bits]
    sf.write(str(ruta), audio.T, sr, subtype=subtipo)


def igualar_largo(pistas: list[np.ndarray]) -> list[np.ndarray]:
    n = max(p.shape[1] for p in pistas)
    return [np.pad(p, ((0, 0), (0, n - p.shape[1]))) for p in pistas]


def a_estereo(audio: np.ndarray) -> np.ndarray:
    return np.vstack([audio, audio]) if audio.shape[0] == 1 else audio


def a_mono(audio: np.ndarray) -> np.ndarray:
    return audio.mean(axis=0)


def db(x: float | np.ndarray) -> float | np.ndarray:
    return 20 * np.log10(np.maximum(np.abs(x), 1e-12))


def desde_db(d: float) -> float:
    return float(10 ** (d / 20))


def rms_corto(audio: np.ndarray, sr: int = SR_TRABAJO, ventana_ms: float = 50) -> np.ndarray:
    """RMS en ventanas cortas (dBFS), sobre la mezcla mono de la pista."""
    mono = a_mono(audio)
    n = max(1, int(sr * ventana_ms / 1000))
    bloques = len(mono) // n
    if bloques == 0:
        return np.array([db(np.sqrt(np.mean(mono**2)) + 1e-12)])
    trozos = mono[: bloques * n].reshape(bloques, n)
    return db(np.sqrt(np.mean(trozos**2, axis=1)))


def nivel_activo(audio: np.ndarray, sr: int = SR_TRABAJO, umbral_db: float = -50) -> float:
    """RMS (dBFS) sólo de los fragmentos donde la pista suena (ignora silencios)."""
    r = rms_corto(audio, sr)
    activos = r[r > umbral_db]
    if len(activos) == 0:
        return float(np.max(r))
    return float(db(np.sqrt(np.mean(desde_db_arr(activos) ** 2))))


def desde_db_arr(d: np.ndarray) -> np.ndarray:
    return 10 ** (d / 20)


def lufs(audio: np.ndarray, sr: int = SR_TRABAJO) -> float:
    medidor = pyln.Meter(sr)
    valor = medidor.integrated_loudness(a_estereo(audio).T.astype(np.float64))
    return float(valor) if np.isfinite(valor) else -70.0


def pico_real(audio: np.ndarray) -> float:
    """True peak aproximado (dBTP) con sobremuestreo x4."""
    sobre = resample_poly(audio, 4, 1, axis=1)
    return float(db(np.max(np.abs(sobre))))
