"""Masterización: balance tonal, pegamento, graves en mono, volumen comercial sin distorsión."""

from __future__ import annotations

import numpy as np
from pedalboard import BrickwallLimiter, Compressor, HighShelfFilter, LowShelfFilter, PeakFilter, Pedalboard

from .analisis import espectro
from .audio import SR_TRABAJO, desde_db, lufs, pico_real, rms_corto
from .dinamica import filtro_paso_alto, saturacion

# (nombre, Hz desde, Hz hasta, filtro que corrige esa zona)
BANDAS = [
    ("graves", 40, 120, ("bajos", 110, 0.7)),
    ("barro", 200, 500, ("pico", 330, 0.9)),
    ("presencia", 2000, 5000, ("pico", 3200, 0.8)),
    ("aire", 8000, 16000, ("agudos", 10000, 0.7)),
]


def _perfil(f: np.ndarray, p_db: np.ndarray) -> dict[str, float]:
    """Nivel de cada zona relativo a los medios (500 Hz-2 kHz)."""
    ref = p_db[(f >= 500) & (f < 2000)].mean()
    return {n: float(p_db[(f >= a) & (f < b)].mean() - ref) for n, a, b, _ in BANDAS}


def perfil_objetivo(referencia: np.ndarray | None) -> tuple[dict[str, float], str]:
    if referencia is not None:
        return _perfil(*espectro(referencia)), "el tema de referencia"
    # Curva típica de discos de rock/pop modernos: cae ~4.5 dB por octava.
    f = np.linspace(20, 20000, 4000)
    return _perfil(f, -4.5 * np.log2(f / 1000)), "una curva típica de discos de rock/pop"


def balance_tonal(mezcla: np.ndarray, objetivo: dict[str, float], fuerza: float = 0.6, maximo: float = 3.0
                  ) -> tuple[list, list[str]]:
    actual = _perfil(*espectro(mezcla))
    filtros, notas = [], []
    for nombre, _, _, (tipo, hz, q) in BANDAS:
        dif = float(np.clip((objetivo[nombre] - actual[nombre]) * fuerza, -maximo, maximo))
        if abs(dif) < 0.5:
            continue
        clase = {"bajos": LowShelfFilter, "agudos": HighShelfFilter, "pico": PeakFilter}[tipo]
        filtros.append(clase(cutoff_frequency_hz=hz, gain_db=dif, q=q))
        notas.append(f"EQ de máster: {nombre} {dif:+.1f} dB (zona de {hz} Hz).")
    return filtros, notas


def graves_en_mono(audio: np.ndarray, frec: float = 120) -> np.ndarray:
    """Los graves al centro: más pegada y compatibilidad con parlantes chicos y vinilo."""
    medio = (audio[0] + audio[1]) / 2
    lado = filtro_paso_alto(((audio[0] - audio[1]) / 2)[None, :], frec)[0]
    return np.vstack([medio + lado, medio - lado]).astype(np.float32)


def fundidos(audio: np.ndarray, entrada_s: float = 0.01, salida_s: float = 1.5) -> np.ndarray:
    """Entrada sin clic y final que se apaga suave (útil en temas cortados de una sesión)."""
    audio = audio.copy()
    n_in = min(int(SR_TRABAJO * entrada_s), audio.shape[1] // 4)
    n_out = min(int(SR_TRABAJO * salida_s), audio.shape[1] // 4)
    if n_in:
        audio[:, :n_in] *= np.linspace(0, 1, n_in, dtype=np.float32)
    if n_out:
        audio[:, -n_out:] *= np.cos(np.linspace(0, np.pi / 2, n_out, dtype=np.float32)) ** 2
    return audio


def masterizar(
    mezcla: np.ndarray, lufs_objetivo: float = -14.0, techo_db: float = -1.0, referencia: np.ndarray | None = None
) -> tuple[np.ndarray, list[str]]:
    notas: list[str] = []
    audio = graves_en_mono(mezcla)
    notas.append("Graves por debajo de 120 Hz centrados (mono).")

    objetivo, origen = perfil_objetivo(referencia)
    filtros, n_eq = balance_tonal(audio, objetivo)
    notas.append(f"Balance tonal comparado con {origen}.")
    notas.extend(n_eq or ["EQ de máster: el balance ya estaba bien, no hizo falta corregir."])

    r = rms_corto(audio)
    picos = float(np.percentile(r[r > -60], 90)) if np.any(r > -60) else -20.0
    filtros.append(Compressor(threshold_db=picos - 3, ratio=1.5, attack_ms=30, release_ms=200))
    notas.append("Compresión de 'pegamento' 1.5:1: une la mezcla sin aplastarla.")
    audio = Pedalboard(filtros)(audio, SR_TRABAJO)
    audio = saturacion(audio, 0.08)

    if referencia is not None:
        lufs_objetivo = min(lufs(referencia), -7.0)
        notas.append(f"Volumen objetivo tomado de la referencia: {lufs_objetivo:.1f} LUFS.")

    # Ajuste iterativo: subir hasta el volumen pedido con el limitador cuidando los picos.
    ganancia = lufs_objetivo - lufs(audio)
    limitador = BrickwallLimiter(ceiling_db=techo_db - 0.2, release_ms=120, lookahead_ms=5, true_peak=True)
    salida = audio
    for _ in range(4):
        limitador.reset()
        salida = limitador(audio * desde_db(ganancia), SR_TRABAJO)
        error = lufs_objetivo - lufs(salida)
        if abs(error) < 0.2:
            break
        ganancia += error

    pico = pico_real(salida)
    if pico > techo_db:
        salida = salida * desde_db(techo_db - pico - 0.05)
        pico = pico_real(salida)
    salida = fundidos(salida)
    reduccion = ganancia - (lufs(salida) - lufs(audio))
    notas.append(f"Volumen final: {lufs(salida):.1f} LUFS, pico real {pico:.1f} dBTP.")
    if reduccion > 4:
        notas.append(f"Aviso: el limitador trabaja fuerte (~{reduccion:.1f} dB). Si suena aplastado, "
                     "probá con --lufs -16.")
    return salida.astype(np.float32), notas
