"""Paso 4 de la ventana: pasar los masters a MP3 con los datos del disco (título, número, disco y artista)."""

from __future__ import annotations

import re
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from . import preferencias
from .convertir import CALIDADES, CARPETA_MP3, temas_de, wavs_en
from .estilo_ui import ACENTO, ERROR, EXITO, S1, S2, S3, S4, S6, TEXTO_2, TEXTO_3, CampoRuta, Tarjeta

CALIDADES_GUI = {
    "320 kbps · máxima": 320,
    "256 kbps · muy buena": 256,
    "192 kbps · más liviana": 192,
    "128 kbps · para mandar por chat": 128,
}
ESTADOS = {
    "espera": ("○", "En espera"),
    "convirtiendo": ("◐", "Convirtiendo…"),
    "listo": ("✓", "Listo"),
    "hecho": ("✓", "Ya convertido"),
    "cancelado": ("–", "Cancelado"),
    "error": ("!", "Error"),
}


class PaginaConvertir(ttk.Frame):
    def __init__(self, padre, app):
        super().__init__(padre)
        self.app = app
        self.wavs: list[Path] = []
        self.etiquetas: dict[str, tuple[int, str]] = {}  # archivo -> (número, título)
        self._actual: str | None = None
        self._editor: ttk.Entry | None = None
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        prefs = preferencias.cargar()

        # --- dónde están los WAV finales
        origen = Tarjeta(self)
        origen.grid(row=0, column=0, sticky="ew")
        origen.columnconfigure(0, weight=1)
        self.carpeta = tk.StringVar()
        CampoRuta(origen, "Carpeta con los WAV finales", self.carpeta,
                  ayuda="La carpeta 'masters' que crea el paso 2 (dentro de 'temas'). Los MP3 se guardan en "
                        "una carpeta 'mp3' al lado de los WAV.").grid(row=0, column=0, sticky="ew")
        self.carpeta.trace_add("write", lambda *_: self.after(80, self.actualizar_lista))

        # --- datos del disco
        datos = Tarjeta(self)
        datos.grid(row=1, column=0, sticky="ew", pady=(S4, 0))
        for c in range(3):
            datos.columnconfigure(c, weight=1, uniform="datos")
        self.disco = tk.StringVar(value=prefs.get("disco", ""))
        self.artista = tk.StringVar(value=prefs.get("artista", ""))
        self.calidad = tk.StringVar(value=next(iter(CALIDADES_GUI)))
        for col, (etiqueta, widget) in enumerate((
                ("Nombre del disco", lambda m: ttk.Entry(m, textvariable=self.disco)),
                ("Artista (la banda)", lambda m: ttk.Entry(m, textvariable=self.artista)),
                ("Calidad", lambda m: ttk.Combobox(m, textvariable=self.calidad, values=list(CALIDADES_GUI),
                                                   state="readonly")))):
            marco = ttk.Frame(datos, style="Superficie.TFrame")
            marco.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else S6, 0))
            marco.columnconfigure(0, weight=1)
            ttk.Label(marco, text=etiqueta, style="Tarjeta.Secundario.TLabel").grid(row=0, column=0, sticky="w",
                                                                                  pady=(0, S1))
            widget(marco).grid(row=1, column=0, sticky="ew")
        ttk.Label(datos, style="Tarjeta.Pista.TLabel",
                  text="Cada MP3 se guarda con su título, número de tema, disco y artista: así se ve bien "
                       "en el celular, en la compu o en el auto.").grid(row=1, column=0, columnspan=3,
                                                                        sticky="w", pady=(S2, 0))

        # --- la lista de temas: número y título editables
        lista = Tarjeta(self, relleno=S4)
        lista.grid(row=2, column=0, sticky="nsew", pady=(S4, 0))
        lista.columnconfigure(0, weight=1)
        lista.rowconfigure(1, weight=1)
        self.resumen = tk.StringVar(value="Temas")
        ttk.Label(lista, textvariable=self.resumen, style="Tarjeta.Subtitulo.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, S2))
        ttk.Label(lista, text="Doble clic en el número o el título para cambiarlos", style="Tarjeta.Pista.TLabel"
                  ).grid(row=0, column=0, columnspan=2, sticky="e", pady=(0, S2))
        self.tabla = ttk.Treeview(lista, columns=("estado", "orden", "titulo", "archivo"), show="headings",
                                  selectmode="browse", height=5)
        for col, titulo, ancho, estirar, alin in (("estado", "ESTADO", 140, False, "w"), ("orden", "Nº", 50, False, "e"),
                                                  ("titulo", "TÍTULO", 280, True, "w"),
                                                  ("archivo", "ARCHIVO", 220, True, "w")):
            self.tabla.heading(col, text=titulo, anchor=alin)
            self.tabla.column(col, width=ancho, stretch=estirar, anchor=alin)
        for etiqueta, color in (("listo", EXITO), ("hecho", EXITO), ("convirtiendo", ACENTO), ("error", ERROR),
                                ("espera", TEXTO_2), ("cancelado", TEXTO_3)):
            self.tabla.tag_configure(etiqueta, foreground=color)
        self.tabla.grid(row=1, column=0, sticky="nsew")
        barra = ttk.Scrollbar(lista, orient="vertical", command=self.tabla.yview)
        barra.grid(row=1, column=1, sticky="ns")
        self.tabla.configure(yscrollcommand=barra.set)
        self.tabla.bind("<Double-1>", self._editar_celda)
        self.tabla.bind("<Return>", lambda _: self.editar(self._elegido(), "titulo"))
        self.vacio = ttk.Label(lista, style="Tarjeta.Secundario.TLabel", justify="center", anchor="center",
                               text="Todavía no hay WAV para convertir.\nElegí arriba la carpeta 'masters' "
                                    "(la crea el paso 2 dentro de 'temas').")

        # --- acciones
        acciones = ttk.Frame(self)
        acciones.grid(row=3, column=0, sticky="ew", pady=(S4, 0))
        self.btn_convertir = ttk.Button(acciones, text="♪  Convertir a MP3", style="Primario.TButton",
                                        command=self.convertir)
        self.btn_convertir.pack(side="left")
        self.btn_abrir = ttk.Button(acciones, text="Abrir carpeta de MP3", state="disabled",
                                    command=self._abrir_mp3)
        self.btn_abrir.pack(side="left", padx=(S3, 0))
        self.actualizar_lista()

    # ---------------------------------------------------------- lista

    @property
    def destino(self) -> Path | None:
        return self.wavs[0].parent / CARPETA_MP3 if self.wavs else None

    def al_mostrar(self) -> None:
        if not self.carpeta.get().strip():  # de entrada: los masters del paso 2
            temas = self.app.pagina_mezclar.carpeta.get().strip()
            if temas and wavs_en(Path(temas)):
                self.carpeta.set(str(Path(temas) / "masters") if (Path(temas) / "masters").is_dir() else temas)
        self.actualizar_lista()

    def botones_trabajo(self) -> list:
        return [self.btn_convertir]

    def actualizar_botones(self) -> None:
        if not self.wavs:
            self.btn_convertir.configure(state="disabled")

    def actualizar_lista(self) -> None:
        if self.app.trabajando:
            return
        texto = self.carpeta.get().strip()
        wavs = wavs_en(Path(texto)) if texto else []
        if [w.name for w in wavs] != [w.name for w in self.wavs]:  # otra carpeta: títulos sacados de los nombres
            self.etiquetas = {t.wav.name: (t.orden, t.titulo) for t in temas_de(wavs)}
        self.wavs = wavs
        self.tabla.delete(*self.tabla.get_children())
        for wav in wavs:
            self._fila(wav, "hecho" if (wav.parent / CARPETA_MP3 / (wav.stem + ".mp3")).is_file() else "espera")
        hay = bool(wavs)
        if hay:
            self.vacio.place_forget()
            self.resumen.set("1 tema" if len(wavs) == 1 else f"{len(wavs)} temas")
            self.btn_convertir.configure(text="♪  Convertir 1 tema a MP3" if len(wavs) == 1
                                         else f"♪  Convertir {len(wavs)} temas a MP3")
            preferencias.guardar(masters=texto)
        else:
            self.resumen.set("Temas")
            self.btn_convertir.configure(text="♪  Convertir a MP3")
            self.vacio.place(relx=0.5, rely=0.55, anchor="center")
        self.btn_convertir.configure(state="normal" if hay else "disabled")
        self.btn_abrir.configure(state="normal" if self.destino and self.destino.is_dir() else "disabled")

    def _fila(self, wav: Path, estado: str) -> None:
        icono, texto = ESTADOS[estado]
        orden, titulo = self.etiquetas.get(wav.name, (0, wav.stem))
        valores = (f"{icono}  {texto}", orden, titulo, wav.name)
        if self.tabla.exists(wav.name):
            self.tabla.item(wav.name, values=valores, tags=(estado,))
        else:
            self.tabla.insert("", "end", iid=wav.name, values=valores, tags=(estado,))

    def _poner(self, nombre: str, estado: str) -> None:
        wav = next((w for w in self.wavs if w.name == nombre), None)
        if wav is not None:
            self._fila(wav, estado)
            self.tabla.see(nombre)

    # ---------------------------------------------------------- editar número y título

    def _elegido(self) -> str | None:
        sel = self.tabla.selection()
        return sel[0] if sel else None

    def _editar_celda(self, evento) -> None:
        fila = self.tabla.identify_row(evento.y)
        columna = {"#2": "orden", "#3": "titulo"}.get(self.tabla.identify_column(evento.x))
        if fila and columna:
            self.editar(fila, columna)

    def poner_etiqueta(self, archivo: str, columna: str, valor: str) -> bool:
        orden, titulo = self.etiquetas[archivo]
        valor = valor.strip()
        if columna == "orden":
            if not re.fullmatch(r"\d{1,3}", valor) or int(valor) < 1:
                self.app.notificar("El número de tema tiene que ser un número entero, por ejemplo 3.", "aviso")
                return False
            orden = int(valor)
        elif valor:
            titulo = valor
        self.etiquetas[archivo] = (orden, titulo)
        estado = self.tabla.item(archivo, "tags")[0] if self.tabla.exists(archivo) else "espera"
        self._fila(next(w for w in self.wavs if w.name == archivo), estado)
        return True

    def editar(self, archivo: str | None, columna: str) -> None:
        """Abre un campo encima de la celda; Enter guarda, Escape cancela."""
        if not archivo or self.app.trabajando:
            return
        if self._editor is not None:
            self._editor.destroy()
        x, y, ancho, alto = self.tabla.bbox(archivo, columna) or (0, 0, 0, 0)
        if not ancho:
            return
        editor = ttk.Entry(self.tabla)
        orden, titulo = self.etiquetas[archivo]
        editor.insert(0, str(orden) if columna == "orden" else titulo)
        editor.select_range(0, "end")
        editor.place(x=x, y=y, width=max(ancho, 60), height=alto)
        editor.focus_set()
        self._editor = editor

        def terminar(guardar: bool) -> None:
            if self._editor is not editor:
                return
            texto = editor.get()
            self._editor = None
            editor.destroy()
            if guardar:
                self.poner_etiqueta(archivo, columna, texto)

        editor.bind("<Return>", lambda _: terminar(True))
        editor.bind("<KP_Enter>", lambda _: terminar(True))
        editor.bind("<Escape>", lambda _: terminar(False))
        editor.bind("<FocusOut>", lambda _: terminar(True))

    # ---------------------------------------------------------- convertir

    def _abrir_mp3(self) -> None:
        from .gui import abrir_carpeta

        if self.destino and self.destino.is_dir():
            abrir_carpeta(self.destino)

    def _leer_linea(self, linea: str) -> None:
        total = max(1, len(self.wavs))
        m = re.match(r"^=== (.+) \((\d+)/(\d+)\) ===$", linea)
        if m:
            if self._actual:
                self._poner(self._actual, "listo")
            self._actual, i = m.group(1), int(m.group(2))
            self._poner(self._actual, "convirtiendo")
            titulo = self.etiquetas.get(self._actual, (0, self._actual))[1]
            self.app.poner_estado(f"Convirtiendo {titulo}", f"Tema {i} de {total}", (i - 1) / total)

    def _al_terminar(self, codigo: int) -> None:
        if self._actual:
            self._poner(self._actual, {0: "listo", -1: "cancelado"}.get(codigo, "error"))
        self._actual = None

    def convertir(self) -> None:
        if self._editor is not None:
            self._editor.event_generate("<Return>")
        carpeta = self.app._carpeta_valida(self.carpeta)
        if not carpeta:
            return
        self.actualizar_lista()
        if not self.wavs:
            self.app.notificar("En esa carpeta no hay archivos WAV: elegí la carpeta 'masters' que crea el paso 2.",
                               "aviso")
            return
        disco, artista = self.disco.get().strip(), self.artista.get().strip()
        preferencias.guardar(disco=disco, artista=artista)
        # '--opcion=valor': así un valor que empieza con '-' no se confunde con otra opción
        args = ["convertir", str(carpeta), f"--kbps={CALIDADES_GUI.get(self.calidad.get(), CALIDADES[0])}",
                f"--disco={disco}", f"--artista={artista}"]
        for wav in self.wavs:
            orden, titulo = self.etiquetas[wav.name]
            args += [f"--orden={wav.name}={orden}", f"--titulo={wav.name}={titulo}"]
        for wav in self.wavs:
            self._fila(wav, "espera")
        self._actual = None
        destino = self.destino

        def listo():
            for wav in self.wavs:
                self._fila(wav, "listo")
            self.btn_abrir.configure(state="normal")
            self.app.marcar_hecho(4)
            cuantos = "El MP3 quedó listo" if len(self.wavs) == 1 else f"Los {len(self.wavs)} MP3 quedaron listos"
            self.app.notificar(f"{cuantos}, con sus datos de disco. Están en {destino}.", "exito",
                               ("Abrir carpeta", self._abrir_mp3))

        self.app.escuchar_trabajo(self._leer_linea, self._al_terminar)
        self.app._correr(args, listo, estado="Preparando la conversión…")
