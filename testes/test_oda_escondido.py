# -*- coding: utf-8 -*-
"""
O ODA File Converter e um programa de janela (Qt), nao de console: a flag CREATE_NO_WINDOW
nao esconde a janela dele. Quem abre um .dwg no programa nao pode ver o ODA aparecer.
O que esconde e pedir ao Windows, no STARTUPINFO, que a primeira janela do processo nasca
oculta (SW_HIDE).
"""
import os
import subprocess

import pytest

from conversor import dwg

pytestmark = pytest.mark.skipif(os.name != "nt", reason="STARTUPINFO e coisa do Windows")


@pytest.fixture
def chamada(monkeypatch):
    """Roda dwg._executar com o ODA e o subprocess de mentira: devolve o que foi pedido ao
    subprocess.Popen, sem abrir nenhuma janela."""
    capturado = {}

    class ProcessoFalso:
        def __init__(self, comando, **kwargs):
            capturado["comando"] = comando
            capturado.update(kwargs)

        def communicate(self, timeout=None):
            return b"", b""

    monkeypatch.setattr(dwg, "localizar_oda", lambda: r"C:\ODA\ODAFileConverter.exe")
    monkeypatch.setattr(dwg.subprocess, "Popen", ProcessoFalso)
    dwg._executar("entrada", "saida", "ACAD2004", "DXF", "*.DWG")
    return capturado


def test_pede_ao_windows_que_a_janela_do_oda_nasca_escondida(chamada):
    info = chamada.get("startupinfo")
    assert info is not None, "sem STARTUPINFO a janela do ODA aparece na tela"
    assert info.dwFlags & subprocess.STARTF_USESHOWWINDOW
    assert info.wShowWindow == subprocess.SW_HIDE


def test_continua_sem_janela_de_console(chamada):
    assert chamada["creationflags"] & subprocess.CREATE_NO_WINDOW


def test_o_comando_do_oda_nao_mudou(chamada):
    assert chamada["comando"] == [r"C:\ODA\ODAFileConverter.exe", "entrada", "saida",
                                  "ACAD2004", "DXF", "0", "1", "*.DWG"]


# ---------------------------------------------------------------------------------------
# Com o ODA de verdade: o Windows e quem diz se a janela chegou a ficar visivel.
# ---------------------------------------------------------------------------------------

def _vigiar_janelas_do_oda(parar, vistas):
    """Enquanto `parar` nao for acionado, anota em `vistas` {hwnd: algum_momento_visivel}
    de toda janela de um processo ODAFileConverter.exe. Nao captura a tela."""
    import ctypes
    from ctypes import wintypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [proto, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                    ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    exes = {}

    def exe_do_pid(pid):
        if pid not in exes:
            nome, h = "", kernel32.OpenProcess(0x1000, False, pid)
            if h:
                buf, n = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
                if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                    nome = os.path.basename(buf.value).lower()
                kernel32.CloseHandle(h)
            exes[pid] = nome
        return exes[pid]

    def janela(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if exe_do_pid(pid.value) == "odafileconverter.exe":
            vistas[hwnd] = vistas.get(hwnd, False) or bool(user32.IsWindowVisible(hwnd))
        return True

    funcao = proto(janela)
    while not parar.is_set():
        user32.EnumWindows(funcao, 0)
        parar.wait(0.003)


@pytest.mark.skipif(not dwg.disponivel(), reason="ODA File Converter nao instalado")
def test_o_oda_de_verdade_nunca_mostra_a_janela(tmp_path):
    import threading

    import ezdxf

    doc = ezdxf.new("R2010")
    for i in range(20000):               # o bastante para o ODA ficar vivo por um bom tempo
        doc.modelspace().add_line((i, 0), (i + 10, 10))
    dxf = tmp_path / "obra.dxf"
    doc.saveas(str(dxf))

    parar, vistas = threading.Event(), {}
    vigia = threading.Thread(target=_vigiar_janelas_do_oda, args=(parar, vistas), daemon=True)
    vigia.start()
    try:
        dwg.dxf_para_dwg(str(dxf), str(tmp_path / "obra.dwg"))
    finally:
        parar.set()
        vigia.join()

    if not vistas:
        pytest.skip("o vigia nao chegou a ver a janela do ODA (nada a conferir)")
    assert not any(vistas.values()), "a janela do ODA ficou visivel durante a conversao"
