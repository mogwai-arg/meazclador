"""Paso 4 de la ventana: pasar los masters a MP3 con los datos del disco (título, número, disco y artista),
o cargarle esos datos a MP3 que ya existen."""

from __future__ import annotations

import re
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from . import preferencias
from .convertir import CALIDADES, CARPETA_MP3, archivos_en, datos_comunes, leer_etiquetas, temas_de, wavs_en
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
    "sin_datos": ("○", "Sin datos"),
    "con_datos": ("✓", "Con datos"),
    "guardando": ("◐", "Guardando…"),
    "cancelado": ("–", "Cancelado"),
    "error": ("!", "Error"),
}


class PaginaConvertir(ttk.Frame):
    def __init__(self, padre, app):
        super().__init__(padre)
        self.app = app
        self.archivos: list[Path] = []  # WAV para convertir, o MP3 para cargarles los datos
        self.modo = "wav"
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
        CampoRuta(origen, "Carpeta con los WAV finales o con MP3", self.carpeta,
                  ayuda="Con WAV (la carpeta 'masters' del paso 2): los pasa a MP3 en una carpeta 'mp3' al lado. "
                        "Con MP3: sólo les carga los datos del disco.").grid(row=0, column=0, sticky="ew")
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
            w = widget(marco)
            w.grid(row=1, column=0, sticky="ew")
            if etiqueta == "Calidad":
                self.combo_calidad = w
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
        for etiqueta, color in (("listo", EXITO), ("hecho", EXITO), ("con_datos", EXITO), ("convirtiendo", ACENTO),
                                ("guardando", ACENTO), ("error", ERROR), ("espera", TEXTO_2), ("sin_datos", TEXTO_2),
                                ("cancelado", TEXTO_3)):
            self.tabla.tag_configure(etiqueta, foreground=color)
        self.tabla.grid(row=1, column=0, sticky="nsew")
        barra = ttk.Scrollbar(lista, orient="vertical", command=self.tabla.yview)
        barra.grid(row=1, column=1, sticky="ns")
        self.tabla.configure(yscrollcommand=barra.set)
        self.tabla.bind("<Double-1>", self._editar_celda)
        self.tabla.bind("<Return>", lambda _: self.editar(self._elegido(), "titulo"))
        self.vacio = ttk.Label(lista, style="Tarjeta.Secundario.TLabel", justify="center", anchor="center",
                               text="Todavía no hay temas.\nElegí arriba la carpeta 'masters' del paso 2 "
                                    "(WAV) o una carpeta con MP3.")

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
        """Dónde quedan los MP3: al lado de los WAV, o la misma carpeta si ya eran MP3."""
        if not self.archivos:
            return None
        return self.archivos[0].parent if self.modo == "mp3" else self.archivos[0].parent / CARPETA_MP3

    def al_mostrar(self) -> None:
        if not self.carpeta.get().strip():  # de entrada: los masters del paso 2
            temas = self.app.pagina_mezclar.carpeta.get().strip()
            if temas and wavs_en(Path(temas)):
                self.carpeta.set(str(Path(temas) / "masters") if (Path(temas) / "masters").is_dir() else temas)
        self.actualizar_lista()

    def botones_trabajo(self) -> list:
        return [self.btn_convertir]

    def actualizar_botones(self) -> None:
        if not self.archivos:
            self.btn_convertir.configure(state="disabled")

    def actualizar_lista(self) -> None:
        if self.app.trabajando:
            return
        texto = self.carpeta.get().strip()
        archivos, modo = archivos_en(Path(texto)) if texto else ([], "wav")
        if [a.name for a in archivos] != [a.name for a in self.archivos] or modo != self.modo:
            # otra carpeta: títulos y números de los datos que ya tienen los MP3, o de los nombres
            self.etiquetas = {t.archivo.name: (t.orden, t.titulo) for t in temas_de(archivos)}
            if modo == "mp3":
                comunes = datos_comunes(archivos)
                for var, clave in ((self.disco, "disco"), (self.artista, "artista")):
                    if comunes[clave]:
                        var.set(comunes[clave])
        self.archivos, self.modo = archivos, modo
        self.tabla.delete(*self.tabla.get_children())
        for a in archivos:
            self._fila(a, self._estado_inicial(a))
        hay, n = bool(archivos), len(archivos)
        self.combo_calidad.configure(state="disabled" if modo == "mp3" else "readonly")
        if hay:
            self.vacio.place_forget()
            self.resumen.set(("1 tema" if n == 1 else f"{n} temas") + (" en MP3" if modo == "mp3" else ""))
            if modo == "mp3":
                self.btn_convertir.configure(text="♪  Guardar los datos en el MP3" if n == 1
                                             else f"♪  Guardar los datos en los {n} MP3")
            else:
                self.btn_convertir.configure(text="♪  Convertir 1 tema a MP3" if n == 1
                                             else f"♪  Convertir {n} temas a MP3")
            preferencias.guardar(masters=texto)
        else:
            self.resumen.set("Temas")
            self.btn_convertir.configure(text="♪  Convertir a MP3")
            self.vacio.place(relx=0.5, rely=0.55, anchor="center")
        self.btn_convertir.configure(state="normal" if hay else "disabled")
        self.btn_abrir.configure(state="normal" if self.destino and self.destino.is_dir() else "disabled")

    def _estado_inicial(self, archivo: Path) -> str:
        if self.modo == "mp3":
            return "con_datos" if leer_etiquetas(archivo)["titulo"] else "sin_datos"
        return "hecho" if (archivo.parent / CARPETA_MP3 / (archivo.stem + ".mp3")).is_file() else "espera"

    def _fila(self, archivo: Path, estado: str) -> None:
        icono, texto = ESTADOS[estado]
        orden, titulo = self.etiquetas.get(archivo.name, (0, archivo.stem))
        valores = (f"{icono}  {texto}", orden, titulo, archivo.name)
        if self.tabla.exists(archivo.name):
            self.tabla.item(archivo.name, values=valores, tags=(estado,))
        else:
            self.tabla.insert("", "end", iid=archivo.name, values=valores, tags=(estado,))

    def _poner(self, nombre: str, estado: str) -> None:
        archivo = next((a for a in self.archivos if a.name == nombre), None)
        if archivo is not None:
            self._fila(archivo, estado)
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
        self._fila(next(a for a in self.archivos if a.name == archivo), estado)
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
        total = max(1, len(self.archivos))
        m = re.match(r"^=== (.+) \((\d+)/(\d+)\) ===$", linea)
        if m:
            if self._actual:
                self._poner(self._actual, "listo")
            self._actual, i = m.group(1), int(m.group(2))
            self._poner(self._actual, "guardando" if self.modo == "mp3" else "convirtiendo")
            titulo = self.etiquetas.get(self._actual, (0, self._actual))[1]
            accion = "Guardando los datos de" if self.modo == "mp3" else "Convirtiendo"
            self.app.poner_estado(f"{accion} {titulo}", f"Tema {i} de {total}", (i - 1) / total)

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
        if not self.archivos:
            self.app.notificar("En esa carpeta no hay WAV ni MP3: elegí la carpeta 'masters' del paso 2 o una "
                               "carpeta con MP3.", "aviso")
            return
        disco, artista = self.disco.get().strip(), self.artista.get().strip()
        preferencias.guardar(disco=disco, artista=artista)
        mp3 = self.modo == "mp3"
        # '--opcion=valor': así un valor que empieza con '-' no se confunde con otra opción
        if mp3:
            args = ["etiquetar", str(self.archivos[0].parent)]
        else:
            args = ["convertir", str(carpeta), f"--kbps={CALIDADES_GUI.get(self.calidad.get(), CALIDADES[0])}"]
        args += [f"--disco={disco}", f"--artista={artista}"]
        for a in self.archivos:
            orden, titulo = self.etiquetas[a.name]
            args += [f"--orden={a.name}={orden}", f"--titulo={a.name}={titulo}"]
        for a in self.archivos:
            self._fila(a, "espera")
        self._actual = None
        destino, n = self.destino, len(self.archivos)

        def listo():
            for a in self.archivos:
                self._fila(a, "listo")
            self.btn_abrir.configure(state="normal")
            self.app.marcar_hecho(4)
            if mp3:
                texto = (f"Listo: datos cargados en {'el MP3' if n == 1 else f'los {n} MP3'} "
                         f"(título, número, disco y artista).")
            else:
                cuantos = "El MP3 quedó listo" if n == 1 else f"Los {n} MP3 quedaron listos"
                texto = f"{cuantos}, con sus datos de disco. Están en {destino}."
            self.app.notificar(texto, "exito", ("Abrir carpeta", self._abrir_mp3))

        self.app.escuchar_trabajo(self._leer_linea, self._al_terminar)
        self.app._correr(args, listo, estado="Guardando los datos…" if mp3 else "Preparando la conversión…")
