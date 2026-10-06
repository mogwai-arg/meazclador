"""Script que empaqueta PyInstaller (importa el paquete como tal, no como archivo suelto)."""

import sys

from meazclador.app import main

sys.exit(main())
