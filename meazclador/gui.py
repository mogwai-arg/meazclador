"""Ventana de meazclador: un recorrido en tres pasos (cortar, mezclar, escuchar y retocar)."""

from __future__ import annotations

import contextlib
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from . import __version__, preferencias
from .audio import Cancelado
from .estilo_ui import (ACENTO, BORDE, ELEVADA, EXITO, S1, S2, S3, S4, S6, S8, SOBRE_ACENTO, SUPERFICIE, TEXTO,
                        TEXTO_2, TEXTO_3, Banner, Desplazable, aplicar_tema)
from .gui_mezclar import PaginaMezclar
from .gui_retoque import PanelRetoque
from .gui_sesion import PanelSesion

PASOS = [
    ("Cortar", "la grabación larga",
     "Encontrá los temas dentro de la grabación completa, escuchalos y cortalos. "
     "¿Ya tenés los temas separados? Pasá al paso 2."),
    ("Mezclar", "y masterizar",
     "Reconoce cada micrófono y mezcla y masteriza todos los temas. Tal como viene ya suena bien."),
    ("Escuchar", "y retocar",
     "Ajustá lo que no te convenza y compará con la versión anterior. Cada retoque tarda segundos."),
]
HOVER_LATERAL = "#25272C"


class _Cola:
    """Archivo falso: lo que el programa imprime va a la ventana."""

    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, texto: str) -> int:
        self.q.put(texto)
        return len(texto)

    def flush(self) -> None:
        pass


def abrir_carpeta(ruta: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(ruta)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(ruta)])
    else:
        subprocess.Popen(["xdg-open", str(ruta)])


class BotonPaso(tk.Frame):
    """Un paso de la barra lateral: número (o ✓), nombre y estado. Todo el bloque es clickeable."""

    def __init__(self, padre, numero: int, titulo: str, subtitulo: str, fuentes, al_elegir):
        super().__init__(padre, background=SUPERFICIE, cursor="hand2", padx=S4, pady=S3, takefocus=1,
                         highlightthickness=1, highlightbackground=SUPERFICIE, highlightcolor=ACENTO)
        self.numero, self.al_elegir, self.fuentes = numero, al_elegir, fuentes
        # Teclado: Tab llega a cada paso (con un borde ámbar visible) y Enter o Espacio lo eligen.
        self.bind("<Return>", lambda _: self.al_elegir(self.numero))
        self.bind("<space>", lambda _: self.al_elegir(self.numero))
        self.actual, self.hecho = False, False
        self.barra = tk.Frame(self, width=3, background=SUPERFICIE)
        self.barra.pack(side="left", fill="y", padx=(0, S3))
        self.insignia = tk.Canvas(self, width=28, height=28, background=SUPERFICIE, highlightthickness=0)
        self.insignia.pack(side="left", padx=(0, S3))
        self.textos = tk.Frame(self, background=SUPERFICIE)
        self.textos.pack(side="left", fill="x")
        self.lbl_titulo = tk.Label(self.textos, text=titulo, font=fuentes.cuerpo_fuerte, anchor="w",
                                   background=SUPERFICIE, foreground=TEXTO)
        self.lbl_titulo.pack(anchor="w")
        self.lbl_sub = tk.Label(self.textos, text=subtitulo, font=fuentes.chica, anchor="w",
                                background=SUPERFICIE, foreground=TEXTO_3)
        self.lbl_sub.pack(anchor="w")
        for w in (self, self.barra, self.insignia, self.textos, self.lbl_titulo, self.lbl_sub):
            w.bind("<Button-1>", lambda _: self.al_elegir(self.numero))
            w.bind("<Enter>", lambda _: self._pintar(hover=True))
            w.bind("<Leave>", lambda _: self._pintar())
        self._pintar()

    def poner(self, actual: bool | None = None, hecho: bool | None = None) -> None:
        if actual is not None:
            self.actual = actual
        if hecho is not None:
            self.hecho = hecho
        self._pintar()

    def _pintar(self, hover: bool = False) -> None:
        fondo = ELEVADA if self.actual else (HOVER_LATERAL if hover else SUPERFICIE)
        for w in (self, self.insignia, self.textos, self.lbl_titulo, self.lbl_sub):
            w.configure(background=fondo)
        self.barra.configure(background=ACENTO if self.actual else fondo)
        self.lbl_titulo.configure(foreground=TEXTO if (self.actual or hover) else TEXTO_2)
        c = self.insignia
        c.delete("all")
        if self.hecho:
            c.create_oval(2, 2, 26, 26, fill=EXITO, outline="")
            c.create_text(14, 14, text="✓", fill=SOBRE_ACENTO, font=self.fuentes.cuerpo_fuerte)
        elif self.actual:
            c.create_oval(2, 2, 26, 26, fill=ACENTO, outline="")
            c.create_text(14, 14, text=str(self.numero), fill=SOBRE_ACENTO, font=self.fuentes.cuerpo_fuerte)
        else:
            c.create_oval(3, 3, 25, 25, outline=TEXTO_3, width=1.5)
            c.create_text(14, 14, text=str(self.numero), fill=TEXTO_2, font=self.fuentes.cuerpo_fuerte)


class App(ttk.Frame):
    def __init__(self, raiz: tk.Tk):
        super().__init__(raiz, style="TFrame")
        self.raiz = raiz
        self.fuentes = aplicar_tema(raiz)
        self.cola: queue.Queue = queue.Queue()
        self.trabajando = False
        self.proceso: subprocess.Popen | None = None
        self.cancelacion = threading.Event()
        self.oyente = None  # quien quiera leer, línea por línea, lo que imprime el trabajo en curso
        self._oyente_fin = None
        self._lineas_error: list[str] = []
        self.paso_actual = 1
        raiz.title("Meazclador")
        raiz.geometry("1180x840")
        raiz.minsize(1040, 740)
        self.grid(sticky="nsew")
        raiz.columnconfigure(0, weight=1)
        raiz.rowconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self._barra_lateral()
        principal = ttk.Frame(self, padding=(S8, S6, S8, S4))  # márgenes de la zona de trabajo
        principal.grid(row=0, column=1, sticky="nsew")
        principal.columnconfigure(0, weight=1)
        principal.rowconfigure(3, weight=1)

        self.titulo = ttk.Label(principal, style="Titulo.TLabel")
        self.titulo.grid(row=0, column=0, sticky="w")
        self.descripcion = ttk.Label(principal, style="Secundario.TLabel", wraplength=760, justify="left")
        self.descripcion.grid(row=1, column=0, sticky="w", pady=(S1, S3))
        self.banner = Banner(principal, self.fuentes)
        self.banner.grid(row=2, column=0, sticky="ew")

        self.paginas_marco = ttk.Frame(principal)
        self.paginas_marco.grid(row=3, column=0, sticky="nsew", pady=(S2, 0))
        self.paginas_marco.columnconfigure(0, weight=1)
        self.paginas_marco.rowconfigure(0, weight=1)
        self.contenedores = [Desplazable(self.paginas_marco) for _ in PASOS]
        for c in self.contenedores:
            c.grid(row=0, column=0, sticky="nsew")
        self.panel_sesion = PanelSesion(self.contenedores[0].interior, self)
        self.pagina_mezclar = PaginaMezclar(self.contenedores[1].interior, self)
        self.panel_retoque = PanelRetoque(self.contenedores[2].interior, self)
        self.paginas = [self.panel_sesion, self.pagina_mezclar, self.panel_retoque]
        for p in self.paginas:
            p.pack(fill="both", expand=True)

        self._pie(principal)
        tecla = "Command" if sys.platform == "darwin" else "Control"
        for i in range(1, len(PASOS) + 1):
            raiz.bind_all(f"<{tecla}-Key-{i}>", lambda _, n=i: self.ir_a(n))
        self._recordar()
        self.ir_a(2 if preferencias.cargar().get("temas") else 1)
        self._leer_cola()

    # ---------------------------------------------------------- estructura

    def _barra_lateral(self) -> None:
        lateral = tk.Frame(self, background=SUPERFICIE, width=248)
        lateral.grid(row=0, column=0, sticky="ns")
        lateral.pack_propagate(False)
        marca = tk.Frame(lateral, background=SUPERFICIE, padx=S6, pady=S6)
        marca.pack(fill="x")
        tk.Label(marca, text="MEAZCLADOR", font=self.fuentes.subtitulo, background=SUPERFICIE,
                 foreground=TEXTO).pack(anchor="w")
        tk.Label(marca, text="Mezcla automática para bandas", font=self.fuentes.chica, background=SUPERFICIE,
                 foreground=TEXTO_3).pack(anchor="w", pady=(S1, 0))
        tk.Frame(lateral, height=1, background=BORDE).pack(fill="x", padx=S6, pady=(0, S3))
        self.botones_paso: list[BotonPaso] = []
        for i, (titulo, sub, _) in enumerate(PASOS, 1):
            b = BotonPaso(lateral, i, titulo, sub, self.fuentes, self.ir_a)
            b.pack(fill="x")
            self.botones_paso.append(b)
        atajo = "⌘" if sys.platform == "darwin" else "Ctrl+"
        tk.Label(lateral, text=f"Atajos: {atajo}1, {atajo}2, {atajo}3", font=self.fuentes.chica,
                 background=SUPERFICIE, foreground=TEXTO_3).pack(anchor="w", padx=S6, pady=(S3, 0))
        tk.Label(lateral, text=f"versión {__version__}", font=self.fuentes.chica, background=SUPERFICIE,
                 foreground=TEXTO_3).pack(side="bottom", anchor="w", padx=S6, pady=S4)

    def _pie(self, padre) -> None:
        pie = tk.Frame(padre, background=SUPERFICIE, padx=S4, pady=S3)
        pie.grid(row=4, column=0, sticky="ew", pady=(S4, 0))
        pie.columnconfigure(0, weight=1)
        textos = tk.Frame(pie, background=SUPERFICIE)
        textos.grid(row=0, column=0, sticky="ew")
        self.estado = tk.StringVar(value="Listo.")
        self.estado_detalle = tk.StringVar(value="")
        tk.Label(textos, textvariable=self.estado, font=self.fuentes.cuerpo_fuerte, background=SUPERFICIE,
                 foreground=TEXTO, anchor="w").pack(anchor="w")
        tk.Label(textos, textvariable=self.estado_detalle, font=self.fuentes.chica, background=SUPERFICIE,
                 foreground=TEXTO_3, anchor="w").pack(anchor="w")
        self.progreso = ttk.Progressbar(pie, mode="determinate", length=220, maximum=1.0)
        self.progreso.grid(row=0, column=1, padx=S4)
        self.btn_cancelar = ttk.Button(pie, text="Cancelar", state="disabled", command=self.cancelar)
        self.btn_cancelar.grid(row=0, column=2)
        self.btn_detalles = ttk.Button(pie, text="Ver detalles", style="Tarjeta.Fantasma.TButton",
                                       command=self._alternar_detalles)
        self.btn_detalles.grid(row=0, column=3, padx=(S2, 0))
        self.registro = tk.Text(pie, height=9, state="disabled", wrap="word", font=self.fuentes.mono,
                                background="#121316", foreground=TEXTO_2, relief="flat", borderwidth=0,
                                padx=S3, pady=S2, insertbackground=TEXTO, highlightthickness=0)
        self._detalles_visibles = False

    def _alternar_detalles(self) -> None:
        self._detalles_visibles = not self._detalles_visibles
        if self._detalles_visibles:
            self.registro.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(S3, 0))
            self.btn_detalles.configure(text="Ocultar detalles")
        else:
            self.registro.grid_remove()
            self.btn_detalles.configure(text="Ver detalles")

    def _recordar(self) -> None:
        prefs = preferencias.cargar()
        if prefs.get("sesion"):
            self.panel_sesion.sesion.set(prefs["sesion"])
        if prefs.get("temas"):
            self.pagina_mezclar.carpeta.set(prefs["temas"])
            self.panel_retoque.carpeta.set(prefs["temas"])

    # ---------------------------------------------------------- navegación

    def ir_a(self, paso: int) -> None:
        self.paso_actual = paso
        titulo, sub, desc = PASOS[paso - 1]
        self.titulo.configure(text=f"{titulo} {sub}")
        self.descripcion.configure(text=desc)
        for i, b in enumerate(self.botones_paso, 1):
            b.poner(actual=i == paso)
        self.contenedores[paso - 1].tkraise()
        if self.banner.tipo != "error":
            self.banner.ocultar()
        al_mostrar = getattr(self.paginas[paso - 1], "al_mostrar", None)
        if al_mostrar:
            al_mostrar()

    def marcar_hecho(self, paso: int) -> None:
        self.botones_paso[paso - 1].poner(hecho=True)

    def ir_a_mezclar(self, carpeta_temas: Path) -> None:
        self.pagina_mezclar.carpeta.set(str(carpeta_temas))
        self.panel_retoque.carpeta.set(str(carpeta_temas))
        preferencias.guardar(temas=str(carpeta_temas))
        self.marcar_hecho(1)
        self.ir_a(2)

    def ir_a_retocar(self, carpeta: Path) -> None:
        self.panel_retoque.carpeta.set(str(carpeta))
        self.marcar_hecho(2)
        self.ir_a(3)

    @property
    def carpeta(self) -> tk.StringVar:  # compatibilidad: la carpeta del paso 2
        return self.pagina_mezclar.carpeta

    # ---------------------------------------------------------- avisos y estado

    def notificar(self, texto: str, tipo: str = "info", accion=None) -> None:
        self.banner.mostrar(texto, tipo, accion)

    def poner_estado(self, texto: str, detalle: str = "", progreso: float | None = None) -> None:
        self.estado.set(texto)
        self.estado_detalle.set(detalle)
        if progreso is None:
            if str(self.progreso["mode"]) != "indeterminate":
                self.progreso.configure(mode="indeterminate", maximum=100)
                self.progreso.start(12)
        else:
            if str(self.progreso["mode"]) != "determinate":
                self.progreso.stop()
                self.progreso.configure(mode="determinate", maximum=1.0)
            self.progreso["value"] = progreso

    def _log(self, texto: str) -> None:
        self.registro.configure(state="normal")
        self.registro.insert("end", texto)
        self.registro.see("end")
        self.registro.configure(state="disabled")
        for linea in texto.splitlines():
            linea = linea.strip()
            if not linea:
                continue
            if linea.lower().startswith(("error", "traceback")):
                self._lineas_error.append(linea)
            if self.oyente:
                self.oyente(linea)
            elif self.trabajando:
                self.estado_detalle.set(linea[:120])

    def _leer_cola(self) -> None:
        try:
            while True:
                item = self.cola.get_nowait()
                if isinstance(item, tuple):  # ("fin", código, callback) desde el hilo de trabajo
                    self._fin(item[1], item[2])
                else:
                    self._log(item)
        except queue.Empty:
            pass
        self.after(100, self._leer_cola)

    # ---------------------------------------------------------- trabajos

    def _botones_trabajo(self) -> list:
        botones = []
        for p in self.paginas:
            botones += p.botones_trabajo()
        return botones

    @staticmethod
    def _comando(args: list[str]) -> list[str]:
        """Cómo lanzarse a sí mismo como proceso aparte (en el ejecutable o desde Python)."""
        if getattr(sys, "frozen", False):
            return [sys.executable, *args]
        return [sys.executable, "-m", "meazclador.app", *args]

    def escuchar_trabajo(self, al_leer_linea, al_terminar=None) -> None:
        """Para el próximo trabajo: recibir cada línea que imprime y saber cómo terminó (código)."""
        self.oyente = al_leer_linea
        self._oyente_fin = al_terminar

    def _correr(self, tarea, al_terminar=None, estado: str = "Trabajando…") -> None:
        """Corre un trabajo en segundo plano sin congelar la ventana.

        - Lista de argumentos: se lanza como proceso aparte (así 'Cancelar' lo corta en el acto).
        - Función: corre en un hilo; recibe un callback `cancelar()`, y al_terminar recibe lo que devolvió.
        """
        if self.trabajando:
            return
        self.trabajando = True
        self._lineas_error = []
        self.cancelacion.clear()
        for b in self._botones_trabajo():
            b.configure(state="disabled")
        self.btn_cancelar.configure(state="normal")
        self.poner_estado(estado)
        if not callable(tarea):
            self._log("\n▶ " + " ".join(tarea) + "\n")

        def en_proceso() -> int:
            opciones = {}
            if sys.platform.startswith("win"):
                opciones["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
            self.proceso = subprocess.Popen(
                self._comando(tarea), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}, **opciones)
            for linea in self.proceso.stdout:
                self.cola.put(linea)
            return self.proceso.wait()

        def trabajo():
            resultado, codigo = None, 1
            try:
                if callable(tarea):
                    with contextlib.redirect_stdout(_Cola(self.cola)), contextlib.redirect_stderr(_Cola(self.cola)):
                        resultado, codigo = tarea(self.cancelacion.is_set), 0
                else:
                    codigo = en_proceso()
            except Cancelado:
                pass
            except Exception as e:  # que un error nunca cuelgue la ventana
                self.cola.put(f"Error: {e}\n")
            if self.cancelacion.is_set():
                codigo = -1
            listo = (lambda: al_terminar(resultado)) if (al_terminar and callable(tarea)) else al_terminar
            self.cola.put(("fin", codigo, listo))  # tkinter sólo se toca desde el hilo principal

        threading.Thread(target=trabajo, daemon=True).start()

    def cancelar(self) -> None:
        self.cancelacion.set()
        if self.proceso and self.proceso.poll() is None:
            self.proceso.kill()
        self._log("\n✖ Cancelando...\n")
        self.poner_estado("Cancelando…")

    def _fin(self, codigo: int, al_terminar) -> None:
        self.trabajando = False
        self.proceso = None
        fin, self._oyente_fin, self.oyente = self._oyente_fin, None, None
        if fin:
            fin(codigo)
        self.progreso.stop()
        self.progreso.configure(mode="determinate", maximum=1.0)
        self.progreso["value"] = 0
        self.btn_cancelar.configure(state="disabled")
        for b in self._botones_trabajo():
            b.configure(state="normal")
        for p in self.paginas:
            actualizar = getattr(p, "actualizar_botones", None)
            if actualizar:
                actualizar()
        if codigo == -1:
            self.poner_estado("Cancelado.", "", 0)
            self._log("✖ Cancelado. Lo que se estaba haciendo quedó a medias; podés volver a empezar.\n")
            self.notificar("Cancelado. Lo que se estaba haciendo quedó a medias; podés volver a empezar "
                           "cuando quieras.", "aviso")
        elif codigo == 0:
            self.poner_estado("Listo.", "", 0)
            if al_terminar:
                al_terminar()
        else:
            self.poner_estado("Algo salió mal.", "", 0)
            motivo = self._lineas_error[-1] if self._lineas_error else "Mirá los detalles para saber qué pasó."
            self.notificar(f"No se pudo terminar. {motivo}", "error",
                           ("Ver detalles", lambda: self._detalles_visibles or self._alternar_detalles()))

    def _carpeta_valida(self, var: tk.StringVar) -> Path | None:
        ruta = Path(var.get().strip())
        if not var.get().strip() or not ruta.is_dir():
            self.notificar("Primero elegí una carpeta (botón 'Elegir…').", "aviso")
            return None
        return ruta


def main() -> int:
    raiz = tk.Tk()
    App(raiz)
    raiz.mainloop()
    return 0
