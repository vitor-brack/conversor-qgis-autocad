# -*- coding: utf-8 -*-
"""Arquivo que o PyInstaller empacota. Roda o programa a partir do pacote `conversor`."""

import multiprocessing
import sys

from conversor.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()   # evita a janela abrir varias vezes no .exe
    sys.exit(main())
