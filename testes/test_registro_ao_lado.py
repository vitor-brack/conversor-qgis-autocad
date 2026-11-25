# -*- coding: utf-8 -*-
"""
Com o desenho aberto ao lado dos passos (aba AutoCAD -> QGIS, "Escolher as camadas"), o
quadro "O que aconteceu" sai de baixo das abas, onde ocupava a largura toda da janela, e vai
para baixo dos passos, na coluna deles (onde sobrava espaco). O desenho fica com a altura toda
da janela. Na outra aba, ou com o desenho fechado, o quadro volta para baixo. Ampliado, ele
some, como antes.

A janela nasce escondida: nada aparece na tela de quem roda os testes.
"""
import time

import pytest

import gerar_camadas
from conversor import config


@pytest.fixture(scope="module")
def janela(tmp_path_factory):
    """Uma janela so para o arquivo: criar varios Tk no mesmo processo falha de vez em quando
    (ver conftest.py)."""
    tk = pytest.importorskip("tkinter")
    pasta = tmp_path_factory.mktemp("registro")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(config, "PASTA", str(pasta))
        mp.setattr(config, "ARQUIVO", str(pasta / "config.json"))
        original = tk.Tk.__init__

        def nasce_escondida(self, *args, **kwargs):
            original(self, *args, **kwargs)
            self.withdraw()

        mp.setattr(tk.Tk, "__init__", nasce_escondida)
        from conversor.gui import App
        try:
            j = App()
        except tk.TclError as erro:
            pytest.skip("sem ambiente grafico: %s" % erro)
        j.geometry("1400x960")
        j.dxf, _ = gerar_camadas.gerar(str(pasta / "d"))
        yield j                      # as preferencias de verdade ficam fora ate o fim
        j.destroy()


@pytest.fixture
def app(janela):
    """A janela como ela abre: desenho fechado, na primeira aba."""
    aba = janela.aba2
    if aba.painel.ampliado:
        aba.painel.ampliar(False)
    if aba.escolher_camadas.get():
        aba.escolher_camadas.set(False)
        aba._alternar_camadas()
    aba.entrada.delete(0, "end")
    janela._abas.select(janela.aba1)
    janela.update()
    return janela


def esperar(janela, condicao, segundos=15):
    fim = time.time() + segundos
    while time.time() < fim:
        janela.update()
        if condicao():
            return True
        time.sleep(0.02)
    return False


def abrir_o_desenho(app):
    aba = app.aba2
    app._abas.select(aba)
    aba.entrada.insert(0, app.dxf)
    aba.escolher_camadas.set(True)
    aba._alternar_camadas()
    assert esperar(app, lambda: aba.painel.estado == "pronto"), aba.painel.estado
    app.update()
    return aba


def onde_esta_o_registro(app):
    caixa = app._caixa_do_registro
    gerente = caixa.winfo_manager()
    if gerente == "grid":
        return "aba2" if caixa.grid_info().get("in") is app.aba2 else "grid fora da aba"
    return gerente or "escondido"


def test_sem_o_desenho_o_registro_fica_embaixo_das_abas(app):
    app.update()
    assert onde_esta_o_registro(app) == "pack"


def test_com_o_desenho_aberto_o_registro_vai_para_baixo_dos_passos(app):
    aba = abrir_o_desenho(app)
    assert onde_esta_o_registro(app) == "aba2"
    info = app._caixa_do_registro.grid_info()
    assert int(info["column"]) == 0 and int(info["row"]) == aba.linha_do_registro
    assert app._caixa_do_registro.winfo_y() > aba.botao.winfo_y(), "embaixo do CONVERTER"


def test_o_desenho_ganha_a_altura_que_era_do_registro(app):
    aba = abrir_o_desenho(app)
    ao_lado = aba.painel.tela.winfo_height()
    app.registro_ao_lado(None)                       # como era antes
    app.update()
    embaixo = aba.painel.tela.winfo_height()
    assert ao_lado > embaixo + 120, (embaixo, ao_lado)


def test_na_outra_aba_o_registro_volta_para_baixo(app):
    abrir_o_desenho(app)
    app._abas.select(app.aba1)
    app.update()
    assert onde_esta_o_registro(app) == "pack"
    app._abas.select(app.aba2)
    app.update()
    assert onde_esta_o_registro(app) == "aba2"


def test_ampliado_o_registro_some_e_volta_para_o_mesmo_lugar(app):
    aba = abrir_o_desenho(app)
    aba.painel.botao_ampliar.invoke()
    app.update()
    assert onde_esta_o_registro(app) == "escondido"
    assert aba.entrada.master.winfo_manager() == "", "os passos saem, como antes"
    aba.painel.botao_ampliar.invoke()
    app.update()
    assert onde_esta_o_registro(app) == "aba2"
    assert aba.entrada.master.winfo_manager() == "grid" and aba.botao.winfo_manager() == "grid"


def test_fechar_o_desenho_devolve_o_registro_para_baixo(app):
    aba = abrir_o_desenho(app)
    aba.escolher_camadas.set(False)
    aba._alternar_camadas()
    app.update()
    assert onde_esta_o_registro(app) == "pack"


def test_fechar_o_desenho_ampliado_devolve_o_registro_para_baixo(app):
    aba = abrir_o_desenho(app)
    aba.painel.botao_ampliar.invoke()
    aba.escolher_camadas.set(False)
    aba._alternar_camadas()
    app.update()
    assert onde_esta_o_registro(app) == "pack"
    assert aba.entrada.master.winfo_manager() == "grid"


def test_o_registro_continua_escrevendo(app):
    abrir_o_desenho(app)
    app.registrar("mensagem de teste")
    assert "mensagem de teste" in app.log.get("1.0", "end")
