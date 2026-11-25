# -*- coding: utf-8 -*-
"""Coisas que os arquivos de teste dividem."""
import tkinter as tk

import pytest


@pytest.fixture(scope="session")
def raiz():
    """Um unico Tk escondido para a sessao inteira de testes.

    Criar o Tk, destrui-lo e criar outro no mesmo processo falhou de vez em
    quando (os testes das janelas foram pulados sem aviso). Com um so, isso nao
    acontece. Se o computador nao abre o Tk, os testes das janelas sao pulados,
    com o motivo no resumo (-ra)."""
    try:
        r = tk.Tk()
    except tk.TclError as erro:
        pytest.skip("sem Tk neste computador: %s" % erro)
    r.withdraw()
    yield r
    r.destroy()
