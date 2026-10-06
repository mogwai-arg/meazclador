"""Sistema visual de la ventana: colores, tipografía, espaciado y componentes reutilizables.

Estética oscura tipo estudio: un fondo casi negro (60 %), superficies un paso más claras (30 %)
y un único acento ámbar, como los LEDs de una consola (10 %). Todo el espaciado sale de una
escala de 4/8 px y hay sólo cuatro tamaños de letra.
"""

from __future__ import annotations

import sys
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, ttk

# ---------------------------------------------------------------- colores

FONDO = "#16171A"  # 60 %: lienzo
SUPERFICIE = "#1F2125"  # 30 %: tarjetas y barra lateral
ELEVADA = "#282A2F"  # campos, botones secundarios, hover
ELEVADA_HOVER = "#31343A"
ELEVADA_PRESION = "#3A3D44"
BORDE = "#34373D"
RIEL = "#33363C"  # riel de los deslizadores
TEXTO = "#ECEDEE"
TEXTO_2 = "#A9ACB2"  # secundario (7:1 sobre las tarjetas)
TEXTO_3 = "#9094A0"  # pistas y textos de ayuda (5.3:1 sobre las tarjetas)
ACENTO = "#F5A524"  # 10 %: la acción principal
ACENTO_HOVER = "#F8B84E"
ACENTO_PRESION = "#D98E12"
ACENTO_APAGADO = "#4A3D24"
SOBRE_ACENTO = "#1B1508"
SELECCION = "#3B3020"  # fila elegida: ámbar muy apagado
EXITO = "#5BC985"
EXITO_FONDO = "#1C2B22"
ERROR = "#EF6B67"
ERROR_FONDO = "#33201F"
AVISO_FONDO = "#33291A"

# ---------------------------------------------------------------- espaciado (escala de 4/8)

S1, S2, S3, S4, S6, S8 = 4, 8, 12, 16, 24, 32

# ---------------------------------------------------------------- tipografía


def _primera_disponible(candidatas: list[str], respaldo: str) -> str:
    try:
        disponibles = {f.lower() for f in tkfont.families()}
    except tk.TclError:
        return respaldo
    return next((c for c in candidatas if c.lower() in disponibles), respaldo)


class Fuentes:
    """Cuatro tamaños (escala ~1.25) y una monoespaciada para el detalle técnico."""

    def __init__(self) -> None:
        if sys.platform.startswith("win"):
            familia = _primera_disponible(["Segoe UI Variable Text", "Segoe UI"], "TkDefaultFont")
            mono = _primera_disponible(["Cascadia Mono", "Consolas"], "TkFixedFont")
        elif sys.platform == "darwin":
            familia = _primera_disponible(["SF Pro Text", "Helvetica Neue"], "TkDefaultFont")
            mono = _primera_disponible(["SF Mono", "Menlo"], "TkFixedFont")
        else:
            familia = _primera_disponible(["Inter", "Cantarell", "Noto Sans", "DejaVu Sans"], "TkDefaultFont")
            mono = _primera_disponible(["JetBrains Mono", "DejaVu Sans Mono"], "TkFixedFont")
        self.chica = tkfont.Font(family=familia, size=9)
        self.cuerpo = tkfont.Font(family=familia, size=10)
        self.cuerpo_fuerte = tkfont.Font(family=familia, size=10, weight="bold")
        self.subtitulo = tkfont.Font(family=familia, size=12, weight="bold")
        self.titulo = tkfont.Font(family=familia, size=17, weight="bold")
        self.mono = tkfont.Font(family=mono, size=9)


# ---------------------------------------------------------------- tema ttk


def aplicar_tema(raiz: tk.Tk) -> Fuentes:
    """Configura todos los widgets ttk con el sistema visual. Devuelve las fuentes."""
    fuentes = Fuentes()
    raiz.configure(background=FONDO)
    estilo = ttk.Style(raiz)
    estilo.theme_use("clam")

    estilo.configure(
        ".", background=FONDO, foreground=TEXTO, font=fuentes.cuerpo, bordercolor=BORDE,
        darkcolor=ELEVADA, lightcolor=ELEVADA, troughcolor=ELEVADA, focuscolor=ACENTO,
        selectbackground=SELECCION, selectforeground=TEXTO, fieldbackground=ELEVADA,
        insertcolor=TEXTO, arrowcolor=TEXTO_2, relief="flat",
    )
    estilo.map(".", foreground=[("disabled", TEXTO_3)])

    # Fondos
    estilo.configure("TFrame", background=FONDO)
    estilo.configure("Superficie.TFrame", background=SUPERFICIE)
    estilo.configure("Lateral.TFrame", background=SUPERFICIE)

    # Textos: una variante por tipo y por fondo (fondo o tarjeta)
    for fondo, prefijo in ((FONDO, ""), (SUPERFICIE, "Tarjeta.")):
        estilo.configure(f"{prefijo}TLabel", background=fondo, foreground=TEXTO, font=fuentes.cuerpo)
        estilo.configure(f"{prefijo}Fuerte.TLabel", background=fondo, foreground=TEXTO, font=fuentes.cuerpo_fuerte)
        estilo.configure(f"{prefijo}Secundario.TLabel", background=fondo, foreground=TEXTO_2, font=fuentes.cuerpo)
        estilo.configure(f"{prefijo}Pista.TLabel", background=fondo, foreground=TEXTO_3, font=fuentes.chica)
        estilo.configure(f"{prefijo}Subtitulo.TLabel", background=fondo, foreground=TEXTO, font=fuentes.subtitulo)
        estilo.configure(f"{prefijo}Titulo.TLabel", background=fondo, foreground=TEXTO, font=fuentes.titulo)
        estilo.configure(f"{prefijo}Exito.TLabel", background=fondo, foreground=EXITO, font=fuentes.cuerpo_fuerte)

    # Botones: secundario (por defecto), primario (ámbar), fantasma (sin caja)
    estilo.configure("TButton", background=ELEVADA, foreground=TEXTO, bordercolor=BORDE, lightcolor=ELEVADA,
                     darkcolor=ELEVADA, padding=(S4, S2), font=fuentes.cuerpo, focusthickness=1)
    estilo.map("TButton",
               background=[("disabled", SUPERFICIE), ("pressed", ELEVADA_PRESION), ("active", ELEVADA_HOVER)],
               lightcolor=[("pressed", ELEVADA_PRESION), ("active", ELEVADA_HOVER)],
               darkcolor=[("pressed", ELEVADA_PRESION), ("active", ELEVADA_HOVER)],
               bordercolor=[("focus", ACENTO)])
    estilo.configure("Primario.TButton", background=ACENTO, foreground=SOBRE_ACENTO, bordercolor=ACENTO,
                     lightcolor=ACENTO, darkcolor=ACENTO, padding=(S6, S3), font=fuentes.cuerpo_fuerte)
    estilo.map("Primario.TButton",
               background=[("disabled", ACENTO_APAGADO), ("pressed", ACENTO_PRESION), ("active", ACENTO_HOVER)],
               lightcolor=[("disabled", ACENTO_APAGADO), ("pressed", ACENTO_PRESION), ("active", ACENTO_HOVER)],
               darkcolor=[("disabled", ACENTO_APAGADO), ("pressed", ACENTO_PRESION), ("active", ACENTO_HOVER)],
               bordercolor=[("disabled", ACENTO_APAGADO), ("focus", TEXTO)],
               foreground=[("disabled", "#8E846F")])
    for fondo, prefijo in ((FONDO, ""), (SUPERFICIE, "Tarjeta.")):
        estilo.configure(f"{prefijo}Fantasma.TButton", background=fondo, foreground=TEXTO_2, bordercolor=fondo,
                         lightcolor=fondo, darkcolor=fondo, padding=(S3, S2), font=fuentes.cuerpo)
        estilo.map(f"{prefijo}Fantasma.TButton",
                   background=[("pressed", ELEVADA_PRESION), ("active", ELEVADA)],
                   lightcolor=[("pressed", ELEVADA_PRESION), ("active", ELEVADA)],
                   darkcolor=[("pressed", ELEVADA_PRESION), ("active", ELEVADA)],
                   foreground=[("disabled", TEXTO_3), ("active", TEXTO)],
                   bordercolor=[("focus", ACENTO)])

    # Campos
    for nombre in ("TEntry", "TSpinbox", "TCombobox"):
        estilo.configure(nombre, fieldbackground=ELEVADA, background=ELEVADA, foreground=TEXTO,
                         bordercolor=BORDE, lightcolor=ELEVADA, darkcolor=ELEVADA, padding=(S2, 6),
                         arrowcolor=TEXTO_2, insertcolor=TEXTO)
        estilo.map(nombre, bordercolor=[("focus", ACENTO)], lightcolor=[("focus", ELEVADA)],
                   fieldbackground=[("readonly", ELEVADA), ("disabled", SUPERFICIE)],
                   foreground=[("readonly", TEXTO), ("disabled", TEXTO_3)],
                   background=[("active", ELEVADA_HOVER)])
    raiz.option_add("*TCombobox*Listbox.background", ELEVADA)
    raiz.option_add("*TCombobox*Listbox.foreground", TEXTO)
    raiz.option_add("*TCombobox*Listbox.selectBackground", SELECCION)
    raiz.option_add("*TCombobox*Listbox.selectForeground", TEXTO)
    raiz.option_add("*TCombobox*Listbox.font", fuentes.cuerpo)
    raiz.option_add("*TCombobox*Listbox.borderWidth", 0)

    # Deslizadores, progreso, casillas, barras de desplazamiento
    for fondo, prefijo in ((FONDO, ""), (SUPERFICIE, "Tarjeta.")):
        estilo.configure(f"{prefijo}Horizontal.TScale", background=ACENTO, troughcolor=RIEL, bordercolor=fondo,
                         lightcolor=ACENTO, darkcolor=ACENTO, sliderthickness=14, sliderlength=14, gripcount=0)
        estilo.map(f"{prefijo}Horizontal.TScale", background=[("active", ACENTO_HOVER)])
        estilo.configure(f"{prefijo}TCheckbutton", background=fondo, foreground=TEXTO, indicatorbackground=ELEVADA,
                         indicatorforeground=SOBRE_ACENTO, indicatormargin=(0, 0, S2, 0), focuscolor=fondo)
        estilo.map(f"{prefijo}TCheckbutton", indicatorbackground=[("selected", ACENTO), ("active", ELEVADA_HOVER)],
                   background=[("active", fondo)])
    estilo.configure("Horizontal.TProgressbar", background=ACENTO, troughcolor=ELEVADA, bordercolor=SUPERFICIE,
                     lightcolor=ACENTO, darkcolor=ACENTO, thickness=6)
    estilo.configure("Vertical.TScrollbar", background=ELEVADA, troughcolor=SUPERFICIE, bordercolor=SUPERFICIE,
                     lightcolor=ELEVADA, darkcolor=ELEVADA, arrowcolor=TEXTO_3, gripcount=0, arrowsize=12)
    estilo.map("Vertical.TScrollbar", background=[("active", ELEVADA_HOVER)])

    # Tablas
    estilo.configure("Treeview", background=SUPERFICIE, fieldbackground=SUPERFICIE, foreground=TEXTO,
                     bordercolor=SUPERFICIE, lightcolor=SUPERFICIE, darkcolor=SUPERFICIE, rowheight=32,
                     font=fuentes.cuerpo, borderwidth=0)
    estilo.map("Treeview", background=[("selected", SELECCION)], foreground=[("selected", TEXTO)])
    estilo.configure("Treeview.Heading", background=SUPERFICIE, foreground=TEXTO_3, bordercolor=SUPERFICIE,
                     lightcolor=SUPERFICIE, darkcolor=SUPERFICIE, font=fuentes.chica, padding=(S2, S2), relief="flat")
    estilo.map("Treeview.Heading", background=[("active", SUPERFICIE)], foreground=[("active", TEXTO_2)])
    estilo.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])  # sin borde exterior
    return fuentes


# ---------------------------------------------------------------- componentes


class Tarjeta(ttk.Frame):
    """Superficie con relleno: agrupa contenido relacionado."""

    def __init__(self, padre, relleno: int = S4, **kw):
        super().__init__(padre, style="Superficie.TFrame", padding=relleno, **kw)


class Banner(tk.Frame):
    """Mensaje dentro de la pantalla (en lugar de ventanitas emergentes): ícono + texto + acción opcional."""

    TIPOS = {
        "info": (ELEVADA, TEXTO_2, "ℹ"),
        "exito": (EXITO_FONDO, EXITO, "✓"),
        "error": (ERROR_FONDO, ERROR, "!"),
        "aviso": (AVISO_FONDO, ACENTO, "!"),
    }

    def __init__(self, padre, fuentes: Fuentes):
        super().__init__(padre, background=FONDO)
        self.fuentes = fuentes
        self.texto = ""
        self.tipo = ""

    def mostrar(self, texto: str, tipo: str = "info", accion: tuple[str, callable] | None = None) -> None:
        for hijo in self.winfo_children():
            hijo.destroy()
        fondo, color, icono = self.TIPOS[tipo]
        self.texto, self.tipo = texto, tipo
        caja = tk.Frame(self, background=fondo, padx=S4, pady=S3)
        caja.pack(fill="x", pady=(0, S3))
        tk.Label(caja, text=icono, background=fondo, foreground=color, font=self.fuentes.subtitulo,
                 width=2).pack(side="left", anchor="n")
        tk.Label(caja, text=texto, background=fondo, foreground=TEXTO, font=self.fuentes.cuerpo,
                 justify="left", anchor="w", wraplength=640).pack(side="left", fill="x", expand=True, padx=(S2, S4))
        if accion:
            ttk.Button(caja, text=accion[0], command=accion[1]).pack(side="left", padx=(0, S2))
        cerrar = tk.Label(caja, text="✕", background=fondo, foreground=TEXTO_3, cursor="hand2",
                          font=self.fuentes.cuerpo)
        cerrar.pack(side="right", anchor="n")
        cerrar.bind("<Button-1>", lambda _: self.ocultar())

    def ocultar(self) -> None:
        for hijo in self.winfo_children():
            hijo.destroy()
        self.configure(height=1)  # sin esto, Tk deja el hueco del mensaje anterior
        self.texto, self.tipo = "", ""


class Plegable(ttk.Frame):
    """Sección que se abre y cierra (por ejemplo, 'Opciones avanzadas')."""

    def __init__(self, padre, titulo: str, abierto: bool = False, fondo: str = "fondo", al_abrir=None):
        super().__init__(padre, style="Superficie.TFrame" if fondo == "tarjeta" else "TFrame")
        self._titulo = titulo
        self._al_abrir = None
        prefijo = "Tarjeta." if fondo == "tarjeta" else ""
        self.boton = ttk.Button(self, style=f"{prefijo}Fantasma.TButton", command=self.alternar)
        self.boton.pack(anchor="w")
        self.cuerpo = ttk.Frame(self, style="Superficie.TFrame" if fondo == "tarjeta" else "TFrame")
        self.abierto = not abierto
        self.alternar()
        self._al_abrir = al_abrir

    def alternar(self) -> None:
        self.abierto = not self.abierto
        self.boton.configure(text=("▾  " if self.abierto else "▸  ") + self._titulo)
        if self.abierto:
            self.cuerpo.pack(fill="x", pady=(S2, 0))
            if self._al_abrir:
                self.after(60, self._al_abrir)  # que lo que se abrió quede a la vista
        else:
            self.cuerpo.pack_forget()


class CampoRuta(ttk.Frame):
    """Etiqueta arriba + campo + botón 'Elegir…' (carpeta o archivo)."""

    def __init__(self, padre, etiqueta: str, variable: tk.StringVar, archivo: bool = False,
                 fondo: str = "tarjeta", ayuda: str | None = None, ancho: int | None = None):
        prefijo = "Tarjeta." if fondo == "tarjeta" else ""
        super().__init__(padre, style="Superficie.TFrame" if fondo == "tarjeta" else "TFrame")
        self.columnconfigure(0, weight=1)
        if etiqueta:
            ttk.Label(self, text=etiqueta, style=f"{prefijo}Secundario.TLabel").grid(row=0, column=0, sticky="w",
                                                                                   pady=(0, S1))
        self.entrada = ttk.Entry(self, textvariable=variable, **({"width": ancho} if ancho else {}))
        self.entrada.grid(row=1, column=0, sticky="ew")

        def elegir():
            inicial = variable.get().strip() or str(Path.home())
            if archivo:
                r = filedialog.askopenfilename(initialdir=Path(inicial).parent if Path(inicial).is_file() else inicial,
                                               filetypes=[("Audio", "*.wav *.flac *.aif *.aiff"), ("Todos", "*.*")])
            else:
                r = filedialog.askdirectory(initialdir=inicial)
            if r:
                variable.set(r)

        ttk.Button(self, text="Elegir…", command=elegir).grid(row=1, column=1, padx=(S2, 0))
        if ayuda:
            ttk.Label(self, text=ayuda, style=f"{prefijo}Pista.TLabel").grid(row=2, column=0, columnspan=2,
                                                                            sticky="w", pady=(S1, 0))


def deslizador(padre, variable: tk.DoubleVar, desde: float, hasta: float, al_mover=None,
               fondo: str = "tarjeta") -> ttk.Scale:
    prefijo = "Tarjeta." if fondo == "tarjeta" else ""
    return ttk.Scale(padre, from_=desde, to=hasta, variable=variable, command=al_mover,
                     style=f"{prefijo}Horizontal.TScale")


class Desplazable(ttk.Frame):
    """Contenedor con desplazamiento vertical: si la pantalla no entra en la ventana (notebooks de
    768 px de alto), se baja con la rueda del mouse. La barra aparece sólo cuando hace falta."""

    def __init__(self, padre):
        super().__init__(padre)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.lienzo = tk.Canvas(self, background=FONDO, highlightthickness=0, borderwidth=0)
        self.lienzo.grid(row=0, column=0, sticky="nsew")
        self.barra = ttk.Scrollbar(self, orient="vertical", command=self.lienzo.yview)
        self.lienzo.configure(yscrollcommand=self.barra.set)
        self.interior = ttk.Frame(self.lienzo)
        self._ventana = self.lienzo.create_window(0, 0, window=self.interior, anchor="nw")
        self.interior.bind("<Configure>", lambda _: self._ajustar())
        self.lienzo.bind("<Configure>", lambda _: self._ajustar())
        self.bind_all("<MouseWheel>", self._rueda, add="+")
        self.bind_all("<Button-4>", lambda e: self._rueda(e, -1), add="+")
        self.bind_all("<Button-5>", lambda e: self._rueda(e, 1), add="+")

    def _ajustar(self) -> None:
        alto_interior = self.interior.winfo_reqheight()
        alto = self.lienzo.winfo_height()
        # El contenido ocupa todo el ancho y, si sobra lugar, todo el alto (para que las tablas crezcan).
        self.lienzo.itemconfigure(self._ventana, width=self.lienzo.winfo_width(), height=max(alto, alto_interior))
        self.lienzo.configure(scrollregion=(0, 0, self.lienzo.winfo_width(), max(alto, alto_interior)))
        if alto_interior > alto + 1:
            self.barra.grid(row=0, column=1, sticky="ns")
        else:
            self.barra.grid_remove()
            self.lienzo.yview_moveto(0)

    def _rueda(self, evento, direccion: int | None = None) -> None:
        if not self.winfo_ismapped() or not self.barra.winfo_ismapped():
            return
        x, y = self.winfo_pointerxy()
        if not (self.winfo_rootx() <= x <= self.winfo_rootx() + self.winfo_width()
                and self.winfo_rooty() <= y <= self.winfo_rooty() + self.winfo_height()):
            return
        if direccion is None:
            direccion = -1 if evento.delta > 0 else 1
        self.lienzo.yview_scroll(direccion * 3, "units")
