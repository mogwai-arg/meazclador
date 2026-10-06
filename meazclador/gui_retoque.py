"""Paso 3 de la ventana: escuchar cada tema mezclado y retocarlo (comparando con la versión anterior)."""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import soundfile as sf

from .analisis import ROLES_VOZ
from .estilo_ui import S1, S2, S3, S4, S6, Tarjeta, deslizador
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
        super().__init__(padre)
        self.app = app
        self.reproductor = Reproductor()
        self.mezclas: dict[str, Path] = {}
        self.vars: dict[str, tk.DoubleVar] = {}
        self.silenciadas: dict[str, tk.BooleanVar] = {}
        self._voz_al_cargar = ""
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        # --- izquierda: dónde están y cuáles son los temas
        izquierda = Tarjeta(self)
        izquierda.grid(row=0, column=0, sticky="nsw", padx=(0, S4))
        izquierda.rowconfigure(1, weight=1)
        ttk.Label(izquierda, text="Temas", style="Tarjeta.Subtitulo.TLabel").grid(row=0, column=0, sticky="w",
                                                                                pady=(0, S2))
        self.tema = tk.StringVar()
        self.lista_temas = ttk.Treeview(izquierda, columns=("tema",), show="headings", selectmode="browse", height=8)
        self.lista_temas.heading("tema", text="MEZCLADOS", anchor="w")
        self.lista_temas.column("tema", width=200, anchor="w")
        self.lista_temas.grid(row=1, column=0, sticky="nsew")
        self.lista_temas.bind("<<TreeviewSelect>>", lambda _: self._tema_elegido())
        self.carpeta = tk.StringVar()
        self.nombre_carpeta = tk.StringVar(value="")
        ttk.Label(izquierda, textvariable=self.nombre_carpeta, style="Tarjeta.Pista.TLabel", wraplength=200).grid(
            row=2, column=0, sticky="w", pady=(S3, 0))
        ttk.Button(izquierda, text="Cambiar carpeta…", style="Tarjeta.Fantasma.TButton",
                   command=self._elegir_carpeta).grid(row=3, column=0, sticky="w", pady=(S1, 0))
        self.carpeta.trace_add("write", lambda *_: self.after(50, self.buscar_mezclas))

        # --- derecha: escuchar, ajustar y aplicar
        self.derecha = ttk.Frame(self)
        self.derecha.grid(row=0, column=1, sticky="nsew")
        self.derecha.columnconfigure(0, weight=1, uniform="col")
        self.derecha.columnconfigure(1, weight=1, uniform="col")

        escuchar = Tarjeta(self.derecha)
        escuchar.grid(row=0, column=0, columnspan=2, sticky="ew")
        # Se empaqueta primero para que, si la ventana es angosta, la acción principal nunca quede aplastada.
        self.btn_aplicar = ttk.Button(escuchar, text="Aplicar retoque", style="Primario.TButton", command=self.aplicar)
        self.btn_aplicar.pack(side="right")
        ttk.Label(escuchar, text="Desde", style="Tarjeta.Secundario.TLabel").pack(side="left")
        self.desde = tk.StringVar(value="0:30")
        ttk.Entry(escuchar, textvariable=self.desde, width=6).pack(side="left", padx=(S2, S3))
        ttk.Button(escuchar, text="▶  Actual", command=lambda: self.escuchar("master.wav")).pack(side="left")
        ttk.Button(escuchar, text="▶  Anterior",
                   command=lambda: self.escuchar("master_anterior.wav")).pack(side="left", padx=(S2, 0))
        ttk.Button(escuchar, text="■", width=3, style="Tarjeta.Fantasma.TButton",
                   command=self.reproductor.parar).pack(side="left", padx=(S1, 0))

        niveles = Tarjeta(self.derecha)
        niveles.grid(row=1, column=0, sticky="nsew", pady=(S4, 0), padx=(0, S2))
        niveles.columnconfigure(1, weight=1)
        ttk.Label(niveles, text="Niveles", style="Tarjeta.Subtitulo.TLabel").grid(row=0, column=0, columnspan=3,
                                                                                sticky="w", pady=(0, S2))
        for fila, (clave, texto) in enumerate(CONTROLES_DB, 1):
            self._deslizador(niveles, fila, clave, texto, -6, 6, lambda v: f"{v:+.1f} dB")

        sonido = Tarjeta(self.derecha)
        sonido.grid(row=1, column=1, sticky="nsew", pady=(S4, 0), padx=(S2, 0))
        sonido.columnconfigure(1, weight=1)
        ttk.Label(sonido, text="Sonido", style="Tarjeta.Subtitulo.TLabel").grid(row=0, column=0, columnspan=3,
                                                                              sticky="w", pady=(0, S2))
        self._deslizador(sonido, 1, "reverb", "Reverb", 0, 2, lambda v: f"{v:.0%}", inicial=1.0)
        self._deslizador(sonido, 2, "sala", "Sacar sala", 0, 1.5, lambda v: f"{v:.0%}", inicial=1.0)
        self._deslizador(sonido, 3, "presencia", "Presencia", 0, 1, lambda v: f"{v:.0%}", inicial=0.6)
        ttk.Label(sonido, style="Tarjeta.Pista.TLabel", justify="left", wraplength=220,
                  text="Sacar sala en 0 % deja la habitación original.\n"
                       "Presencia: cuánto trae todo adelante.").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(S2, 0))

        voces = Tarjeta(self.derecha)
        voces.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(S4, 0))
        voces.columnconfigure(2, weight=1)
        ttk.Label(voces, text="Voces", style="Tarjeta.Subtitulo.TLabel").grid(row=0, column=0, sticky="w",
                                                                            pady=(0, S2))
        ttk.Label(voces, text="Voz principal", style="Tarjeta.Secundario.TLabel").grid(row=1, column=0, sticky="w")
        self.voz_principal = tk.StringVar()
        self.combo_voz = ttk.Combobox(voces, textvariable=self.voz_principal, state="readonly", width=28)
        self.combo_voz.grid(row=1, column=1, sticky="w", padx=(S3, 0))
        ttk.Label(voces, text="Si la cambiás, se vuelven a procesar sólo las voces.",
                  style="Tarjeta.Pista.TLabel").grid(row=2, column=1, sticky="w", padx=(S3, 0), pady=(S1, 0))
        self.marco_silenciadas = ttk.Frame(voces, style="Superficie.TFrame")
        self.marco_silenciadas.grid(row=3, column=0, columnspan=3, sticky="w", pady=(S2, 0))

        ttk.Button(self.derecha, text="Volver a la mezcla automática", style="Fantasma.TButton",
                   command=self.restablecer).grid(row=3, column=0, columnspan=2, sticky="w", pady=(S2, 0))

        # --- estado vacío
        self.vacio = Tarjeta(self, relleno=S6)
        ttk.Label(self.vacio, text="Todavía no hay temas mezclados", style="Tarjeta.Subtitulo.TLabel").pack(anchor="w")
        ttk.Label(self.vacio, style="Tarjeta.Secundario.TLabel", wraplength=520, justify="left",
                  text="Cuando mezcles en el paso 2, los temas aparecen acá para escucharlos y retocarlos. "
                       "Si ya los mezclaste, elegí arriba la carpeta donde están.").pack(anchor="w", pady=(S2, S4))
        ttk.Button(self.vacio, text="Ir a Mezclar", style="Primario.TButton",
                   command=lambda: self.app.ir_a(2)).pack(anchor="w")
        self._mostrar_vacio(True)

    def _elegir_carpeta(self) -> None:
        from tkinter import filedialog

        r = filedialog.askdirectory(initialdir=self.carpeta.get() or str(Path.home()))
        if r:
            self.carpeta.set(r)

    def _deslizador(self, padre, fila, clave, texto, desde, hasta, formato, inicial=0.0) -> None:
        ttk.Label(padre, text=texto, style="Tarjeta.TLabel", width=9).grid(row=fila, column=0, sticky="w", pady=S1)
        var = tk.DoubleVar(value=inicial)
        etiqueta = tk.StringVar(value=formato(inicial))

        def cambio(_=None):
            paso = 0.5 if clave in dict(CONTROLES_DB) else 0.05  # dB de a medio; porcentajes de a 5 %
            var.set(round(var.get() / paso) * paso)
            etiqueta.set(formato(var.get()))

        deslizador(padre, var, desde, hasta, cambio).grid(row=fila, column=1, sticky="ew", padx=S2)
        ttk.Label(padre, textvariable=etiqueta, style="Tarjeta.Secundario.TLabel", width=6, anchor="e").grid(
            row=fila, column=2, sticky="e")
        var.trace_add("write", lambda *_: etiqueta.set(formato(var.get())))
        self.vars[clave] = var

    def _mostrar_vacio(self, vacio: bool) -> None:
        if vacio:
            self.vacio.grid(row=0, column=1, sticky="new")
            self.vacio.tkraise()
        else:
            self.vacio.grid_forget()

    def botones_trabajo(self) -> list:
        return [self.btn_aplicar]

    def al_mostrar(self) -> None:
        self.buscar_mezclas()

    # ---------------------------------------------------------- datos

    def buscar_mezclas(self) -> None:
        texto = self.carpeta.get().strip()
        self.mezclas = mezclas_en(Path(texto)) if texto else {}
        self.nombre_carpeta.set(f"En {Path(texto).name}" if texto else "Sin carpeta elegida")
        self.lista_temas.delete(*self.lista_temas.get_children())
        for nombre in self.mezclas:
            self.lista_temas.insert("", "end", iid=nombre, values=(nombre,))
        self._mostrar_vacio(not self.mezclas)
        if self.mezclas:
            elegido = self.tema.get() if self.tema.get() in self.mezclas else next(iter(self.mezclas))
            self.lista_temas.selection_set(elegido)
            self.lista_temas.see(elegido)
            if elegido != self.tema.get():
                self.tema.set(elegido)
                self.cargar_retoques()

    def _tema_elegido(self) -> None:
        sel = self.lista_temas.selection()
        if sel and sel[0] != self.tema.get():
            self.reproductor.parar()
            self.tema.set(sel[0])
            self.cargar_retoques()

    def _mezcla(self) -> Path | None:
        if not self.mezclas:
            self.buscar_mezclas()
        destino = self.mezclas.get(self.tema.get())
        if destino is None:
            self.app.notificar("Elegí un tema ya mezclado (los mezclás en el paso 2).", "info")
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
            ttk.Label(self.marco_silenciadas, text="Silenciadas porque no cantan en este tema. Tildá para que suenen:",
                      style="Tarjeta.Pista.TLabel").pack(anchor="w")
            for nombre in calladas:
                var = tk.BooleanVar(value=nombre in r.reactivar)
                ttk.Checkbutton(self.marco_silenciadas, text=nombre, variable=var, style="Tarjeta.TCheckbutton").pack(
                    anchor="w", pady=(S1, 0))
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
            self.app.notificar("Volviste a los valores de la mezcla automática. Tocá 'Aplicar retoque' para "
                               "escucharla así.", "info")

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
        estado = f"Retocando {self.tema.get()}…"
        if self.voz_principal.get() and self.voz_principal.get() != self._voz_al_cargar:
            args += ["--voz-principal", self.voz_principal.get()]
            estado = f"Reprocesando las voces de {self.tema.get()}…"

        def listo():
            self.cargar_retoques()
            self.app.notificar("Retoque aplicado. Ya está sonando la versión nueva; compará con '▶ Anterior'.",
                               "exito")
            self.escuchar("master.wav")

        self.app._correr(args, listo, estado=estado)

    def escuchar(self, archivo: str) -> None:
        destino = self._mezcla()
        if destino is None:
            return
        ruta = destino / archivo
        if not ruta.is_file():
            self.app.notificar("Todavía no hay versión anterior: aparece después del primer retoque.", "info")
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
        nombre = "la versión actual" if archivo == "master.wav" else "la versión anterior"
        self.app.poner_estado(f"Sonando {nombre}", f"{self.tema.get()} · desde {a_reloj(desde)}",
                              0)
