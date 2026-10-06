"""Pestaña 1 de la ventana: ver, escuchar y ajustar los temas de una sesión larga antes de cortar."""

from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import numpy as np

from .mezcla import listar_pistas
from .reproductor import Reproductor
from .sesion import Tema, a_reloj, detectar_temas, energia, escribir_lista, fragmento, info_pistas

ESCUCHA_S = 12  # duración de cada fragmento de escucha
COLOR_TEMA = "#cfe3f7"
COLOR_TEMA_ELEGIDO = "#8fc1ee"
COLOR_NIVEL = "#3b4a5a"
COLOR_MARCA = "#1f6fd1"
COLOR_CABEZAL = "#d62828"


class PanelSesion(ttk.Frame):
    def __init__(self, padre, app):
        super().__init__(padre, padding=10)
        self.app = app
        self.reproductor = Reproductor()
        self.archivos: list[Path] = []
        self.nivel: np.ndarray | None = None
        self.duracion = 0.0
        self.temas: list[Tema] = []
        self.umbral = 0.0
        self.marca: float | None = None
        self.editado = False

        self.columnconfigure(1, weight=1)
        self.rowconfigure(5, weight=1)
        ttk.Label(self, wraplength=700, justify="left", text=(
            "1) Elegí la carpeta con las pistas de la grabación completa y tocá 'Analizar'. "
            "2) En el mapa, cada franja celeste es un tema. Hacé clic en cualquier punto del mapa "
            "para escuchar desde ahí. 3) Si junta o parte temas, mové la sensibilidad. "
            "4) Ajustá los bordes escuchando el inicio y el final de cada tema, y cortá."
        )).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        self.sesion = tk.StringVar()
        app._fila_carpeta(self, 1, "Carpeta de la sesión:", self.sesion)

        fila = ttk.Frame(self)
        fila.grid(row=2, column=0, columnspan=3, sticky="ew", pady=4)
        fila.columnconfigure(1, weight=1)
        ttk.Label(fila, text="Sensibilidad:").grid(row=0, column=0, sticky="w")
        self.sensibilidad = tk.DoubleVar(value=0.45)
        escala = ttk.Scale(fila, from_=0.2, to=0.8, variable=self.sensibilidad, command=lambda _: self._redetectar())
        escala.grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Label(fila, text="← une temas · separa más →", foreground="gray").grid(row=0, column=2)
        ttk.Label(fila, text="   Tema más corto (s):").grid(row=0, column=3)
        self.min_tema = tk.IntVar(value=60)
        ttk.Spinbox(fila, from_=10, to=600, increment=10, textvariable=self.min_tema, width=5,
                    command=self._redetectar).grid(row=0, column=4, padx=4)
        self.btn_analizar = ttk.Button(fila, text="🔍  Analizar", command=self.analizar)
        self.btn_analizar.grid(row=0, column=5, padx=(8, 0))

        self.mapa = tk.Canvas(self, height=130, background="white", highlightthickness=1,
                              highlightbackground="#bbb", cursor="hand2")
        self.mapa.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(6, 2))
        self.mapa.bind("<Configure>", lambda _: self._dibujar())
        self.mapa.bind("<Button-1>", self._clic_mapa)
        self.ayuda_mapa = tk.StringVar(value="Analizá una sesión para ver el mapa.")
        ttk.Label(self, textvariable=self.ayuda_mapa, foreground="gray").grid(row=4, column=0, columnspan=3, sticky="w")

        tabla = ttk.Frame(self)
        tabla.grid(row=5, column=0, columnspan=3, sticky="nsew", pady=(6, 0))
        tabla.columnconfigure(0, weight=1)
        tabla.rowconfigure(0, weight=1)
        self.lista = ttk.Treeview(tabla, columns=("n", "nombre", "inicio", "fin", "dur"), show="headings",
                                  height=6, selectmode="browse")
        for col, titulo, ancho in (("n", "#", 40), ("nombre", "Nombre (doble clic para cambiar)", 300),
                                   ("inicio", "Inicio", 80), ("fin", "Fin", 80), ("dur", "Duración", 80)):
            self.lista.heading(col, text=titulo)
            self.lista.column(col, width=ancho, anchor="w" if col == "nombre" else "center",
                              stretch=col == "nombre")
        self.lista.grid(row=0, column=0, sticky="nsew")
        barra = ttk.Scrollbar(tabla, orient="vertical", command=self.lista.yview)
        barra.grid(row=0, column=1, sticky="ns")
        self.lista.configure(yscrollcommand=barra.set)
        self.lista.bind("<<TreeviewSelect>>", lambda _: self._dibujar())
        self.lista.bind("<Double-1>", lambda _: self.renombrar())

        botones = ttk.Frame(self)
        botones.grid(row=6, column=0, columnspan=3, sticky="w", pady=(6, 0))
        grupos = [
            ("Escuchar:", [("▶ Inicio", self.escuchar_inicio), ("▶ Final", self.escuchar_final),
                           ("⏹ Parar", self.parar)]),
            ("Inicio:", [("−1 s", lambda: self.mover("inicio", -1)), ("+1 s", lambda: self.mover("inicio", 1)),
                         ("◆ a la marca", lambda: self.a_la_marca("inicio"))]),
            ("Fin:", [("−1 s", lambda: self.mover("fin", -1)), ("+1 s", lambda: self.mover("fin", 1)),
                      ("◆ a la marca", lambda: self.a_la_marca("fin"))]),
        ]
        for fila_b, (titulo, acciones) in enumerate(grupos):
            ttk.Label(botones, text=titulo, width=9).grid(row=fila_b, column=0, sticky="w")
            for col, (texto, cmd) in enumerate(acciones, 1):
                ttk.Button(botones, text=texto, command=cmd).grid(row=fila_b, column=col, padx=2, pady=1, sticky="ew")
        ttk.Label(botones, text="Tema:", width=9).grid(row=3, column=0, sticky="w")
        for col, (texto, cmd) in enumerate((("Renombrar", self.renombrar), ("✂ Dividir en la marca", self.dividir),
                                            ("Unir con el siguiente", self.unir), ("🗑 Borrar", self.borrar)), 1):
            ttk.Button(botones, text=texto, command=cmd).grid(row=3, column=col, padx=2, pady=1, sticky="ew")

        self.btn_cortar = ttk.Button(self, text="✂  Cortar temas", command=self.cortar)
        self.btn_cortar.grid(row=7, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self._cabezal()

    # ---------------------------------------------------------- análisis

    def analizar(self) -> None:
        sesion = self.app._carpeta_valida(self.sesion)
        if not sesion:
            return
        archivos = listar_pistas(sesion)
        if not archivos:
            messagebox.showwarning("Meazclador", "No hay archivos de audio en esa carpeta.")
            return

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
            print(f"{len(self.temas)} temas detectados. Hacé clic en el mapa para escuchar.")

        self.app._correr(trabajo, listo)

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

    # ---------------------------------------------------------- tabla y mapa

    def _actualizar_lista(self, elegir: int | None = None) -> None:
        anterior = self._elegido()
        self.lista.delete(*self.lista.get_children())
        for i, t in enumerate(self.temas):
            self.lista.insert("", "end", iid=str(i), values=(i + 1, t.nombre, a_reloj(t.inicio), a_reloj(t.fin),
                                                             a_reloj(t.duracion)))
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
        if self.nivel is None or ancho < 10:
            return
        abajo = alto - 16  # espacio para la escala de tiempo
        elegido = self._elegido()
        for i, t in enumerate(self.temas):
            color = COLOR_TEMA_ELEGIDO if i == elegido else COLOR_TEMA
            c.create_rectangle(self._x(t.inicio), 0, self._x(t.fin), abajo, fill=color, outline="")
            c.create_text(self._x(t.inicio) + 4, 3, text=str(i + 1), anchor="nw", font=("TkDefaultFont", 9, "bold"))

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
        c.create_line(0, y_umbral, ancho, y_umbral, fill="#e09f3e", dash=(4, 3))

        paso = 60 if self.duracion <= 15 * 60 else 300
        for s in np.arange(0, self.duracion, paso):
            x = self._x(s)
            c.create_line(x, abajo, x, abajo + 4, fill="#888")
            c.create_text(x + 2, abajo + 3, text=a_reloj(s), anchor="nw", fill="#666", font=("TkDefaultFont", 8))

        if self.marca is not None:
            x = self._x(self.marca)
            c.create_line(x, 0, x, abajo, fill=COLOR_MARCA, width=2)
            c.create_text(x + 3, abajo - 12, text=f"◆ {a_reloj(self.marca)}", anchor="w", fill=COLOR_MARCA,
                          font=("TkDefaultFont", 8, "bold"))
        self.ayuda_mapa.set(f"Sesión de {a_reloj(self.duracion)} · {len(self.temas)} temas · "
                            "clic en el mapa = poner la marca ◆ y escuchar desde ahí · línea naranja = umbral")

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
            messagebox.showerror("Meazclador", f"No pude leer el fragmento: {e}")
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
            messagebox.showinfo("Meazclador", "Primero hacé clic en el mapa para poner la marca ◆ donde querés el borde.")
            return
        t = self.temas[i]
        if borde == "inicio" and self.marca < t.fin - 1:
            t.inicio = self.marca
        elif borde == "fin" and self.marca > t.inicio + 1:
            t.fin = self.marca
        else:
            messagebox.showinfo("Meazclador", "La marca quedó del lado equivocado de ese tema.")
            return
        self._editar(i)

    def renombrar(self) -> None:
        i = self._elegido()
        if i is None:
            return
        nombre = simpledialog.askstring("Meazclador", "Nombre del tema:", initialvalue=self.temas[i].nombre,
                                        parent=self)
        if nombre and nombre.strip():
            self.temas[i].nombre = nombre.strip()
            self._editar(i)

    def dividir(self) -> None:
        i = self._elegido()
        if i is None or self.marca is None or not (self.temas[i].inicio + 1 < self.marca < self.temas[i].fin - 1):
            messagebox.showinfo("Meazclador", "Poné la marca ◆ (clic en el mapa) adentro del tema que querés dividir.")
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
            messagebox.showinfo("Meazclador", "Primero tocá 'Analizar' para encontrar los temas.")
            return
        self.reproductor.parar()
        destino = sesion / "temas"
        destino.mkdir(exist_ok=True)
        lista = destino / "temas.txt"
        escribir_lista(sorted(self.temas, key=lambda t: t.inicio), lista)

        def listo():
            self.app.carpeta.set(str(destino))
            self.app.pestanas.select(1)
            messagebox.showinfo("Meazclador", "Temas cortados. Ahora podés mezclarlos en la pestaña 2.")

        self.app._correr(["cortar", str(sesion), "--cortes", str(lista)], listo)

