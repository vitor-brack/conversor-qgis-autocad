# -*- coding: utf-8 -*-
"""
O desenho grande: o botao "Ampliar desenho" deixa a previa ocupar a janela inteira.

Ampliado, somem os passos da conversao, a lista de camadas e o quadro "O que
aconteceu"; ficam o desenho, a linha de ferramentas e o resumo do que vai para a
conversao. "Voltar ao normal" (ou Esc) traz tudo de volta.

O desenho ocupa a altura toda da aba (antes parava na altura dos passos ao lado, e
ampliado ficava com 300 pixels de altura). Quando o tamanho do desenho muda, o que a
pessoa pediu para ver (o "Ver tudo", ou onde o zoom e o arrasto pararam) continua
inteiro e no centro: tela maior, desenho maior. Ir e voltar nao muda nada (antes cada
ida e volta encolhia o desenho a metade).
"""
import time
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace

import pytest

import gerar_camadas
from conversor import config, previa, previa_raster as pr


# ---------------------------------------------------------------------------
# a conta da vista (sem janela)
def test_regiao_visivel_e_o_pedaco_do_desenho_que_cabe_na_tela():
    vista = pr.Vista(2.0, 100.0, 300.0)       # 2 pixels por unidade, canto em (100, 300)
    assert pr.regiao_visivel(vista, 200, 100) == pytest.approx((100.0, 250.0, 200.0, 300.0))


# ---------------------------------------------------------------------------
# o painel
@pytest.fixture(scope="module")
def desenho(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("ampliar")
    dxf, _ = gerar_camadas.gerar(str(pasta / "d"))
    return dxf, previa.ler(dxf), pasta


@pytest.fixture
def painel(raiz, desenho):
    from conversor.gui_camadas import PainelCamadas
    avisos = []
    p = PainelCamadas(raiz, ao_ampliar=avisos.append)
    p.avisos = avisos
    p.definir_previa(desenho[1], dxf_pronto=desenho[0])
    raiz.update_idletasks()
    yield p
    p.destroy()


def esperar(raiz, condicao, segundos=15):
    fim = time.time() + segundos
    while time.time() < fim:
        raiz.update()
        if condicao():
            return True
        time.sleep(0.02)
    return False


def na_janela(widget):
    return bool(widget.winfo_manager())


def test_o_desenho_comeca_do_tamanho_normal(painel):
    assert painel.ampliado is False
    assert painel.botao_ampliar.cget("text") == "Ampliar desenho"
    assert na_janela(painel.arvore.master)


def test_ampliar_esconde_a_lista_e_deixa_o_desenho(painel):
    painel.botao_ampliar.invoke()
    assert painel.ampliado is True
    assert not na_janela(painel.arvore.master), "a lista de camadas sai"
    assert not na_janela(painel.campo_busca.master), "a busca sai"
    assert na_janela(painel.tela) and na_janela(painel.botao_ampliar)
    assert "Voltar ao normal" in painel.botao_ampliar.cget("text")
    assert painel.avisos == [True], "a aba e avisada para esconder os passos"


def test_voltar_ao_normal_traz_tudo_de_volta(painel):
    painel.botao_ampliar.invoke()
    painel.botao_ampliar.invoke()
    assert painel.ampliado is False
    assert na_janela(painel.arvore.master) and na_janela(painel.campo_busca.master)
    assert painel.botao_ampliar.cget("text") == "Ampliar desenho"
    assert painel.avisos == [True, False]


def apertar_esc(painel, raiz):
    # o Esc vale na janela toda (o foco pode estar no botao, no desenho...); numa janela
    # escondida o foco nao fica em nenhum lugar e a tecla se perde: da o foco a janela
    topo = painel.winfo_toplevel()
    topo.focus_force()
    raiz.update()
    topo.event_generate("<Escape>")
    raiz.update()


def test_esc_volta_ao_normal(painel, raiz):
    painel.botao_ampliar.invoke()
    apertar_esc(painel, raiz)
    assert painel.ampliado is False
    assert painel.avisos == [True, False]


def test_esc_sem_estar_ampliado_nao_faz_nada(painel, raiz):
    apertar_esc(painel, raiz)
    assert painel.ampliado is False and painel.avisos == []


def test_painel_fechado_ampliado_nao_deixa_o_esc_preso_na_janela(raiz, desenho):
    from conversor.gui_camadas import PainelCamadas
    p = PainelCamadas(raiz)
    p.definir_previa(desenho[1], dxf_pronto=desenho[0])
    p.botao_ampliar.invoke()
    p.destroy()
    assert not raiz.bind("<Escape>").strip(), raiz.bind("<Escape>")


def test_sair_do_desenho_volta_ao_normal(painel):
    # sem desenho (o arquivo trocou, deu erro...), nao pode ficar tudo escondido
    painel.botao_ampliar.invoke()
    painel.limpar()
    assert painel.ampliado is False
    assert painel.avisos == [True, False]


def redimensionar(painel, raiz, largura, altura):
    """O que acontece quando a janela muda o tamanho do desenho (o Tk escondido dos testes
    nao manda o evento sozinho)."""
    painel.tela.configure(width=largura, height=altura)
    painel._ao_redimensionar(SimpleNamespace(width=largura, height=altura))
    assert esperar(raiz, lambda: painel.imagem is not None
                   and painel.imagem.shape[:2] == (altura, largura))


def test_quando_o_desenho_cresce_a_mesma_regiao_aparece_maior(painel, raiz):
    antes_w, antes_h = painel.tamanho()
    vista = painel.vista
    centro = vista.para_desenho(antes_w / 2, antes_h / 2)
    escala = vista.escala
    redimensionar(painel, raiz, antes_w * 2, antes_h * 2)
    # pelo menos o dobro: a folga do "Ver tudo" em volta e de pixels fixos
    assert painel.vista.escala >= 2 * escala
    assert painel.vista.para_desenho(antes_w, antes_h) == pytest.approx(centro)


def test_ampliar_e_voltar_varias_vezes_nao_encolhe_o_desenho(painel, raiz):
    # o ampliado e largo e baixo; o normal, estreito: era isso que encolhia o desenho
    largura, altura = painel.tamanho()
    escala, canto = painel.vista.escala, (painel.vista.x0, painel.vista.y_topo)
    for _ in range(3):
        redimensionar(painel, raiz, largura * 3, altura)
        redimensionar(painel, raiz, largura, altura)
    assert painel.vista.escala == pytest.approx(escala)
    assert (painel.vista.x0, painel.vista.y_topo) == pytest.approx(canto)


def test_depois_do_zoom_ir_e_voltar_mostra_o_mesmo_pedaco(painel, raiz):
    largura, altura = painel.tamanho()
    painel._roda(SimpleNamespace(delta=120, x=largura // 3, y=altura // 3))
    painel._roda(SimpleNamespace(delta=120, x=largura // 3, y=altura // 3))
    assert esperar(raiz, lambda: painel._depois_render is None)
    escala, canto = painel.vista.escala, (painel.vista.x0, painel.vista.y_topo)
    redimensionar(painel, raiz, largura * 3, altura)
    redimensionar(painel, raiz, largura, altura)
    assert painel.vista.escala == pytest.approx(escala)
    assert (painel.vista.x0, painel.vista.y_topo) == pytest.approx(canto)


# ---------------------------------------------------------------------------
# a aba AutoCAD -> QGIS
class AppFalso:
    def __init__(self):
        self.cfg = dict(config.PADROES)
        self.registro = []

    def registrar(self, _texto):
        pass

    def mostrar_registro(self, mostrar):
        self.registro.append(mostrar)


@pytest.fixture
def aba(raiz, desenho):
    from conversor import gui
    app = AppFalso()
    a = gui.AbaCadParaQgis(raiz, app)
    a.app_falso = app
    a.entrada.insert(0, desenho[0])
    a.escolher_camadas.set(True)
    a._alternar_camadas()
    assert esperar(raiz, lambda: a.painel.estado == "pronto"), a.painel.estado
    yield a
    a.destroy()


def test_ampliado_os_passos_e_o_quadro_do_que_aconteceu_saem(aba):
    aba.painel.botao_ampliar.invoke()
    assert not na_janela(aba.entrada.master), "o passo 1 sai"
    assert not na_janela(aba.botao), "o botao de converter sai"
    assert na_janela(aba.painel)
    assert aba.app_falso.registro == [False]


def test_voltar_ao_normal_traz_os_passos_de_volta(aba):
    aba.painel.botao_ampliar.invoke()
    aba.painel.botao_ampliar.invoke()
    assert na_janela(aba.entrada.master) and na_janela(aba.botao)
    assert aba.app_falso.registro == [False, True]


@pytest.fixture
def aba_na_tela(raiz, desenho):
    """A aba numa area do tamanho que ela tem na tela do usuario (1920x1080, janela
    maximizada), dentro do Tk escondido: o Tk calcula onde cada coisa fica sem mostrar
    nada na tela."""
    from conversor import gui
    area = ttk.Frame(raiz)
    area.place(x=0, y=0, width=1900, height=970)
    a = gui.AbaCadParaQgis(area, AppFalso())
    a.pack(fill="both", expand=True)
    a.entrada.insert(0, desenho[0])
    a.escolher_camadas.set(True)
    a._alternar_camadas()
    assert esperar(raiz, lambda: a.painel.estado == "pronto"), a.painel.estado
    raiz.update()
    yield a
    area.destroy()


def fundo(widget):
    return widget.winfo_y() + widget.winfo_height()


def test_o_painel_vai_ate_embaixo_da_aba_e_nao_para_na_altura_dos_passos(aba_na_tela, raiz):
    aba = aba_na_tela
    assert fundo(aba.painel) >= aba.winfo_height() - 20, (
        "o painel para em %d; a aba vai ate %d" % (fundo(aba.painel), aba.winfo_height()))
    assert aba.painel.tela.winfo_height() > 400, "a altura que sobra vai para o desenho"


def test_ampliado_o_desenho_ocupa_a_altura_da_aba(aba_na_tela, raiz):
    aba = aba_na_tela
    aba.painel.botao_ampliar.invoke()
    raiz.update()
    tela = aba.painel.tela
    assert tela.winfo_width() > 1800
    assert tela.winfo_height() > aba.winfo_height() - 220, (
        "o desenho tem %d de altura numa aba de %d" % (tela.winfo_height(), aba.winfo_height()))


def test_desligar_a_escolha_de_camadas_ampliado_traz_os_passos_de_volta(aba):
    aba.painel.botao_ampliar.invoke()
    aba.escolher_camadas.set(False)
    aba._alternar_camadas()
    assert na_janela(aba.entrada.master) and na_janela(aba.botao)
    assert not na_janela(aba.painel)
    assert aba.painel.ampliado is False
