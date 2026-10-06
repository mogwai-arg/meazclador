"""Paso 2 de la ventana: mezclar y masterizar todos los temas, viendo cómo avanza cada uno."""

from __future__ import annotations

import re
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from . import preferencias
from .estilo_ui import (ACENTO, ERROR, EXITO, S1, S2, S3, S4, S6, TEXTO_2, TEXTO_3, CampoRuta, Plegable, Tarjeta,
                        deslizador)
from .mezcla import ESTILOS, listar_pistas

ESTILOS_GUI = {
    "Natural: limpio y fuerte": "natural",
    "Punk: crudo, estilo Ramones": "punk",
}
GUITARRAS = {
    "Detectar solo": "auto",
    "Por línea (simular el ampli)": "directas",
    "Con ampli microfoneado": "amplificadas",
}
VOLUMENES = {
    "Según el estilo": None,
    "Spotify / YouTube (-14 LUFS)": -14.0,
    "Fuerte (-10 LUFS)": -10.0,
    "Dinámico (-16 LUFS)": -16.0,
}
CARPETAS_SALIDA = {"mezcla", "masters"}
ESTADOS = {
    "espera": ("○", "En espera"),
    "mezclando": ("◐", "Mezclando…"),
    "listo": ("✓", "Listo"),
    "hecho": ("✓", "Ya mezclado"),
    "cancelado": ("–", "Cancelado"),
    "error": ("!", "Error"),
}


def temas_en(carpeta: Path) -> tuple[list[Path], bool]:
    """(temas, es_un_solo_tema). Un tema es una carpeta con pistas de audio."""
    if not carpeta.is_dir():
        return [], False
    if listar_pistas(carpeta):
        return [carpeta], True
    return sorted(d for d in carpeta.iterdir()
                  if d.is_dir() and d.name not in CARPETAS_SALIDA and listar_pistas(d)), False


class PaginaMezclar(ttk.Frame):
    def __init__(self, padre, app):
        super().__init__(padre)
        self.app = app
        self.temas: list[Path] = []
        self.un_solo_tema = False
        self.ultima_salida: Path | None = None
        self._actual: str | None = None
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # --- dónde están los temas
        origen = Tarjeta(self)
        origen.grid(row=0, column=0, sticky="ew")
        origen.columnconfigure(0, weight=1)
        self.carpeta = tk.StringVar()
        CampoRuta(origen, "Carpeta con los temas", self.carpeta,
                  ayuda="La carpeta 'temas' que crea el paso 1, o la carpeta de un solo tema.").grid(
            row=0, column=0, sticky="ew")
        self.carpeta.trace_add("write", lambda *_: self.after(80, self.actualizar_lista))

        # --- la lista de temas con su estado
        lista = Tarjeta(self, relleno=S4)
        lista.grid(row=1, column=0, sticky="nsew", pady=(S4, 0))
        lista.columnconfigure(0, weight=1)
        lista.rowconfigure(1, weight=1)
        self.resumen = tk.StringVar(value="")
        ttk.Label(lista, textvariable=self.resumen, style="Tarjeta.Subtitulo.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, S2))
        self.tabla = ttk.Treeview(lista, columns=("estado", "tema", "pistas"), show="headings", selectmode="none",
                                  height=6)
        for col, titulo, ancho, estirar, alin in (("estado", "ESTADO", 150, False, "w"), ("tema", "TEMA", 360, True, "w"),
                                                  ("pistas", "PISTAS", 90, False, "e")):
            self.tabla.heading(col, text=titulo, anchor=alin)
            self.tabla.column(col, width=ancho, stretch=estirar, anchor=alin)
        for etiqueta, color in (("listo", EXITO), ("hecho", EXITO), ("mezclando", ACENTO), ("error", ERROR),
                                ("espera", TEXTO_2), ("cancelado", TEXTO_3)):
            self.tabla.tag_configure(etiqueta, foreground=color)
        self.tabla.grid(row=1, column=0, sticky="nsew")
        barra = ttk.Scrollbar(lista, orient="vertical", command=self.tabla.yview)
        barra.grid(row=1, column=1, sticky="ns")
        self.tabla.configure(yscrollcommand=barra.set)
        self.vacio = ttk.Label(lista, style="Tarjeta.Secundario.TLabel", justify="center", anchor="center",
                               text="Todavía no hay temas.\nElegí arriba la carpeta 'temas' que crea el paso 1, "
                                    "o la carpeta de un tema con sus pistas.")

        # --- opciones avanzadas (plegadas: lo de entrada ya suena bien)
        avanzadas = Plegable(self, "Opciones avanzadas",
                             al_abrir=lambda: self.app.contenedores[1].lienzo.yview_moveto(1.0))
        avanzadas.grid(row=2, column=0, sticky="ew", pady=(S3, 0))
        cuerpo = Tarjeta(avanzadas.cuerpo)
        cuerpo.pack(fill="x")
        self._opciones(cuerpo)

        # --- acciones
        acciones = ttk.Frame(self)
        acciones.grid(row=3, column=0, sticky="ew", pady=(S4, 0))
        self.btn_mezclar = ttk.Button(acciones, text="▶  Mezclar todos los temas", style="Primario.TButton",
                                      command=self.mezclar)
        self.btn_mezclar.pack(side="left")
        self.btn_abrir = ttk.Button(acciones, text="Abrir carpeta de resultados", state="disabled",
                                    command=self._abrir_resultados)
        self.btn_abrir.pack(side="left", padx=(S3, 0))
        self.actualizar_lista()

    # ---------------------------------------------------------- opciones

    def _campo(self, padre, fila, col, etiqueta, widget_factory, ayuda=None):
        marco = ttk.Frame(padre, style="Superficie.TFrame")
        marco.grid(row=fila, column=col, sticky="ew", padx=(0 if col == 0 else S6, 0), pady=(0, S4))
        marco.columnconfigure(0, weight=1)
        ttk.Label(marco, text=etiqueta, style="Tarjeta.Secundario.TLabel").grid(row=0, column=0, sticky="w",
                                                                              pady=(0, S1))
        w = widget_factory(marco)
        w.grid(row=1, column=0, sticky="ew")
        if ayuda:
            ttk.Label(marco, text=ayuda, style="Tarjeta.Pista.TLabel").grid(row=2, column=0, sticky="w", pady=(S1, 0))
        return w

    def _opciones(self, padre) -> None:
        padre.columnconfigure(0, weight=1, uniform="op")
        padre.columnconfigure(1, weight=1, uniform="op")
        self.estilo = tk.StringVar(value=next(iter(ESTILOS_GUI)))
        combo = self._campo(padre, 0, 0, "Estilo", lambda m: ttk.Combobox(
            m, textvariable=self.estilo, values=list(ESTILOS_GUI), state="readonly"))
        combo.bind("<<ComboboxSelected>>", lambda _: self._estilo_elegido())
        self.volumen = tk.StringVar(value=next(iter(VOLUMENES)))
        self._campo(padre, 0, 1, "Volumen final", lambda m: ttk.Combobox(
            m, textvariable=self.volumen, values=list(VOLUMENES), state="readonly"))
        self.guitarras = tk.StringVar(value=next(iter(GUITARRAS)))
        self._campo(padre, 1, 0, "Guitarras grabadas", lambda m: ttk.Combobox(
            m, textvariable=self.guitarras, values=list(GUITARRAS), state="readonly"))
        self.tonalidad = tk.StringVar()
        self._campo(padre, 1, 1, "Tonalidad (opcional)", lambda m: ttk.Entry(m, textvariable=self.tonalidad),
                    ayuda="Ej.: Am, E, La menor. Sólo cuando mezclás un tema.")

        self.afinar = tk.DoubleVar(value=ESTILOS[next(iter(ESTILOS_GUI.values()))].afinar)
        self.txt_afinar = tk.StringVar(value=self._texto_afinar())

        def fabrica_afinar(m):
            fila = ttk.Frame(m, style="Superficie.TFrame")
            fila.columnconfigure(0, weight=1)
            deslizador(fila, self.afinar, 0, 1, lambda _: self.txt_afinar.set(self._texto_afinar())).grid(
                row=0, column=0, sticky="ew")
            ttk.Label(fila, textvariable=self.txt_afinar, style="Tarjeta.TLabel", width=22).grid(
                row=0, column=1, padx=(S3, 0))
            return fila

        self._campo(padre, 2, 0, "Afinar voces", fabrica_afinar)
        self.referencia = tk.StringVar()
        self._campo(padre, 2, 1, "Tema de referencia (opcional)",
                    lambda m: CampoRuta(m, "", self.referencia, archivo=True))
        self.sample_bombo = tk.StringVar()
        self._campo(padre, 3, 0, "Sample de bombo (opcional)",
                    lambda m: CampoRuta(m, "", self.sample_bombo, archivo=True))
        self.sample_caja = tk.StringVar()
        self._campo(padre, 3, 1, "Sample de caja (opcional)",
                    lambda m: CampoRuta(m, "", self.sample_caja, archivo=True))

    def _texto_afinar(self) -> str:
        v = self.afinar.get()
        if v < 0.05:
            return "No tocar"
        if ESTILOS_GUI.get(self.estilo.get()) == "punk":
            return f"{v:.0%} · sólo desafinadas"
        return f"{v:.0%}" + (" · natural" if v <= 0.6 else " · marcado")

    def _estilo_elegido(self) -> None:
        estilo = ESTILOS[ESTILOS_GUI[self.estilo.get()]]
        self.afinar.set(estilo.afinar if estilo.afinar else 0.0)
        self.txt_afinar.set(self._texto_afinar())

    # ---------------------------------------------------------- lista de temas

    def al_mostrar(self) -> None:
        self.actualizar_lista()

    def botones_trabajo(self) -> list:
        return [self.btn_mezclar]

    def actualizar_botones(self) -> None:
        if not self.temas:
            self.btn_mezclar.configure(state="disabled")

    def actualizar_lista(self) -> None:
        if self.app.trabajando:
            return
        texto = self.carpeta.get().strip()
        self.temas, self.un_solo_tema = temas_en(Path(texto)) if texto else ([], False)
        self.tabla.delete(*self.tabla.get_children())
        for tema in self.temas:
            estado = "hecho" if (tema / "mezcla" / "master.wav").is_file() else "espera"
            self._fila(tema, estado)
        hay = bool(self.temas)
        if hay:
            self.vacio.place_forget()
            self.resumen.set("1 tema" if self.un_solo_tema else f"{len(self.temas)} temas")
            self.btn_mezclar.configure(text="▶  Mezclar este tema" if self.un_solo_tema
                                       else "▶  Mezclar todos los temas")
            preferencias.guardar(temas=texto)
        else:
            self.resumen.set("Temas")
            self.vacio.place(relx=0.5, rely=0.55, anchor="center")
        if not self.app.trabajando:
            self.btn_mezclar.configure(state="normal" if hay else "disabled")
        hechos = [t for t in self.temas if (t / "mezcla" / "master.wav").is_file()]
        self.btn_abrir.configure(state="normal" if hechos else "disabled")

    def _fila(self, tema: Path, estado: str) -> None:
        icono, texto = ESTADOS[estado]
        valores = (f"{icono}  {texto}", tema.name, len(listar_pistas(tema)))
        if self.tabla.exists(tema.name):
            self.tabla.item(tema.name, values=valores, tags=(estado,))
        else:
            self.tabla.insert("", "end", iid=tema.name, values=valores, tags=(estado,))

    def _poner(self, nombre: str, estado: str) -> None:
        tema = next((t for t in self.temas if t.name == nombre), None)
        if tema is not None:
            self._fila(tema, estado)
            self.tabla.see(nombre)

    # ---------------------------------------------------------- mezclar

    def _abrir_resultados(self) -> None:
        from .gui import abrir_carpeta

        if self.un_solo_tema and self.temas:
            abrir_carpeta(self.temas[0] / "mezcla")
        elif (Path(self.carpeta.get()) / "masters").is_dir():
            abrir_carpeta(Path(self.carpeta.get()) / "masters")

    def _leer_linea(self, linea: str) -> None:
        total = max(1, len(self.temas))
        m = re.match(r"^=== (.+) \((\d+)/(\d+)\) ===$", linea)
        if m:
            if self._actual:
                self._poner(self._actual, "listo")
            self._actual, i = m.group(1), int(m.group(2))
            self._poner(self._actual, "mezclando")
            self._hechos = i - 1
            self.app.poner_estado(f"Mezclando {self._actual}", f"Tema {i} de {total}", (i - 1) / total)
            return
        if linea.startswith("✔") and linea.endswith("master.wav"):
            self._hechos = getattr(self, "_hechos", 0) + 1
        paso = None
        for prefijo, fraccion in (("Cargando", 0.05), ("Afinando", 0.2), ("Procesando", 0.4), ("Masterizando", 0.9)):
            if linea.startswith(prefijo):
                paso = fraccion
        if paso is not None:
            hechos = getattr(self, "_hechos", 0)
            self.app.poner_estado(f"Mezclando {self._actual}" if self._actual else "Mezclando…",
                                  linea.rstrip("."), (hechos + paso) / total)

    def _al_terminar(self, codigo: int) -> None:
        if self._actual:
            self._poner(self._actual, {0: "listo", -1: "cancelado"}.get(codigo, "error"))
        self._actual = None

    def mezclar(self) -> None:
        carpeta = self.app._carpeta_valida(self.carpeta)
        if not carpeta:
            return
        self.actualizar_lista()
        if not self.temas:
            self.app.notificar("En esa carpeta no hay temas: elegí la carpeta 'temas' que crea el paso 1, "
                               "o la carpeta de un tema con sus pistas de audio.", "aviso")
            return
        args = ["mezclar", str(carpeta), "--afinar", f"{self.afinar.get():.2f}",
                "--estilo", ESTILOS_GUI[self.estilo.get()], "--guitarras", GUITARRAS[self.guitarras.get()]]
        if VOLUMENES[self.volumen.get()] is not None:
            args += ["--lufs", str(VOLUMENES[self.volumen.get()])]
        for opcion, var in (("--tonalidad", self.tonalidad), ("--referencia", self.referencia),
                            ("--sample-bombo", self.sample_bombo), ("--sample-caja", self.sample_caja)):
            if var.get().strip():
                args += [opcion, var.get().strip()]

        for tema in self.temas:
            self._fila(tema, "espera")
        self._hechos = 0
        self._actual = self.temas[0].name if self.un_solo_tema else None
        if self._actual:
            self._poner(self._actual, "mezclando")

        def listo():
            for tema in self.temas:
                self._fila(tema, "listo")
            self.ultima_salida = (self.temas[0] / "mezcla") if self.un_solo_tema else carpeta / "masters"
            self.btn_abrir.configure(state="normal")
            self.app.marcar_hecho(2)
            cuantos = "El tema quedó mezclado" if self.un_solo_tema else f"Los {len(self.temas)} temas quedaron mezclados"
            self.app.notificar(f"{cuantos}. Los masters están en {self.ultima_salida}.", "exito",
                               ("Escuchar y retocar →", lambda: self.app.ir_a_retocar(carpeta)))

        self.app.escuchar_trabajo(self._leer_linea, self._al_terminar)
        self.app._correr(args, listo, estado="Preparando la mezcla…")
