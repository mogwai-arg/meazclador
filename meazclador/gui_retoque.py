"""Pestaña 3 de la ventana: retocar una mezcla ya hecha y escucharla (antes y después)."""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import soundfile as sf

from .analisis import ROLES_VOZ
from .mezcla import ARCHIVO_PROYECTO, ARCHIVO_RETOQUES, ESTILOS, Retoques
from .reproductor import Reproductor
from .sesion import a_reloj, de_reloj

ESCUCHA_S = 30
CONTROLES_DB = [("voz", "Voz"), ("coros", "Coros"), ("guitarras", "Guitarras"), ("bajo", "Bajo"),
                ("bateria", "Batería")]


def mezclas_en(carpeta: Path) -> dict[str, Path]:
    """Temas con una mezcla retocable: {nombre: carpeta 'mezcla'}."""
    if (carpeta / "mezcla" / ARCHIVO_PROYECTO).is_file():
        return {carpeta.name: carpeta / "mezcla"}
    if (carpeta / ARCHIVO_PROYECTO).is_file():
        return {carpeta.parent.name: carpeta}
    return {d.name: d / "mezcla" for d in sorted(carpeta.iterdir())
            if d.is_dir() and (d / "mezcla" / ARCHIVO_PROYECTO).is_file()} if carpeta.is_dir() else {}


class PanelRetoque(ttk.Frame):
    def __init__(self, padre, app):
        super().__init__(padre, padding=10)
        self.app = app
        self.reproductor = Reproductor()
        self.mezclas: dict[str, Path] = {}
        self.columnconfigure(1, weight=1)

        ttk.Label(self, wraplength=700, justify="left", text=(
            "Después de mezclar, ajustá acá lo que no te convence y tocá 'Aplicar'. No se vuelven a "
            "procesar las pistas, así que tarda segundos. Escuchá el antes y el después desde el mismo punto."
        )).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        self.carpeta = tk.StringVar()
        app._fila_carpeta(self, 1, "Carpeta (tema o 'temas'):", self.carpeta)
        self.carpeta.trace_add("write", lambda *_: self.after(50, self.buscar_mezclas))

        ttk.Label(self, text="Tema:").grid(row=2, column=0, sticky="w", pady=4)
        self.tema = tk.StringVar()
        self.combo_tema = ttk.Combobox(self, textvariable=self.tema, state="readonly")
        self.combo_tema.grid(row=2, column=1, sticky="ew", padx=6)
        self.combo_tema.bind("<<ComboboxSelected>>", lambda _: self.cargar_retoques())

        controles = ttk.LabelFrame(self, text="Niveles (dB respecto de la mezcla automática)", padding=8)
        controles.grid(row=3, column=0, columnspan=3, sticky="ew", pady=8)
        controles.columnconfigure(1, weight=1)
        self.vars: dict[str, tk.DoubleVar] = {}
        for fila, (clave, texto) in enumerate(CONTROLES_DB):
            self._deslizador(controles, fila, clave, texto, -6, 6, lambda v: f"{v:+.1f} dB")
        fila = len(CONTROLES_DB)
        self._deslizador(controles, fila, "reverb", "Reverb", 0, 2, lambda v: f"{v:.0%}", inicial=1.0)
        self._deslizador(controles, fila + 1, "sala", "Sacar sala", 0, 1.5,
                         lambda v: f"{v:.0%}" + (" (habitación original)" if v < 0.05 else
                                                 " (más seco)" if v > 1.05 else ""), inicial=1.0)
        self._deslizador(controles, fila + 2, "presencia", "Presencia del máster", 0, 1,
                         lambda v: f"{v:.0%}" + (" (más adelante, de estudio)" if v >= 0.6 else ""), inicial=0.6)

        voces = ttk.Frame(self)
        voces.grid(row=6, column=0, columnspan=3, sticky="w", pady=(0, 6))
        ttk.Label(voces, text="Voz principal de este tema:").pack(side="left")
        self.voz_principal = tk.StringVar()
        self.combo_voz = ttk.Combobox(voces, textvariable=self.voz_principal, state="readonly", width=32)
        self.combo_voz.pack(side="left", padx=6)
        ttk.Label(voces, text="(cambiarla reprocesa sólo las voces)",
                  foreground="gray").pack(side="left")

        self.marco_silenciadas = ttk.Frame(self)
        self.marco_silenciadas.grid(row=9, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.silenciadas: dict[str, tk.BooleanVar] = {}

        escuchar = ttk.Frame(self)
        escuchar.grid(row=7, column=0, columnspan=3, sticky="w")
        ttk.Label(escuchar, text="Escuchar desde:").pack(side="left")
        self.desde = tk.StringVar(value="0:30")
        ttk.Entry(escuchar, textvariable=self.desde, width=7).pack(side="left", padx=4)
        ttk.Button(escuchar, text="▶ Mezcla actual", command=lambda: self.escuchar("master.wav")).pack(side="left", padx=2)
        ttk.Button(escuchar, text="▶ Versión anterior",
                   command=lambda: self.escuchar("master_anterior.wav")).pack(side="left", padx=2)
        ttk.Button(escuchar, text="⏹ Parar", command=self.reproductor.parar).pack(side="left", padx=2)

        acciones = ttk.Frame(self)
        acciones.grid(row=8, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self.btn_aplicar = ttk.Button(acciones, text="🎚  Aplicar retoque", command=self.aplicar)
        self.btn_aplicar.pack(side="left")
        ttk.Button(acciones, text="↺ Volver a la mezcla automática", command=self.restablecer).pack(side="left", padx=8)

    def _deslizador(self, padre, fila, clave, texto, desde, hasta, formato, inicial=0.0) -> None:
        ttk.Label(padre, text=texto, width=20).grid(row=fila, column=0, sticky="w")
        var = tk.DoubleVar(value=inicial)
        etiqueta = tk.StringVar(value=formato(inicial))

        def cambio(_=None):
            paso = 0.5 if clave in dict(CONTROLES_DB) else 0.05  # dB de a medio; porcentajes de a 5 %
            var.set(round(var.get() / paso) * paso)
            etiqueta.set(formato(var.get()))

        ttk.Scale(padre, from_=desde, to=hasta, variable=var, command=cambio).grid(row=fila, column=1, sticky="ew", padx=6)
        ttk.Label(padre, textvariable=etiqueta, width=28).grid(row=fila, column=2, sticky="w")
        var.trace_add("write", lambda *_: etiqueta.set(formato(var.get())))
        self.vars[clave] = var

    # ---------------------------------------------------------- datos

    def buscar_mezclas(self) -> None:
        texto = self.carpeta.get().strip()
        self.mezclas = mezclas_en(Path(texto)) if texto else {}
        self.combo_tema["values"] = list(self.mezclas)
        if self.mezclas and self.tema.get() not in self.mezclas:
            self.tema.set(next(iter(self.mezclas)))
            self.cargar_retoques()

    def _mezcla(self) -> Path | None:
        if not self.mezclas:
            self.buscar_mezclas()
        destino = self.mezclas.get(self.tema.get())
        if destino is None:
            messagebox.showinfo("Meazclador", "Elegí una carpeta con un tema ya mezclado (pestaña 2).")
        return destino

    def cargar_retoques(self) -> None:
        destino = self.mezclas.get(self.tema.get())
        if destino is None:
            return
        r = Retoques.cargar(destino / ARCHIVO_RETOQUES)
        for clave, _ in CONTROLES_DB:
            self.vars[clave].set(getattr(r, clave))
        self.vars["reverb"].set(r.reverb)
        self.vars["sala"].set(r.sala)
        proyecto = json.loads((destino / ARCHIVO_PROYECTO).read_text(encoding="utf-8"))
        self.vars["presencia"].set(ESTILOS[proyecto["estilo"]].presencia if r.presencia is None else r.presencia)
        vocales = [d for d in proyecto["pistas"] if d["rol"] in ROLES_VOZ]
        self.combo_voz["values"] = [d["nombre"] for d in vocales]
        actual = next((d["nombre"] for d in vocales if d["rol"] == "voz"), "")
        self.voz_principal.set(actual)
        self._voz_al_cargar = actual

        # Pistas que en este tema se silenciaron por no cantar: casilla para hacerlas sonar igual.
        for hijo in self.marco_silenciadas.winfo_children():
            hijo.destroy()
        self.silenciadas = {}
        calladas = [d["nombre"] for d in proyecto["pistas"] if d.get("silenciada")]
        if calladas:
            ttk.Label(self.marco_silenciadas, text="Silenciadas por no cantar en este tema (tildá para que suenen):"
                      ).pack(anchor="w")
            for nombre in calladas:
                var = tk.BooleanVar(value=nombre in r.reactivar)
                ttk.Checkbutton(self.marco_silenciadas, text=nombre, variable=var).pack(anchor="w", padx=12)
                self.silenciadas[nombre] = var

    def restablecer(self) -> None:
        for clave, _ in CONTROLES_DB:
            self.vars[clave].set(0.0)
        self.vars["reverb"].set(1.0)
        self.vars["sala"].set(1.0)
        destino = self.mezclas.get(self.tema.get())
        if destino is not None:
            (destino / ARCHIVO_RETOQUES).unlink(missing_ok=True)
            self.cargar_retoques()

    # ---------------------------------------------------------- acciones

    def aplicar(self) -> None:
        destino = self._mezcla()
        if destino is None:
            return
        self.reproductor.parar()
        args = ["retocar", str(destino.parent)]
        for clave, _ in CONTROLES_DB:
            args += [f"--{clave}", f"{self.vars[clave].get():.1f}"]
        args += ["--reverb", f"{self.vars['reverb'].get() * 100:.0f}",
                 "--sala", f"{self.vars['sala'].get() * 100:.0f}",
                 "--presencia", f"{self.vars['presencia'].get():.2f}"]
        for nombre, var in self.silenciadas.items():
            args += ["--reactivar" if var.get() else "--silenciar", nombre]
        if self.voz_principal.get() and self.voz_principal.get() != getattr(self, "_voz_al_cargar", ""):
            args += ["--voz-principal", self.voz_principal.get()]
            self.app._log(f"Cambio de voz principal a '{self.voz_principal.get()}': se vuelven a procesar las voces "
                          "(tarda un poco más que un retoque común).\n")

        def listo():
            self.cargar_retoques()
            self.app._log("Retoque aplicado. Escuchá 'Mezcla actual' y comparalo con 'Versión anterior'.\n")
            self.escuchar("master.wav")

        self.app._correr(args, listo)

    def escuchar(self, archivo: str) -> None:
        destino = self._mezcla()
        if destino is None:
            return
        ruta = destino / archivo
        if not ruta.is_file():
            messagebox.showinfo("Meazclador", "Todavía no hay una versión anterior: aparece después del primer retoque.")
            return
        try:
            desde = de_reloj(self.desde.get() or "0")
        except ValueError:
            desde = 0.0
        with sf.SoundFile(str(ruta)) as f:
            desde = min(desde, max(0.0, f.frames / f.samplerate - ESCUCHA_S))  # que se escuche un tramo entero
            f.seek(int(desde * f.samplerate))
            audio = f.read(int(ESCUCHA_S * f.samplerate), dtype="float32", always_2d=True).T
            sr = f.samplerate
        self.desde.set(a_reloj(desde))
        aviso = self.reproductor.reproducir(audio, sr, desde)
        if aviso:
            self.app._log(aviso + "\n")
