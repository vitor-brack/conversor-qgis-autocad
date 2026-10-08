# -*- mode: python ; coding: utf-8 -*-
"""
Receita do PyInstaller.

Gera uma PASTA (nao um .exe unico) de proposito: o GDAL embutido tem ~100 MB de
DLLs e bancos de dados de projecao. No modo arquivo-unico tudo isso e extraido
para o disco a cada abertura, o que faz o programa demorar uns 10 segundos para
abrir toda vez. Em pasta, abre na hora.

Para gerar um .exe unico mesmo assim, troque ARQUIVO_UNICO para True.
"""

import os
import shutil

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ARQUIVO_UNICO = False

dados = collect_data_files("fiona") + collect_data_files("pyproj")
# ezdxf: hachuras com padrao e texto formatado. Os aceleradores compilados
# (ezdxf.acc) sao carregados de forma dinamica e precisam ser declarados; os
# arquivos de dados dele (fontes .pyx/.c, icones) nao servem em tempo de uso.
ocultos = (collect_submodules("fiona") + collect_submodules("pyproj")
           + collect_submodules("ezdxf.acc"))

a = Analysis(
    ["executar.py"],
    pathex=[],
    binaries=[],
    datas=dados,
    hiddenimports=ocultos,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Pesos mortos: nada disso e usado e sao centenas de MB.
    # (unittest NAO pode sair: o numpy, usado pelo ezdxf, o importa ao carregar)
    excludes=["matplotlib", "numpy.random._examples", "tkinter.test",
              "test", "pydoc_data", "pandas", "geopandas",
              "IPython", "jupyter", "notebook", "PIL", "PySide6", "PyQt5"],
    noarchive=False,
)
pyz = PYZ(a.pure)

nome = "ConversorGeo"

if ARQUIVO_UNICO:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name=nome, debug=False, bootloader_ignore_signals=False,
        strip=False, upx=False, console=False,
        disable_windowed_traceback=False, argv_emulation=False,
    )
else:
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name=nome, debug=False, bootloader_ignore_signals=False,
        strip=False, upx=False, console=False,
        disable_windowed_traceback=False, argv_emulation=False,
    )
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=nome)

# O manual de quem usa o programa vai ao lado do executavel. O COLLECT apaga a
# pasta de saida a cada build, entao a copia e feita aqui, depois dele.
shutil.copy2(os.path.join(SPECPATH, "COMO USAR.txt"),
             os.path.join(DISTPATH, "COMO USAR.txt") if ARQUIVO_UNICO
             else os.path.join(DISTPATH, nome, "COMO USAR.txt"))
