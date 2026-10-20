"""Paso 5 de la ventana: medir el tempo de cada tema, ver dónde se va de tempo y armar clicks."""

from __future__ import annotations

import json
import re
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from . import preferencias
from .convertir import titulo_y_orden
from .estilo_ui import ACENTO, ERROR, EXITO, S1, S2, S3, S4, S6, TEXTO_2, TEXTO_3, CampoRuta, Tarjeta
from .tempo import ARCHIVO_TEMPOS, CARPETA_CLICKS, archivos_en

FORMATOS = {"MP3": "mp3", "WAV": "wav"}
CUENTAS = {"8 golpes": 8, "4 golpes": 4}
ARRANQUES = ("A tempo", "Gradual")
ESTADOS = {
    "espera": ("○", "Sin medir"),
    "midiendo": ("◐", "Midiendo…"),
    "listo": ("✓", "Listo"),
    "cancelado": ("–", "Cancelado"),
    "error": ("!", "Error"),
}


class PaginaTempo(ttk.Frame):
    def __init__(self, padre, app):
        super().__init__(padre)
        self.app = app
        self.archivos: list[Path] = []
        self.resultados: dict[str, dict] = {}  # archivo -> fila de tempos.json
        self.bpm_manual: dict[str, float] = {}
        self.gradual: dict[str, bool] = {}
        self._actual: str | None = None
        self._editor: ttk.Entry | None = None
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        origen = Tarjeta(self)
        origen.grid(row=0, column=0, sticky="ew")
        for c in range(3):
            origen.columnconfigure(c, weight=1 if c == 0 else 0)
        self.carpeta = tk.StringVar()
        CampoRuta(origen, "Carpeta con los temas (MP3 o WAV)", self.carpeta,
                  ayuda="Por ejemplo la carpeta 'mp3' del paso 4. Los clicks quedan en 'clicks', al lado."
                  ).grid(row=0, column=0, sticky="ew")
        self.carpeta.trace_add("write", lambda *_: self.after(80, self.actualizar_lista))
        self.formato = tk.StringVar(value=next(iter(FORMATOS)))
        self.cuenta = tk.StringVar(value=next(iter(CUENTAS)))
        for col, (etiqueta, var, valores, ancho) in enumerate((("Formato", self.formato, list(FORMATOS), 6),
                                                               ("Cuenta", self.cuenta, list(CUENTAS), 9)), 1):
            marco = ttk.Frame(origen, style="Superficie.TFrame")
            marco.grid(row=0, column=col, sticky="new", padx=(S6, 0))
            ttk.Label(marco, text=etiqueta, style="Tarjeta.Secundario.TLabel").grid(row=0, column=0, sticky="w",
                                                                                  pady=(0, S1))
            ttk.Combobox(marco, textvariable=var, values=valores, state="readonly", width=ancho).grid(
                row=1, column=0, sticky="ew")

        lista = Tarjeta(self, relleno=S4)
        lista.grid(row=1, column=0, sticky="nsew", pady=(S4, 0))
        lista.columnconfigure(0, weight=1)
        lista.rowconfigure(1, weight=1)
        self.resumen = tk.StringVar(value="Temas")
        ttk.Label(lista, textvariable=self.resumen, style="Tarjeta.Subtitulo.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, S2))
        ttk.Label(lista, text="Tempo fijo, igual en los cortes · doble clic en BPM o Arranque para cambiarlos",
                  style="Tarjeta.Pista.TLabel"
                  ).grid(row=0, column=0, columnspan=2, sticky="e", pady=(0, S2))
        columnas = (("estado", "ESTADO", 110, False, "w"), ("tema", "TEMA", 230, True, "w"),
                    ("bpm", "BPM", 70, False, "e"), ("arranque", "ARRANQUE", 100, False, "w"),
                    ("cortes", "CORTES", 70, False, "e"), ("desvios", "SE VA DE TEMPO", 130, False, "w"))
        self.tabla = ttk.Treeview(lista, columns=[c[0] for c in columnas], show="headings", selectmode="browse",
                                  height=6)
        for col, titulo, ancho, estirar, alin in columnas:
            self.tabla.heading(col, text=titulo, anchor=alin)
            self.tabla.column(col, width=ancho, stretch=estirar, anchor=alin)
        for etiqueta, color in (("listo", EXITO), ("midiendo", ACENTO), ("error", ERROR), ("espera", TEXTO_2),
                                ("cancelado", TEXTO_3)):
            self.tabla.tag_configure(etiqueta, foreground=color)
        self.tabla.grid(row=1, column=0, sticky="nsew")
        barra = ttk.Scrollbar(lista, orient="vertical", command=self.tabla.yview)
        barra.grid(row=1, column=1, sticky="ns")
        self.tabla.configure(yscrollcommand=barra.set)
        self.tabla.bind("<Double-1>", self._editar_celda)
        self.tabla.bind("<<TreeviewSelect>>", lambda _: self._mostrar_detalle())
        self.detalle = tk.StringVar(value="")
        ttk.Label(lista, textvariable=self.detalle, style="Tarjeta.Secundario.TLabel", justify="left",
                  wraplength=720).grid(row=2, column=0, columnspan=2, sticky="nw", pady=(S3, 0))
        self.vacio = ttk.Label(lista, style="Tarjeta.Secundario.TLabel", justify="center", anchor="center",
                               text="Todavía no hay temas.\nElegí arriba una carpeta con los temas en MP3 o WAV.")

        acciones = ttk.Frame(self)
        acciones.grid(row=2, column=0, sticky="ew", pady=(S4, 0))
        self.btn_medir = ttk.Button(acciones, text="♩  Medir tempo y armar clicks", style="Primario.TButton",
                                    command=self.medir)
        self.btn_medir.pack(side="left")
        self.btn_abrir = ttk.Button(acciones, text="Abrir carpeta de clicks", state="disabled",
                                    command=self._abrir_clicks)
        self.btn_abrir.pack(side="left", padx=(S3, 0))
        self.actualizar_lista()

    # ---------------------------------------------------------- lista

    @property
    def destino(self) -> Path | None:
        return Path(self.carpeta.get().strip()) / CARPETA_CLICKS if self.carpeta.get().strip() else None

    def al_mostrar(self) -> None:
        if not self.carpeta.get().strip():  # de entrada: los MP3 del paso 4
            mp3 = self.app.pagina_convertir.destino
            if mp3 and archivos_en(mp3):
                self.carpeta.set(str(mp3))
        self.actualizar_lista()

    def botones_trabajo(self) -> list:
        return [self.btn_medir]

    def actualizar_botones(self) -> None:
        if not self.archivos:
            self.btn_medir.configure(state="disabled")

    def _cargar_resultados(self) -> None:
        self.resultados = {}
        if self.destino and (self.destino / ARCHIVO_TEMPOS).is_file():
            try:
                datos = json.loads((self.destino / ARCHIVO_TEMPOS).read_text(encoding="utf-8"))
                self.resultados = {f["archivo"]: f for f in datos.get("temas", [])}
            except (OSError, ValueError, KeyError):
                self.resultados = {}
        for archivo, fila in self.resultados.items():  # lo que se eligió a mano la vez anterior
            if fila.get("bpm_forzado"):
                self.bpm_manual.setdefault(archivo, float(fila["bpm_forzado"]))
            if fila.get("gradual_pedido"):
                self.gradual.setdefault(archivo, True)

    def actualizar_lista(self) -> None:
        if self.app.trabajando:
            return
        texto = self.carpeta.get().strip()
        archivos = archivos_en(Path(texto)) if texto else []
        if [a.name for a in archivos] != [a.name for a in self.archivos]:
            self.bpm_manual, self.gradual = {}, {}
        self.archivos = archivos
        self._cargar_resultados()
        self.tabla.delete(*self.tabla.get_children())
        for a in archivos:
            self._fila(a.name, "listo" if a.name in self.resultados else "espera")
        hay = bool(archivos)
        if hay:
            self.vacio.place_forget()
            self.resumen.set("1 tema" if len(archivos) == 1 else f"{len(archivos)} temas")
            preferencias.guardar(tempo=texto)
        else:
            self.resumen.set("Temas")
            self.vacio.place(relx=0.5, rely=0.55, anchor="center")
        self.btn_medir.configure(state="normal" if hay else "disabled")
        self.btn_abrir.configure(state="normal" if self.destino and self.destino.is_dir() else "disabled")
        self._mostrar_detalle()

    def _fila(self, archivo: str, estado: str) -> None:
        icono, texto = ESTADOS[estado]
        r = self.resultados.get(archivo, {})
        bpm = self.bpm_manual.get(archivo) or r.get("bpm_click")
        gradual = self.gradual.get(archivo, bool(r.get("gradual_pedido")))
        valores = (f"{icono}  {texto}", titulo_y_orden(Path(archivo).stem)[0],
                   f"{bpm:g}" if bpm else "–", ARRANQUES[gradual],
                   len(r["cortes"]) if r else "–", r.get("resumen", "–") if r else "–")
        if self.tabla.exists(archivo):
            self.tabla.item(archivo, values=valores, tags=(estado,))
        else:
            self.tabla.insert("", "end", iid=archivo, values=valores, tags=(estado,))

    def _estado(self, archivo: str) -> str:
        return self.tabla.item(archivo, "tags")[0] if self.tabla.exists(archivo) else "espera"

    def _mostrar_detalle(self) -> None:
        sel = self.tabla.selection()
        r = self.resultados.get(sel[0]) if sel else None
        if not r:
            self.detalle.set("Elegí un tema de la lista para ver dónde se va de tempo." if self.resultados else "")
            return
        titulo = titulo_y_orden(Path(r["archivo"]).stem)[0]
        lineas = [f"{titulo}: {r['bpm_click']:g} BPM"]
        if r.get("golpes_rampa"):
            lineas[0] += f", arranque gradual desde {r['bpm_inicial']:.0f}"
        lineas += r.get("detalle") or ["Estable: no se va de tempo."]
        self.detalle.set("\n".join(lineas))

    # ---------------------------------------------------------- editar BPM y arranque

    def _editar_celda(self, evento) -> None:
        fila = self.tabla.identify_row(evento.y)
        columna = {"#3": "bpm", "#4": "arranque"}.get(self.tabla.identify_column(evento.x))
        if not fila or not columna or self.app.trabajando:
            return
        if columna == "arranque":
            self.alternar_arranque(fila)
        else:
            self.editar_bpm(fila)

    def alternar_arranque(self, archivo: str) -> None:
        r = self.resultados.get(archivo, {})
        self.gradual[archivo] = not self.gradual.get(archivo, bool(r.get("gradual_pedido")))
        self._fila(archivo, self._estado(archivo))

    def poner_bpm(self, archivo: str, texto: str) -> bool:
        texto = texto.strip().replace(",", ".")
        if not re.fullmatch(r"\d{2,3}(\.\d+)?", texto) or not 40 <= float(texto) <= 300:
            self.app.notificar("El tempo tiene que ser un número entre 40 y 300, por ejemplo 163 o 107.5.", "aviso")
            return False
        self.bpm_manual[archivo] = float(texto)
        self._fila(archivo, self._estado(archivo))
        return True

    def editar_bpm(self, archivo: str) -> None:
        if self._editor is not None:
            self._editor.destroy()
        x, y, ancho, alto = self.tabla.bbox(archivo, "bpm") or (0, 0, 0, 0)
        if not ancho:
            return
        editor = ttk.Entry(self.tabla, justify="right")
        editor.insert(0, str(self.tabla.set(archivo, "bpm")).replace("–", ""))
        editor.select_range(0, "end")
        editor.place(x=x, y=y, width=max(ancho, 70), height=alto)
        editor.focus_set()
        self._editor = editor

        def terminar(guardar: bool) -> None:
            if self._editor is not editor:
                return
            texto = editor.get()
            self._editor = None
            editor.destroy()
            if guardar and texto.strip():
                self.poner_bpm(archivo, texto)

        editor.bind("<Return>", lambda _: terminar(True))
        editor.bind("<KP_Enter>", lambda _: terminar(True))
        editor.bind("<Escape>", lambda _: terminar(False))
        editor.bind("<FocusOut>", lambda _: terminar(True))

    # ---------------------------------------------------------- medir

    def _abrir_clicks(self) -> None:
        from .gui import abrir_carpeta

        if self.destino and self.destino.is_dir():
            abrir_carpeta(self.destino)

    def _leer_linea(self, linea: str) -> None:
        total = max(1, len(self.archivos))
        m = re.match(r"^=== (.+) \((\d+)/(\d+)\) ===$", linea)
        if m:
            if self._actual:
                self._fila(self._actual, "listo")
            self._actual, i = m.group(1), int(m.group(2))
            self._fila(self._actual, "midiendo")
            self.tabla.see(self._actual)
            self.app.poner_estado(f"Midiendo {titulo_y_orden(Path(self._actual).stem)[0]}", f"Tema {i} de {total}",
                                  (i - 1) / total)

    def _al_terminar(self, codigo: int) -> None:
        if self._actual:
            self._fila(self._actual, {0: "listo", -1: "cancelado"}.get(codigo, "error"))
        self._actual = None

    def medir(self) -> None:
        if self._editor is not None:
            self._editor.event_generate("<Return>")
        carpeta = self.app._carpeta_valida(self.carpeta)
        if not carpeta:
            return
        self.actualizar_lista()
        if not self.archivos:
            self.app.notificar("En esa carpeta no hay temas en MP3 o WAV.", "aviso")
            return
        args = ["tempo", str(carpeta), f"--formato={FORMATOS.get(self.formato.get(), 'mp3')}",
                f"--cuenta={CUENTAS.get(self.cuenta.get(), 8)}"]
        for a in self.archivos:
            if a.name in self.bpm_manual:
                args.append(f"--bpm={a.name}={self.bpm_manual[a.name]:g}")
            if self.gradual.get(a.name, bool(self.resultados.get(a.name, {}).get("gradual_pedido"))):
                args.append(f"--gradual={a.name}")
        self._actual = None

        def listo():
            self._cargar_resultados()
            for a in self.archivos:
                self._fila(a.name, "listo")
            self.btn_abrir.configure(state="normal")
            self.app.marcar_hecho(5)
            con_desvios = sum(bool(r.get("desvios")) for r in self.resultados.values())
            self.app.notificar(f"Listo: {len(self.archivos)} clicks en {self.destino}. "
                               f"{con_desvios} temas tienen partes donde se va de tempo; elegí uno en la lista "
                               f"para ver dónde.", "exito", ("Abrir carpeta", self._abrir_clicks))
            self._mostrar_detalle()

        self.app.escuchar_trabajo(self._leer_linea, self._al_terminar)
        self.app._correr(args, listo, estado="Midiendo el tempo…")
