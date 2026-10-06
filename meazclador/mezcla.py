"""El 'ingeniero de mezcla' automático: junta todo y toma las decisiones."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from pedalboard import Compressor, Pedalboard, Reverb

from .afinacion import afinar
from .analisis import GRUPO_BATERIA, Pista, analizar, espectro, polaridad_invertida
from .audio import SR_TRABAJO, a_estereo, cargar, desde_db, guardar, igualar_largo, nivel_activo, rms_corto
from .dinamica import filtro_paso_alto, filtro_paso_bajo
from .master import masterizar
from .procesos import procesar_pista

# Nivel de cada instrumento respecto de la voz principal (dB). Es el "balance" de la mezcla.
BALANCE = {
    "voz": 0.0, "bombo": -1.0, "caja": -2.0, "bajo": -2.0, "guitarra": -4.0, "teclado": -6.0,
    "toms": -6.0, "overheads": -9.0, "hihat": -12.0, "coros": -8.0, "otros": -6.0,
}
NIVEL_VOZ = -24.0

# Posición estéreo (-1 izquierda, +1 derecha) según cuántas pistas hay de cada tipo.
PANEOS = {
    "guitarra": [[0.25], [-0.8, 0.8], [-0.8, 0.8, 0.0], [-0.8, 0.8, -0.5, 0.5]],
    "coros": [[0.0], [-0.5, 0.5], [-0.5, 0.5, 0.0], [-0.6, 0.6, -0.3, 0.3]],
    "teclado": [[-0.3], [-0.6, 0.6], [-0.6, 0.6, 0.0]],
    "toms": [[-0.3], [-0.3, 0.3], [-0.4, 0.0, 0.4], [-0.5, -0.2, 0.2, 0.5]],
    "hihat": [[0.3]],
}

EXTENSIONES = {".wav", ".wave", ".flac", ".aif", ".aiff"}


@dataclass
class Opciones:
    afinar: float = 0.0
    tonalidad: str | None = None
    lufs: float = -14.0
    referencia: Path | None = None


@dataclass
class Resultado:
    master: np.ndarray
    premaster: np.ndarray
    pistas: list[Pista]
    notas_generales: list[str] = field(default_factory=list)
    notas_master: list[str] = field(default_factory=list)


def _panear(audio: np.ndarray, pan: float) -> np.ndarray:
    if audio.shape[0] == 2:
        # pista estéreo: sólo se balancea, conserva su imagen
        return np.vstack([audio[0] * min(1, 1 - pan), audio[1] * min(1, 1 + pan)])
    angulo = (pan + 1) * np.pi / 4
    return np.vstack([audio[0] * np.cos(angulo), audio[0] * np.sin(angulo)]) * np.sqrt(2)


def _asignar_paneos(pistas: list[Pista]) -> None:
    por_rol: dict[str, list[Pista]] = defaultdict(list)
    for p in pistas:
        por_rol[p.rol].append(p)
    for rol, grupo in por_rol.items():
        opciones = PANEOS.get(rol)
        if not opciones:
            continue
        posiciones = opciones[min(len(grupo), len(opciones)) - 1]
        for i, p in enumerate(grupo):
            p.pan = posiciones[i % len(posiciones)]


def _fundamental_bombo(bombo: np.ndarray) -> float:
    f, p_db = espectro(bombo)
    zona = (f >= 40) & (f <= 110)
    return float(f[zona][np.argmax(p_db[zona])])


def _desenmascarar(pistas: list[Pista]) -> dict[int, list[tuple[float, float, float]]]:
    """Hace lugar entre instrumentos que pelean por las mismas frecuencias."""
    extra: dict[int, list[tuple[float, float, float]]] = defaultdict(list)
    roles = {p.rol for p in pistas}
    if "voz" in roles:
        for i, p in enumerate(pistas):
            if p.rol in ("guitarra", "teclado", "otros"):
                extra[i].append((2800, -2.0, 1.2))
                p.notas.append("Hueco de -2 dB en 2.8 kHz para que la voz se entienda por encima.")
    bombos = [p for p in pistas if p.rol == "bombo"]
    if bombos:
        hz = _fundamental_bombo(bombos[0].audio)
        for i, p in enumerate(pistas):
            if p.rol == "bajo":
                extra[i].append((hz, -2.5, 2.0))
                p.notas.append(f"Hueco de -2.5 dB en {hz:.0f} Hz (donde golpea el bombo): bombo y bajo no se pisan.")
    return extra


def _bus_bateria(señales: list[np.ndarray]) -> tuple[np.ndarray, str]:
    bus = np.sum(señales, axis=0).astype(np.float32)
    r = rms_corto(bus)
    picos = float(np.percentile(r[r > -60], 90)) if np.any(r > -60) else -20.0
    pegada = Pedalboard([Compressor(threshold_db=picos - 4, ratio=2.0, attack_ms=30, release_ms=150)])(bus, SR_TRABAJO)
    aplastada = Pedalboard([Compressor(threshold_db=picos - 18, ratio=10, attack_ms=1, release_ms=120)])(bus, SR_TRABAJO)
    aplastada *= desde_db(nivel_activo(pegada) - nivel_activo(aplastada) - 8)
    return pegada + aplastada, ("Batería: compresión de bus (2:1) + compresión paralela "
                                "(la 'fuerza' de los discos de rock sin perder dinámica).")


def _reverb(envio: np.ndarray) -> np.ndarray:
    pre = int(SR_TRABAJO * 0.025)  # 25 ms de pre-delay: la voz queda adelante
    envio = np.pad(envio, ((0, 0), (pre, 0)))[:, : envio.shape[1]]
    sala = Pedalboard([Reverb(room_size=0.5, damping=0.6, wet_level=1.0, dry_level=0.0, width=1.0)])
    ret = sala(envio.astype(np.float32), SR_TRABAJO)
    ret = filtro_paso_bajo(filtro_paso_alto(ret, 250), 7000)  # sin barro ni siseo
    if nivel_activo(ret) > -100:
        ret *= desde_db(nivel_activo(envio) - nivel_activo(ret))
    return ret


def listar_pistas(carpeta: Path) -> list[Path]:
    return sorted(p for p in carpeta.iterdir() if p.suffix.lower() in EXTENSIONES)


def mezclar(carpeta: Path, opciones: Opciones, avisar=print) -> Resultado:
    archivos = listar_pistas(carpeta)
    if not archivos:
        raise FileNotFoundError(f"No encontré archivos de audio en {carpeta}")

    avisar(f"Cargando {len(archivos)} pistas...")
    audios = igualar_largo([cargar(a) for a in archivos])
    pistas = [analizar(a.name, x) for a, x in zip(archivos, audios)]
    generales: list[str] = []

    # Fase: un micrófono en contrafase con los overheads le roba graves y pegada a la batería.
    overheads = [p for p in pistas if p.rol == "overheads"]
    if overheads:
        for p in pistas:
            if p.rol in ("bombo", "caja", "toms") and polaridad_invertida(p.audio, overheads[0].audio):
                p.audio = -p.audio
                p.notas.append("Polaridad invertida respecto de los overheads: corregida (recupera graves y pegada).")

    if opciones.afinar > 0:
        for p in pistas:
            if p.rol in ("voz", "coros"):
                avisar(f"Afinando {p.nombre}...")
                p.audio, resumen = afinar(p.audio, opciones.afinar, opciones.tonalidad)
                p.notas.append(resumen)

    extra = _desenmascarar(pistas)
    _asignar_paneos(pistas)

    cuenta = defaultdict(int)
    for p in pistas:
        cuenta[p.rol] += 1

    tiene_voz = any(p.rol == "voz" for p in pistas)
    bateria, resto = [], []
    envio = np.zeros((2, audios[0].shape[1]), dtype=np.float32)
    for i, p in enumerate(pistas):
        avisar(f"Procesando {p.nombre} ({p.rol})...")
        audio = _panear(procesar_pista(p, extra.get(i)), p.pan)
        # Varias pistas del mismo instrumento comparten el lugar en la mezcla.
        objetivo = NIVEL_VOZ + BALANCE.get(p.rol, -6.0) - 10 * np.log10(cuenta[p.rol])
        if not tiene_voz:
            objetivo += 2.0
        audio *= desde_db(objetivo - nivel_activo(audio))
        envio += a_estereo(audio) * p.envio_reverb
        (bateria if p.rol in GRUPO_BATERIA else resto).append(audio.astype(np.float32))

    partes = list(resto)
    if bateria:
        bus, nota = _bus_bateria(bateria)
        partes.append(bus)
        generales.append(nota)
    if np.any(envio):
        partes.append(_reverb(envio))
        generales.append("Reverb compartida tipo 'plate' con pre-delay de 25 ms, filtrada (250 Hz-7 kHz).")
    premaster = np.sum(partes, axis=0).astype(np.float32)

    avisar("Masterizando...")
    referencia = cargar(opciones.referencia) if opciones.referencia else None
    master, notas_master = masterizar(premaster, opciones.lufs, referencia=referencia)

    # Pre-máster con margen (-6 dBFS de pico) por si querés mandarlo a masterizar afuera.
    premaster = premaster * desde_db(-6) / (np.max(np.abs(premaster)) + 1e-12)
    return Resultado(master, premaster.astype(np.float32), pistas, generales, notas_master)


def informe(res: Resultado) -> str:
    lineas = ["INFORME DE MEZCLA", "=" * 60, ""]
    for p in res.pistas:
        pos = "centro" if abs(p.pan) < 0.05 else f"{abs(p.pan):.0%} {'izquierda' if p.pan < 0 else 'derecha'}"
        detectado = "por el nombre" if p.rol_por == "nombre" else "por cómo suena (renombrala si está mal)"
        lineas.append(f"■ {p.nombre} → {p.rol.upper()} (detectado {detectado}), paneo: {pos}")
        lineas += [f"   - {n}" for n in p.notas]
        if p.envio_reverb:
            lineas.append(f"   - Envío a reverb: {p.envio_reverb:.0%}")
        lineas.append("")
    lineas += ["MEZCLA GENERAL", "-" * 60] + [f"- {n}" for n in res.notas_generales] + [""]
    lineas += ["MASTER", "-" * 60] + [f"- {n}" for n in res.notas_master] + [""]
    return "\n".join(lineas)


def exportar(res: Resultado, destino: Path) -> list[Path]:
    destino.mkdir(parents=True, exist_ok=True)
    rutas = [destino / "master.wav", destino / "premaster.wav", destino / "informe.txt"]
    guardar(rutas[0], res.master)
    guardar(rutas[1], res.premaster)
    rutas[2].write_text(informe(res), encoding="utf-8")
    return rutas
