"""Masterización: balance tonal, pegamento, graves en mono, volumen comercial sin distorsión."""

from __future__ import annotations

import numpy as np
from scipy.signal import resample_poly
from pedalboard import BrickwallLimiter, Compressor, HighShelfFilter, LowShelfFilter, PeakFilter, Pedalboard

from .analisis import espectro
from .audio import SR_TRABAJO, desde_db, lufs, pico_real, rms_corto
from .dinamica import filtro_paso_alto, saturacion

# Bandas de media octava para comparar y corregir el balance tonal del máster (media octava
# alcanza para ver, por ejemplo, el sonido 'a caja de cartón' de 700 Hz entre 500 y 1000).
OCTAVAS = [63, 90, 125, 180, 250, 355, 500, 710, 1000, 1400, 2000, 2800, 4000, 5600, 8000, 11300, 16000]
NOMBRES_OCTAVA = {63: "sub-graves", 90: "graves", 125: "graves", 180: "cuerpo", 250: "cuerpo", 355: "barro",
                  500: "medios-graves", 710: "caja de cartón", 1000: "medios", 1400: "medios",
                  2000: "medios-altos", 2800: "medios-altos", 4000: "presencia", 5600: "presencia",
                  8000: "brillo", 11300: "aire", 16000: "aire"}
# Cuánto puede corregir como máximo cada banda (en los extremos se va con más cuidado).
MAXIMO_OCTAVA = {63: 3.0, 16000: 2.5}


def _perfil(f: np.ndarray, p_db: np.ndarray) -> np.ndarray:
    """Nivel de cada octava relativo a los medios (500 Hz-2 kHz)."""
    ref = p_db[(f >= 500) & (f < 2000)].mean()
    niveles = []
    for fc in OCTAVAS:
        sel = (f >= fc / 2 ** 0.25) & (f < fc * 2 ** 0.25)
        niveles.append(p_db[sel].mean() - ref)
    return np.array(niveles)


def perfil_objetivo(referencia: np.ndarray | None) -> tuple[np.ndarray, str]:
    if referencia is not None:
        return _perfil(*espectro(referencia)), "el tema de referencia"
    # Curva típica de discos de rock/pop modernos: cae ~4.5 dB por octava.
    f = np.linspace(20, 20000, 20000)
    return _perfil(f, -4.5 * np.log2(f / 1000)), "una curva típica de discos de rock/pop"


def balance_tonal(mezcla: np.ndarray, objetivo: np.ndarray, fuerza: float = 0.8, maximo: float = 4.0
                  ) -> tuple[list, list[str]]:
    """EQ de máster por medias octavas: lleva cada banda hacia el objetivo (sin pasarse).

    Detecta, por ejemplo, un exceso de 2-5 kHz (sonido 'latoso', de teléfono) y la falta de
    aire arriba de 6 kHz, y los corrige a la vez.
    """
    actual = _perfil(*espectro(mezcla))
    difs = fuerza * (objetivo - actual)
    filtros, notas = [], []
    for fc, dif in zip(OCTAVAS, difs):
        dif = float(np.clip(dif, -MAXIMO_OCTAVA.get(fc, maximo), MAXIMO_OCTAVA.get(fc, maximo)))
        if abs(dif) < 0.5:
            continue
        if fc == OCTAVAS[0]:
            filtros.append(LowShelfFilter(cutoff_frequency_hz=90, gain_db=dif, q=0.7))
        elif fc == OCTAVAS[-1]:
            filtros.append(HighShelfFilter(cutoff_frequency_hz=11000, gain_db=dif, q=0.7))
        else:
            filtros.append(PeakFilter(cutoff_frequency_hz=fc, gain_db=dif, q=2.0))
        notas.append(f"EQ de máster: {NOMBRES_OCTAVA[fc]} ({fc} Hz) {dif:+.1f} dB.")
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


def clipper(audio: np.ndarray, umbral_db: float = -3.0) -> np.ndarray:
    """Recorte suave de picos, sobremuestreado x4 (como saturar una cinta o un conversor analógico).

    Por debajo del umbral no toca nada; por encima redondea el pico hacia 0 dBFS. Saca los
    picos más filosos antes del limitador, así éste trabaja menos y no 'bombea'.
    """
    t = desde_db(umbral_db)
    sobre = resample_poly(audio, 4, 1, axis=1)
    mag = np.abs(sobre)
    curva = np.where(mag <= t, mag, t + (1 - t) * np.tanh((mag - t) / (1 - t)))
    return resample_poly(np.sign(sobre) * curva, 1, 4, axis=1).astype(np.float32)


def adelantar(audio: np.ndarray, presencia: float) -> np.ndarray:
    """Trae la mezcla 'adelante', como un tema de estudio.

    - Compresión paralela (estilo Nueva York): una copia muy comprimida mezclada por debajo sube
      los detalles y las colas cortas sin aplastar los golpes.
    - Un poco menos de 'caja' (400 Hz, lo que suena a habitación chica), sin adelgazar: se
      compensa con cuerpo en los graves, y el brillo va arriba (aire, 8 kHz), no en los
      medios-altos de 2-4 kHz que hacen sonar 'latoso'.
    """
    r = rms_corto(audio)
    picos = float(np.percentile(r[r > -60], 90)) if np.any(r > -60) else -20.0
    aplastada = Pedalboard([Compressor(threshold_db=picos - 15, ratio=6, attack_ms=5, release_ms=100)])(
        audio, SR_TRABAJO)
    aplastada = aplastada * desde_db(-10.0 + 3.0 * presencia)  # por debajo de la mezcla: no aplastar todo
    tono = Pedalboard([
        LowShelfFilter(cutoff_frequency_hz=120, gain_db=1.0 * presencia, q=0.7),
        PeakFilter(cutoff_frequency_hz=400, gain_db=-1.2 * presencia, q=1.2),
        HighShelfFilter(cutoff_frequency_hz=8000, gain_db=1.5 * presencia, q=0.7),
    ])
    salida = tono(audio + presencia * aplastada, SR_TRABAJO)
    return salida.astype(np.float32)


def masterizar(
    mezcla: np.ndarray, lufs_objetivo: float = -14.0, techo_db: float = -1.0, referencia: np.ndarray | None = None,
    usar_clipper: bool = False, presencia: float = 0.0,
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
    if presencia > 0:
        audio = adelantar(audio, presencia)
        notas.append(f"Presencia {presencia:.0%}: compresión paralela (sube el detalle y el cuerpo) "
                     "y menos 'caja' en los medios-graves: todo suena más cerca, menos de habitación.")

    if referencia is not None:
        lufs_objetivo = min(lufs(referencia), -7.0)
        notas.append(f"Volumen objetivo tomado de la referencia: {lufs_objetivo:.1f} LUFS.")

    # Ajuste iterativo: subir hasta el volumen pedido con el limitador cuidando los picos.
    ganancia = lufs_objetivo - lufs(audio)
    limitador = BrickwallLimiter(ceiling_db=techo_db - 0.2, release_ms=120, lookahead_ms=5, true_peak=True)
    if usar_clipper:
        notas.append("Clipper suave antes del limitador: los picos se redondean como en una cinta (sonido crudo y fuerte).")

    def cadena(g: float, con_clipper: bool) -> np.ndarray:
        x = audio * desde_db(g)
        if con_clipper:
            x = clipper(x)
        limitador.reset()
        return limitador(x, SR_TRABAJO)

    def ajustar(con_clipper: bool, g: float) -> tuple[np.ndarray, float, float]:
        salida = audio
        error = 0.0
        for _ in range(8):
            salida = cadena(g, con_clipper)
            error = lufs_objetivo - lufs(salida)
            if abs(error) < 0.2:
                break
            g += error
        return salida, g, error

    salida, ganancia_final, error = ajustar(usar_clipper, ganancia)
    if not usar_clipper and error > 0.5:
        # Picos muy filosos: el limitador solo no llega al volumen pedido. Se redondean los picos antes.
        salida, ganancia_final, error = ajustar(True, ganancia)
        notas.append("Los picos eran muy filosos para llegar al volumen sólo con el limitador: se usó un "
                     "clipper suave antes (redondea los picos como una cinta).")
    ganancia = ganancia_final

    pico = pico_real(salida)
    if pico > techo_db:
        salida = salida * desde_db(techo_db - pico - 0.05)
        pico = pico_real(salida)
    salida = fundidos(salida)
    reduccion = ganancia - (lufs(salida) - lufs(audio))
    notas.append(f"Volumen final: {lufs(salida):.1f} LUFS, pico real {pico:.1f} dBTP.")
    if reduccion > 4:
        notas.append(f"Aviso: el volumen se consigue recortando ~{reduccion:.1f} dB de picos. Si suena "
                     "aplastado, probá con un volumen final más bajo (--lufs -12 o -14).")
    return salida.astype(np.float32), notas
