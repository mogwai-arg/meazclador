"""El 'ingeniero de mezcla' automático: junta todo y toma las decisiones."""

from __future__ import annotations

from collections import defaultdict
import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf
from pedalboard import Compressor, Pedalboard, Reverb

from .afinacion import afinar
from .analisis import GRUPO_BATERIA, Pista, analizar, elegir_voz_principal, espectro, polaridad_invertida
from .audio import SR_TRABAJO, Cancelado, a_estereo, cargar, desde_db, guardar, igualar_largo, nivel_activo, rms_corto
from .dinamica import filtro_paso_alto, filtro_paso_bajo
from .master import masterizar
from .procesos import RECETAS, RECETAS_PUNK, procesar_pista

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
class Estilo:
    nombre: str
    descripcion: str
    recetas: dict
    balance: dict[str, float]  # cambios sobre BALANCE (dB)
    afinar: float  # fuerza por defecto
    tolerancia_cents: float  # notas más cerca que esto no se tocan
    lufs: float
    paralela_db: float  # nivel de la compresión paralela de batería respecto del bus
    sala: float  # tamaño de la reverb
    clipper: bool = False  # recorte suave antes del limitador en el máster
    presencia: float = 0.3  # 0..1: cuánto adelanta el máster (compresión paralela + medios-agudos)


ESTILOS = {
    "natural": Estilo(
        "natural", "Mezcla limpia y equilibrada, sin color de género.",
        RECETAS, {}, afinar=0.0, tolerancia_cents=10, lufs=-14.0, paralela_db=-8, sala=0.5, presencia=0.3,
    ),
    "punk": Estilo(
        "punk", "Crudo y al frente, estilo Ramones: pared de guitarras con ampli saturado, bajo con "
        "gruñido, batería reforzada con samples, voz con eco corto y sólo las notas muy desafinadas corregidas.",
        RECETAS_PUNK,
        {"voz": +1.5, "guitarra": +1.0, "bajo": +1.0, "caja": +1.0, "coros": +2.0, "overheads": -3.0},
        afinar=0.85, tolerancia_cents=35, lufs=-10.0, paralela_db=-4, sala=0.25, clipper=True, presencia=0.6,
    ),
}


@dataclass
class Opciones:
    afinar: float | None = None  # None = lo que diga el estilo
    tonalidad: str | None = None
    lufs: float | None = None  # None = lo que diga el estilo
    referencia: Path | None = None
    estilo: str = "natural"
    sample_bombo: Path | None = None
    sample_caja: Path | None = None
    guitarras: str = "auto"  # "auto", "directas" (por línea, DI) o "amplificadas" (ampli microfoneado)


# Grupos que se pueden subir o bajar después de mezclar.
GRUPOS_RETOQUE = {
    "voz": ("voz",),
    "coros": ("coros",),
    "guitarras": ("guitarra", "teclado"),
    "bajo": ("bajo",),
    "bateria": ("bombo", "caja", "hihat", "toms", "overheads"),
    "otros": ("otros",),
}


@dataclass
class Retoques:
    """Ajustes finos que se aplican sobre una mezcla ya hecha, sin volver a procesar las pistas."""

    voz: float = 0.0  # dB
    coros: float = 0.0
    guitarras: float = 0.0
    bajo: float = 0.0
    bateria: float = 0.0
    otros: float = 0.0
    reverb: float = 1.0  # 0 = nada, 1 = lo que eligió el estilo, 2 = el doble
    presencia: float | None = None  # 0..1; None = lo que diga el estilo
    lufs: float | None = None  # None = lo que diga el estilo (u opciones)

    def db(self, rol: str) -> float:
        for grupo, roles in GRUPOS_RETOQUE.items():
            if rol in roles:
                return float(getattr(self, grupo))
        return 0.0

    def resumen(self) -> str:
        partes = [f"{g} {getattr(self, g):+.1f} dB" for g in GRUPOS_RETOQUE if getattr(self, g)]
        if self.reverb != 1.0:
            partes.append(f"reverb {self.reverb:.0%}")
        if self.presencia is not None:
            partes.append(f"presencia {self.presencia:.0%}")
        if self.lufs is not None:
            partes.append(f"volumen {self.lufs:.0f} LUFS")
        return ", ".join(partes) if partes else "sin retoques"

    def guardar(self, ruta: Path) -> None:
        ruta.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def cargar(cls, ruta: Path) -> Retoques:
        if not ruta.is_file():
            return cls()
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        return cls(**{k: v for k, v in datos.items() if k in cls.__dataclass_fields__})


@dataclass
class Proyecto:
    """Pistas ya procesadas (limpias, ecualizadas, comprimidas) listas para combinar."""

    pistas: list[Pista]
    estilo: str
    lufs: float | None
    referencia: Path | None
    notas: list[str] = field(default_factory=list)


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


def _bus_bateria(señales: list[np.ndarray], paralela_db: float = -8) -> tuple[np.ndarray, str]:
    bus = np.sum(señales, axis=0).astype(np.float32)
    r = rms_corto(bus)
    picos = float(np.percentile(r[r > -60], 90)) if np.any(r > -60) else -20.0
    pegada = Pedalboard([Compressor(threshold_db=picos - 4, ratio=2.0, attack_ms=30, release_ms=150)])(bus, SR_TRABAJO)
    aplastada = Pedalboard([Compressor(threshold_db=picos - 18, ratio=10, attack_ms=1, release_ms=120)])(bus, SR_TRABAJO)
    aplastada *= desde_db(nivel_activo(pegada) - nivel_activo(aplastada) + paralela_db)
    return pegada + aplastada, ("Batería: compresión de bus (2:1) + compresión paralela "
                                "(la 'fuerza' de los discos de rock sin perder dinámica).")


def _reverb(envio: np.ndarray, sala: float = 0.5) -> np.ndarray:
    pre = int(SR_TRABAJO * 0.025)  # 25 ms de pre-delay: la voz queda adelante
    envio = np.pad(envio, ((0, 0), (pre, 0)))[:, : envio.shape[1]]
    sala = Pedalboard([Reverb(room_size=sala, damping=0.6, wet_level=1.0, dry_level=0.0, width=1.0)])
    ret = sala(envio.astype(np.float32), SR_TRABAJO)
    ret = filtro_paso_bajo(filtro_paso_alto(ret, 250), 7000)  # sin barro ni siseo
    if nivel_activo(ret) > -100:
        ret *= desde_db(nivel_activo(envio) - nivel_activo(ret))
    return ret


def listar_pistas(carpeta: Path) -> list[Path]:
    return sorted(p for p in carpeta.iterdir() if p.suffix.lower() in EXTENSIONES)


def procesar(carpeta: Path, opciones: Opciones, avisar=print, cancelar=lambda: False) -> Proyecto:
    """La parte lenta: analiza, afina y procesa cada pista. El resultado se puede guardar y retocar."""
    archivos = listar_pistas(carpeta)
    if not archivos:
        raise FileNotFoundError(f"No encontré archivos de audio en {carpeta}")

    if opciones.estilo not in ESTILOS:
        raise ValueError(f"Estilo desconocido '{opciones.estilo}'. Opciones: {', '.join(ESTILOS)}")
    estilo = ESTILOS[opciones.estilo]
    fuerza = estilo.afinar if opciones.afinar is None else opciones.afinar
    samples = {"bombo": opciones.sample_bombo, "caja": opciones.sample_caja}

    avisar(f"Cargando {len(archivos)} pistas...")
    audios = igualar_largo([cargar(a) for a in archivos])
    pistas = [analizar(a.name, x) for a, x in zip(archivos, audios)]
    notas: list[str] = []
    cambio = elegir_voz_principal(pistas)
    if cambio:
        avisar(cambio)
        notas.append(cambio)

    # Fase: un micrófono en contrafase con los overheads le roba graves y pegada a la batería.
    overheads = [p for p in pistas if p.rol == "overheads"]
    if overheads:
        for p in pistas:
            if p.rol in ("bombo", "caja", "toms") and polaridad_invertida(p.audio, overheads[0].audio):
                p.audio = -p.audio
                p.notas.append("Polaridad invertida respecto de los overheads: corregida (recupera graves y pegada).")

    if fuerza > 0:
        for p in pistas:
            if p.rol in ("voz", "coros"):
                if cancelar():
                    raise Cancelado()
                avisar(f"Afinando {p.nombre}...")
                p.audio, resumen = afinar(p.audio, fuerza, opciones.tonalidad,
                                          tolerancia_cents=estilo.tolerancia_cents)
                p.notas.append(resumen)

    extra = _desenmascarar(pistas)
    _asignar_paneos(pistas)
    for i, p in enumerate(pistas):
        if cancelar():
            raise Cancelado()
        avisar(f"Procesando {p.nombre} ({p.rol})...")
        p.audio = procesar_pista(p, extra.get(i), estilo.recetas, samples, opciones.guitarras)
    return Proyecto(pistas, opciones.estilo, opciones.lufs, opciones.referencia, notas)


def combinar(proyecto: Proyecto, retoques: Retoques | None = None, avisar=print) -> Resultado:
    """La parte rápida: balance, paneo, buses, reverb y máster. Es lo que se rehace al retocar."""
    retoques = retoques or Retoques()
    estilo = ESTILOS[proyecto.estilo]
    pistas = proyecto.pistas
    generales: list[str] = [f"Estilo {estilo.nombre}: {estilo.descripcion}"] + proyecto.notas
    if retoques.resumen() != "sin retoques":
        generales.append(f"Retoques: {retoques.resumen()}.")

    cuenta: dict[str, int] = defaultdict(int)
    for p in pistas:
        cuenta[p.rol] += 1
    tiene_voz = any(p.rol == "voz" for p in pistas)
    largo = max(p.audio.shape[1] for p in pistas)
    bateria, resto = [], []
    envio = np.zeros((2, largo), dtype=np.float32)
    for p in pistas:
        audio = _panear(p.audio, p.pan)
        # Varias pistas del mismo instrumento comparten el lugar en la mezcla.
        objetivo = (NIVEL_VOZ + BALANCE.get(p.rol, -6.0) + estilo.balance.get(p.rol, 0.0)
                    - 10 * np.log10(cuenta[p.rol]) + retoques.db(p.rol))
        if not tiene_voz:
            objetivo += 2.0
        audio = (audio * desde_db(objetivo - nivel_activo(audio))).astype(np.float32)
        envio += a_estereo(audio) * p.envio_reverb * retoques.reverb
        (bateria if p.rol in GRUPO_BATERIA else resto).append(audio)

    partes = list(resto)
    if bateria:
        bus, nota = _bus_bateria(bateria, estilo.paralela_db)
        partes.append(bus)
        generales.append(nota)
    if np.any(envio):
        partes.append(_reverb(envio, estilo.sala))
        generales.append("Reverb compartida tipo 'plate' con pre-delay de 25 ms, filtrada (250 Hz-7 kHz).")
    premaster = np.sum(partes, axis=0).astype(np.float32)

    avisar("Masterizando...")
    lufs_final = next(v for v in (retoques.lufs, proyecto.lufs, estilo.lufs) if v is not None)
    presencia = estilo.presencia if retoques.presencia is None else retoques.presencia
    referencia = cargar(proyecto.referencia) if proyecto.referencia else None
    master, notas_master = masterizar(premaster, lufs_final, referencia=referencia, usar_clipper=estilo.clipper,
                                      presencia=presencia)

    # Pre-máster con margen (-6 dBFS de pico) por si querés mandarlo a masterizar afuera.
    premaster = premaster * desde_db(-6) / (np.max(np.abs(premaster)) + 1e-12)
    return Resultado(master, premaster.astype(np.float32), pistas, generales, notas_master)


def mezclar(carpeta: Path, opciones: Opciones, avisar=print, retoques: Retoques | None = None,
            cancelar=lambda: False) -> Resultado:
    return combinar(procesar(carpeta, opciones, avisar, cancelar), retoques, avisar)


# ---------------------------------------------------------------- caché para retocar

CARPETA_PISTAS = "pistas_procesadas"
ARCHIVO_PROYECTO = "proyecto.json"
ARCHIVO_RETOQUES = "retoques.json"
MARGEN_GUARDADO_DB = -12.0  # las pistas procesadas pueden pasar 0 dBFS: se guardan con margen


def guardar_proyecto(proyecto: Proyecto, destino: Path) -> None:
    """Guarda las pistas procesadas (FLAC 24 bits) para poder retocar la mezcla en segundos."""
    carpeta = destino / CARPETA_PISTAS
    carpeta.mkdir(parents=True, exist_ok=True)
    datos = {"version": 1, "estilo": proyecto.estilo, "lufs": proyecto.lufs,
             "referencia": str(proyecto.referencia) if proyecto.referencia else None,
             "notas": proyecto.notas, "pistas": []}
    for i, p in enumerate(proyecto.pistas):
        archivo = f"{i:02d}_{Path(p.nombre).stem}.flac"
        sf.write(str(carpeta / archivo), (p.audio * desde_db(MARGEN_GUARDADO_DB)).T, SR_TRABAJO, subtype="PCM_24")
        datos["pistas"].append({"archivo": archivo, "nombre": p.nombre, "rol": p.rol, "rol_por": p.rol_por,
                                "pan": p.pan, "envio_reverb": p.envio_reverb, "notas": p.notas})
    (destino / ARCHIVO_PROYECTO).write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")


def cargar_proyecto(destino: Path) -> Proyecto:
    ruta = destino / ARCHIVO_PROYECTO
    if not ruta.is_file():
        raise FileNotFoundError(f"No hay una mezcla para retocar en {destino}. Mezclá el tema primero.")
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    pistas = []
    for d in datos["pistas"]:
        audio, _ = sf.read(str(destino / CARPETA_PISTAS / d["archivo"]), dtype="float32", always_2d=True)
        pistas.append(Pista(nombre=d["nombre"], audio=audio.T * desde_db(-MARGEN_GUARDADO_DB), rol=d["rol"],
                            rol_por=d["rol_por"], notas=d["notas"], pan=d["pan"], envio_reverb=d["envio_reverb"]))
    referencia = Path(datos["referencia"]) if datos.get("referencia") else None
    return Proyecto(pistas, datos["estilo"], datos.get("lufs"), referencia, datos.get("notas", []))


def mezclar_y_guardar(carpeta: Path, opciones: Opciones, destino: Path, avisar=print,
                      cancelar=lambda: False) -> list[Path]:
    """Mezcla un tema, guarda las pistas procesadas y aplica los retoques que ya existieran."""
    proyecto = procesar(carpeta, opciones, avisar, cancelar)
    destino.mkdir(parents=True, exist_ok=True)
    guardar_proyecto(proyecto, destino)
    retoques = Retoques.cargar(destino / ARCHIVO_RETOQUES)
    return exportar(combinar(proyecto, retoques, avisar), destino)


def retocar(destino: Path, retoques: Retoques, avisar=print) -> list[Path]:
    """Rehace balance, reverb y máster con los retoques nuevos (segundos, no minutos).

    La versión anterior queda como master_anterior.wav para comparar.
    """
    avisar("Cargando la mezcla guardada...")
    proyecto = cargar_proyecto(destino)
    if (destino / "master.wav").is_file():
        shutil.copyfile(destino / "master.wav", destino / "master_anterior.wav")
    retoques.guardar(destino / ARCHIVO_RETOQUES)
    return exportar(combinar(proyecto, retoques, avisar), destino)


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
