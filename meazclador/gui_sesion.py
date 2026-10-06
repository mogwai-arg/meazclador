"""Paso 1 de la ventana: ver, escuchar y ajustar los temas de una sesión larga antes de cortar."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import numpy as np

from . import preferencias
from .estilo_ui import ACENTO, S1, S2, S3, S4, S6, SUPERFICIE, TEXTO, TEXTO_2, TEXTO_3, CampoRuta, Tarjeta, deslizador
from .mezcla import listar_pistas
from .reproductor import Reproductor
from .sesion import Tema, a_reloj, detectar_temas, energia, escribir_lista, fragmento, info_pistas

ESCUCHA_S = 12  # duración de cada fragmento de escucha
COLOR_TEMA = "#2A2620"  # franja de un tema: ámbar muy apagado sobre la superficie
COLOR_TEMA_ELEGIDO = "#4A3A1E"
COLOR_NIVEL = "#6B717B"
COLOR_UMBRAL = "#8C6A2C"
COLOR_MARCA = TEXTO
COLOR_CABEZAL = ACENTO


class PanelSesion(ttk.Frame):
    def __init__(self, padre, app):
        super().__init__(padre)
        self.app = app
        self.reproductor = Reproductor()
        self.archivos: list[Path] = []
        self.nivel: np.ndarray | None = None
        self.duracion = 0.0
        self.temas: list[Tema] = []
        self.umbral = 0.0
        self.marca: float | None = None
        self.editado = False
        self._editor: ttk.Entry | None = None
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # --- la grabación
        origen = Tarjeta(self)
        origen.grid(row=0, column=0, sticky="ew")
        origen.columnconfigure(0, weight=1)
        self.sesion = tk.StringVar()
        CampoRuta(origen, "Carpeta de la grabación completa (un WAV por micrófono)",
                  self.sesion).grid(row=0, column=0, sticky="ew")
        self.btn_analizar = ttk.Button(origen, text="Analizar", style="Primario.TButton", command=self.analizar)
        self.btn_analizar.grid(row=0, column=1, sticky="s", padx=(S4, 0))

        # --- el mapa
        mapa = Tarjeta(self)
        mapa.grid(row=1, column=0, sticky="ew", pady=(S4, 0))
        mapa.columnconfigure(0, weight=1)
        cabecera = ttk.Frame(mapa, style="Superficie.TFrame")
        cabecera.grid(row=0, column=0, sticky="ew", pady=(0, S2))
        ttk.Label(cabecera, text="Mapa de la sesión", style="Tarjeta.Subtitulo.TLabel").pack(side="left")
        self.ayuda_mapa = tk.StringVar(value="")
        ttk.Label(cabecera, textvariable=self.ayuda_mapa, style="Tarjeta.Pista.TLabel").pack(side="left", padx=S3)
        self.mapa = tk.Canvas(mapa, height=120, background=SUPERFICIE, highlightthickness=0, cursor="hand2")
        self.mapa.grid(row=1, column=0, sticky="ew")
        self.mapa.bind("<Configure>", lambda _: self._dibujar())
        self.mapa.bind("<Button-1>", self._clic_mapa)

        ajustes = ttk.Frame(mapa, style="Superficie.TFrame")
        ajustes.grid(row=2, column=0, sticky="ew", pady=(S3, 0))
        ttk.Label(ajustes, text="Sensibilidad", style="Tarjeta.Secundario.TLabel").pack(side="left")
        self.sensibilidad = tk.DoubleVar(value=0.45)
        escala = deslizador(ajustes, self.sensibilidad, 0.2, 0.8, lambda _: self._redetectar())
        escala.configure(length=220)
        escala.pack(side="left", padx=(S3, S2))
        ttk.Label(ajustes, text="une temas  ·  separa más", style="Tarjeta.Pista.TLabel").pack(side="left")
        self.min_tema = tk.IntVar(value=60)
        ttk.Spinbox(ajustes, from_=10, to=600, increment=10, textvariable=self.min_tema, width=5,
                    command=self._redetectar).pack(side="right")
        ttk.Label(ajustes, text="Tema más corto (s)", style="Tarjeta.Secundario.TLabel").pack(side="right", padx=S2)

        # --- los temas encontrados
        tabla = Tarjeta(self)
        tabla.grid(row=2, column=0, sticky="nsew", pady=(S4, 0))
        tabla.columnconfigure(0, weight=1)
        tabla.rowconfigure(1, weight=1)
        cabecera_temas = ttk.Frame(tabla, style="Superficie.TFrame")
        cabecera_temas.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, S2))
        self.titulo_temas = tk.StringVar(value="Temas")
        ttk.Label(cabecera_temas, textvariable=self.titulo_temas, style="Tarjeta.Subtitulo.TLabel").pack(side="left")
        self.btn_cortar = ttk.Button(cabecera_temas, text="Cortar temas", command=self.cortar, state="disabled")
        self.btn_cortar.pack(side="right")
        self.lista = ttk.Treeview(tabla, columns=("n", "nombre", "inicio", "fin", "dur"), show="headings",
                                  height=5, selectmode="browse")
        for col, titulo, ancho, alin in (("n", "#", 44, "e"), ("nombre", "NOMBRE  (doble clic para cambiarlo)", 320, "w"),
                                         ("inicio", "INICIO", 80, "e"), ("fin", "FIN", 80, "e"),
                                         ("dur", "DURACIÓN", 90, "e")):
            self.lista.heading(col, text=titulo, anchor=alin)
            self.lista.column(col, width=ancho, anchor=alin, stretch=col == "nombre")
        self.lista.grid(row=1, column=0, sticky="nsew")
        barra = ttk.Scrollbar(tabla, orient="vertical", command=self.lista.yview)
        barra.grid(row=1, column=1, sticky="ns")
        self.lista.configure(yscrollcommand=barra.set)
        self.lista.bind("<<TreeviewSelect>>", lambda _: self._dibujar())
        self.lista.bind("<Double-1>", lambda _: self.renombrar())

        herramientas = ttk.Frame(tabla, style="Superficie.TFrame")
        herramientas.grid(row=2, column=0, columnspan=2, sticky="w", pady=(S2, 0))
        filas = [
            [("ESCUCHAR", [("▶ Inicio", self.escuchar_inicio), ("▶ Final", self.escuchar_final),
                           ("■ Parar", self.parar)]),
             ("INICIO", [("−1 s", lambda: self.mover("inicio", -1)), ("+1 s", lambda: self.mover("inicio", 1)),
                         ("◆ Marca", lambda: self.a_la_marca("inicio"))]),
             ("FIN", [("−1 s", lambda: self.mover("fin", -1)), ("+1 s", lambda: self.mover("fin", 1)),
                      ("◆ Marca", lambda: self.a_la_marca("fin"))])],
            [("TEMA", [("Renombrar", self.renombrar), ("Dividir en la marca", self.dividir),
                       ("Unir con el siguiente", self.unir), ("Borrar", self.borrar)])],
        ]
        for grupos in filas:
            fila = ttk.Frame(herramientas, style="Superficie.TFrame")
            fila.pack(anchor="w")
            for g, (titulo, acciones) in enumerate(grupos):
                ttk.Label(fila, text=titulo, style="Tarjeta.Pista.TLabel").pack(side="left",
                                                                               padx=(0 if g == 0 else S6, S1))
                for texto, cmd in acciones:
                    ttk.Button(fila, text=texto, style="Tarjeta.Fantasma.TButton", command=cmd).pack(side="left")
        self._cabezal()

    def botones_trabajo(self) -> list:
        return [self.btn_analizar, self.btn_cortar]

    def actualizar_botones(self) -> None:
        """Una sola acción destacada: 'Analizar' hasta que haya temas; después, 'Cortar'."""
        if self.temas:
            self.btn_analizar.configure(style="TButton", text="Volver a analizar")
            self.btn_cortar.configure(style="Primario.TButton", state="normal",
                                      text=f"✂  Cortar {len(self.temas)} tema{'s' if len(self.temas) != 1 else ''}")
        else:
            self.btn_analizar.configure(style="Primario.TButton", text="Analizar")
            self.btn_cortar.configure(style="TButton", state="disabled", text="Cortar temas")

    # ---------------------------------------------------------- análisis

    def analizar(self) -> None:
        sesion = self.app._carpeta_valida(self.sesion)
        if not sesion:
            return
        archivos = listar_pistas(sesion)
        if not archivos:
            self.app.notificar("En esa carpeta no hay archivos de audio (WAV, FLAC o AIFF). Elegí la carpeta "
                               "donde están las pistas de la grabación.", "aviso")
            return
        preferencias.guardar(sesion=str(sesion))

        def trabajo(cancelar):
            sr, duracion, avisos = info_pistas(archivos)
            print(f"{len(archivos)} pistas de {a_reloj(duracion)} a {sr} Hz.")
            for a in avisos:
                print(a)
            print("Escuchando la sesión (sólo se hace una vez; después la sensibilidad responde al instante)...")
            return archivos, duracion, energia(archivos, cancelar=cancelar)

        def listo(resultado):
            self.archivos, self.duracion, self.nivel = resultado
            self.editado = False
            self.marca = None
            self._redetectar(forzar=True)
            self.actualizar_botones()
            if self.temas:
                self.app.notificar(f"Encontré {len(self.temas)} temas. Hacé clic en el mapa para escuchar cualquier "
                                   "momento, ajustá los bordes si hace falta y cortá.", "exito")
            else:
                self.app.notificar("No encontré temas. Probá bajar 'Tema más corto' o mover la sensibilidad.",
                                   "aviso")

        self.app._correr(trabajo, listo, estado="Escuchando la grabación…")

    def _redetectar(self, forzar: bool = False) -> None:
        if self.nivel is None:
            return
        if self.editado and not forzar:
            if not messagebox.askyesno("Meazclador", "Cambiar la sensibilidad vuelve a detectar los temas y "
                                       "se pierden los ajustes que hiciste a mano. ¿Seguir?"):
                return
            self.editado = False
        try:
            minimo = float(self.min_tema.get())
        except (tk.TclError, ValueError):
            return
        self.temas, self.umbral = detectar_temas(self.nivel, min_tema_s=minimo,
                                                 sensibilidad=self.sensibilidad.get())
        self._actualizar_lista()
        if not self.app.trabajando:
            self.actualizar_botones()

    # ---------------------------------------------------------- tabla y mapa

    def _actualizar_lista(self, elegir: int | None = None) -> None:
        anterior = self._elegido()
        self.lista.delete(*self.lista.get_children())
        for i, t in enumerate(self.temas):
            self.lista.insert("", "end", iid=str(i), values=(i + 1, t.nombre, a_reloj(t.inicio), a_reloj(t.fin),
                                                             a_reloj(t.duracion)))
        cuantos = len(self.temas)
        self.titulo_temas.set(f"{cuantos} tema{'s' if cuantos != 1 else ''} encontrados" if cuantos else "Temas")
        destino = elegir if elegir is not None else anterior
        if self.temas:
            destino = min(destino if destino is not None else 0, len(self.temas) - 1)
            self.lista.selection_set(str(destino))
            self.lista.see(str(destino))
        self._dibujar()

    def _elegido(self) -> int | None:
        sel = self.lista.selection()
        return int(sel[0]) if sel else None

    def _x(self, seg: float) -> float:
        return seg / max(self.duracion, 1e-9) * self.mapa.winfo_width()

    def _seg(self, x: float) -> float:
        return float(np.clip(x / max(self.mapa.winfo_width(), 1) * self.duracion, 0, self.duracion))

    def _dibujar(self) -> None:
        c = self.mapa
        c.delete("all")
        ancho, alto = c.winfo_width(), c.winfo_height()
        if ancho < 10:
            return
        if self.nivel is None:
            c.create_text(ancho / 2, alto / 2 - 10, text="Elegí la carpeta de la grabación y tocá Analizar",
                          fill=TEXTO_2, font=self.app.fuentes.cuerpo_fuerte)
            c.create_text(ancho / 2, alto / 2 + 12, text="Acá vas a ver toda la sesión, con cada tema marcado.",
                          fill=TEXTO_3, font=self.app.fuentes.chica)
            self.ayuda_mapa.set("")
            return
        abajo = alto - 16  # espacio para la escala de tiempo
        elegido = self._elegido()
        for i, t in enumerate(self.temas):
            color = COLOR_TEMA_ELEGIDO if i == elegido else COLOR_TEMA
            c.create_rectangle(self._x(t.inicio), 0, self._x(t.fin), abajo, fill=color, outline="")
            c.create_text(self._x(t.inicio) + 6, 4, text=str(i + 1), anchor="nw", fill=ACENTO if i == elegido
                          else TEXTO_2, font=self.app.fuentes.cuerpo_fuerte)

        # Nivel de toda la banda: un valor por píxel (el máximo del tramo).
        bordes = np.linspace(0, len(self.nivel), ancho + 1).astype(int)
        valores = np.array([self.nivel[a:max(b, a + 1)].max() for a, b in zip(bordes[:-1], bordes[1:])])
        piso, techo = np.percentile(self.nivel, 5), float(self.nivel.max())
        alturas = np.clip((valores - piso) / max(techo - piso, 1e-9), 0, 1) * (abajo - 16)
        puntos = [0, abajo]
        for x, h in enumerate(alturas):
            puntos += [x, abajo - h]
        puntos += [ancho, abajo]
        c.create_polygon(puntos, fill=COLOR_NIVEL, outline="")
        y_umbral = abajo - np.clip((self.umbral - piso) / max(techo - piso, 1e-9), 0, 1) * (abajo - 16)
        c.create_line(0, y_umbral, ancho, y_umbral, fill=COLOR_UMBRAL, dash=(4, 3))

        paso = 60 if self.duracion <= 15 * 60 else 300
        for s in np.arange(0, self.duracion, paso):
            x = self._x(s)
            c.create_line(x, abajo, x, abajo + 4, fill=TEXTO_3)
            c.create_text(x + 3, abajo + 3, text=a_reloj(s), anchor="nw", fill=TEXTO_3, font=self.app.fuentes.chica)

        if self.marca is not None:
            x = self._x(self.marca)
            c.create_line(x, 0, x, abajo, fill=COLOR_MARCA, width=2)
            c.create_text(x + 4, abajo - 12, text=f"◆ {a_reloj(self.marca)}", anchor="w", fill=COLOR_MARCA,
                          font=self.app.fuentes.chica)
        self.ayuda_mapa.set(f"{a_reloj(self.duracion)} de grabación  ·  clic para escuchar desde ese punto")

    def _cabezal(self) -> None:
        """Línea roja que avanza mientras suena un fragmento."""
        self.mapa.delete("cabezal")
        pos = self.reproductor.posicion()
        if pos is not None and self.nivel is not None:
            x = self._x(pos)
            self.mapa.create_line(x, 0, x, self.mapa.winfo_height() - 16, fill=COLOR_CABEZAL, width=2, tags="cabezal")
        self.after(80, self._cabezal)

    # ---------------------------------------------------------- escuchar

    def _escuchar(self, desde: float, hasta: float) -> None:
        if not self.archivos:
            return
        desde, hasta = max(0.0, desde), min(self.duracion, hasta)
        if hasta <= desde:
            return
        try:
            audio, sr = fragmento(self.archivos, desde, hasta)
        except Exception as e:
            self.app.notificar(f"No pude leer ese fragmento de la grabación: {e}", "error")
            return
        aviso = self.reproductor.reproducir(audio, sr, desde)
        if aviso:
            self.app._log(aviso + "\n")

    def _clic_mapa(self, evento) -> None:
        if self.nivel is None:
            return
        self.marca = self._seg(evento.x)
        for i, t in enumerate(self.temas):
            if t.inicio <= self.marca <= t.fin:
                self.lista.selection_set(str(i))
                self.lista.see(str(i))
                break
        self._dibujar()
        self._escuchar(self.marca, self.marca + ESCUCHA_S)

    def escuchar_inicio(self) -> None:
        i = self._elegido()
        if i is not None:
            self._escuchar(self.temas[i].inicio - 2, self.temas[i].inicio + ESCUCHA_S)

    def escuchar_final(self) -> None:
        i = self._elegido()
        if i is not None:
            self._escuchar(self.temas[i].fin - ESCUCHA_S, self.temas[i].fin + 2)

    def parar(self) -> None:
        self.reproductor.parar()

    # ---------------------------------------------------------- editar

    def _editar(self, i: int) -> None:
        self.editado = True
        self._actualizar_lista(elegir=i)

    def mover(self, borde: str, segundos: float) -> None:
        i = self._elegido()
        if i is None:
            return
        t = self.temas[i]
        if borde == "inicio":
            t.inicio = float(np.clip(t.inicio + segundos, 0, t.fin - 1))
        else:
            t.fin = float(np.clip(t.fin + segundos, t.inicio + 1, self.duracion))
        self._editar(i)
        if borde == "inicio":
            self.escuchar_inicio()
        else:
            self.escuchar_final()

    def a_la_marca(self, borde: str) -> None:
        i = self._elegido()
        if i is None or self.marca is None:
            self.app.notificar("Primero hacé clic en el mapa para poner la marca ◆ donde querés el borde.", "info")
            return
        t = self.temas[i]
        if borde == "inicio" and self.marca < t.fin - 1:
            t.inicio = self.marca
        elif borde == "fin" and self.marca > t.inicio + 1:
            t.fin = self.marca
        else:
            self.app.notificar("La marca quedó del otro lado de ese tema: ponela adentro o del lado del borde "
                               "que querés mover.", "info")
            return
        self._editar(i)

    def renombrar(self, nombre: str | None = None) -> None:
        """Cambia el nombre del tema elegido. Sin nombre, abre un campo encima de la fila."""
        i = self._elegido()
        if i is None:
            return
        if nombre is not None:
            if nombre.strip():
                self.temas[i].nombre = nombre.strip()
                self._editar(i)
            return
        caja = self.lista.bbox(str(i), "nombre")
        if not caja:
            return
        x, y, ancho, alto = caja
        editor = ttk.Entry(self.lista)
        editor.insert(0, self.temas[i].nombre)
        editor.select_range(0, "end")
        editor.place(x=x, y=y, width=ancho, height=alto)
        editor.focus_set()
        self._editor = editor

        def terminar(guardar: bool) -> None:
            if self._editor is None:
                return
            texto = editor.get()
            self._editor = None
            editor.destroy()
            if guardar:
                self.renombrar(texto)

        editor.bind("<Return>", lambda _: terminar(True))
        editor.bind("<FocusOut>", lambda _: terminar(True))
        editor.bind("<Escape>", lambda _: terminar(False))

    def dividir(self) -> None:
        i = self._elegido()
        if i is None or self.marca is None or not (self.temas[i].inicio + 1 < self.marca < self.temas[i].fin - 1):
            self.app.notificar("Poné la marca ◆ (clic en el mapa) adentro del tema que querés dividir.", "info")
            return
        t = self.temas[i]
        self.temas.insert(i + 1, Tema(self.marca, t.fin, f"tema_{len(self.temas) + 1:02d}"))
        t.fin = self.marca
        self._editar(i)

    def unir(self) -> None:
        i = self._elegido()
        if i is None or i + 1 >= len(self.temas):
            return
        self.temas[i].fin = self.temas[i + 1].fin
        del self.temas[i + 1]
        self._editar(i)

    def borrar(self) -> None:
        i = self._elegido()
        if i is None:
            return
        del self.temas[i]
        self._editar(max(0, i - 1))

    # ---------------------------------------------------------- cortar

    def cortar(self) -> None:
        sesion = self.app._carpeta_valida(self.sesion)
        if not sesion:
            return
        if not self.temas:
            self.app.notificar("Primero tocá 'Analizar' para encontrar los temas.", "info")
            return
        self.reproductor.parar()
        destino = sesion / "temas"
        destino.mkdir(exist_ok=True)
        lista = destino / "temas.txt"
        escribir_lista(sorted(self.temas, key=lambda t: t.inicio), lista)

        cuantos = len(self.temas)

        def listo():
            self.app.ir_a_mezclar(destino)
            self.app.notificar(f"Listo: {cuantos} temas cortados en {destino}. Ahora mezclalos.", "exito")

        self.app._correr(["cortar", str(sesion), "--cortes", str(lista)], listo, estado="Cortando los temas…")

