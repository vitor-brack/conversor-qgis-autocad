# -*- coding: utf-8 -*-
"""
O painel de camadas: a lista com caixas de marcar e a previa do desenho.

Monta o painel num Tk escondido e mexe nele como a pessoa mexeria (marcar,
buscar, clicar no desenho). Pula se a maquina nao consegue abrir o Tk.

Como o painel funciona:
  - o desenho mostra TODAS as camadas que o AutoCAD mostra (e as desligadas, se a
    caixinha pedir); as marcadas ficam em negrito, na mesma cor;
  - clicar numa linha do desenho escolhe so aquela linha (as pecas que se encostam pelas
    pontas), nao a camada inteira nem a cor inteira; Ctrl soma outras. A camada inteira se
    marca na lista.
"""
import time
import tkinter as tk
from types import SimpleNamespace

import ezdxf
import numpy as np
import pytest

import gerar_camadas
from conversor import previa, previa_raster as pr

X0, Y0 = gerar_camadas.X0, gerar_camadas.Y0
AZUL = (0, 0, 255)


@pytest.fixture(scope="module")
def desenho(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("gui_camadas")
    dxf, _ = gerar_camadas.gerar(str(pasta / "d"))
    return dxf, previa.ler(dxf), pasta


@pytest.fixture
def painel(raiz, desenho):
    from conversor.gui_camadas import PainelCamadas
    p = PainelCamadas(raiz)
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


def evento(**campos):
    return SimpleNamespace(**campos)


def pixel_de(painel, x, y):
    """Onde um ponto do desenho cai na imagem da previa."""
    px, py = painel.vista.para_tela(x, y)
    return int(round(px)), int(round(py))


def ids_de(painel, chave):
    """Os ids no mapa de pixels de uma camada (todas as cores dela) ou de uma cor."""
    if isinstance(chave, tuple):
        return {painel.indice[chave] + 1}
    return {n + 1 for k, n in painel.indice.items() if k[0] == chave}


def pixels_da_camada(painel, chave):
    return int(np.isin(painel.ids, list(ids_de(painel, chave))).sum())


# ---------------------------------------------------------------------------
# a lista
def test_lista_so_as_camadas_que_o_autocad_mostra_e_abre_sem_nada_marcado(painel, desenho):
    p = desenho[1]
    assert painel.estado == "pronto"
    assert painel.nomes_na_lista() == [c.nome for c in p.camadas if not c.oculta], \
        "as desligadas ficam de fora, na ordem da previa -> %s" % painel.nomes_na_lista()
    assert painel.marcadas == set(), \
        "abre sem nada marcado: o negrito so diz algo se for o que a pessoa escolheu -> %s" % \
        sorted(painel.marcadas)
    assert "Nada escolhido" in painel.resumo.get() and "clique" in painel.resumo.get(), \
        "e o resumo diz o que fazer -> %r" % painel.resumo.get()


def test_caixinha_das_desligadas_comeca_desmarcada_e_traz_elas_para_a_lista(painel):
    assert painel.mostrar_ocultas.get() is False
    assert "Desligada" not in painel.nomes_na_lista() and "Congelada" not in painel.nomes_na_lista()
    painel.mostrar_ocultas.set(True)
    assert {"Desligada", "Congelada"} <= set(painel.nomes_na_lista())
    assert "Desligada" not in painel.marcadas, "aparecem desmarcadas: quem quiser, marca"


def test_desligar_a_caixinha_desmarca_as_escondidas_que_estavam_marcadas(painel):
    painel.mostrar_ocultas.set(True)
    painel.alternar("Desligada")
    assert "Desligada" in painel.marcadas
    painel.mostrar_ocultas.set(False)
    assert "Desligada" not in painel.marcadas, \
        "o que a lista nao mostra mais nao pode ir para a conversao"
    assert "desligada" in painel.detalhe.get().lower(), \
        "e a pessoa e avisada -> %r" % painel.detalhe.get()


def test_o_desenho_abre_todo_fino_porque_nada_esta_marcado(painel):
    assert pixels_da_camada(painel, "Visivel") > 0
    painel.alternar("Visivel")
    assert pixels_da_camada(painel, "Visivel") > 0
    assert "1 camada inteira" in painel.resumo.get(), painel.resumo.get()


def test_alternar_marca_e_desmarca_e_o_resumo_acompanha(painel):
    antes = len(painel.marcadas)
    painel.alternar("Carimbo")
    assert "Carimbo" in painel.marcadas and len(painel.marcadas) == antes + 1
    assert painel.estado_da_caixa("Carimbo") == "marcada"
    assert "Vai para a conversao: 1 camada inteira" in painel.resumo.get(), \
        "o resumo diz o que vai para a conversao -> %r" % painel.resumo.get()
    painel.alternar("Carimbo")
    assert "Carimbo" not in painel.marcadas


def test_marcar_todas_pega_tudo_o_que_tem_desenho_e_as_que_a_lista_mostra(painel, desenho):
    """Camada so de textos (como o Carimbo) tambem e marcada: textos, hachuras e figuras
    vao para a conversao pela camada marcada, entao ficar de fora era perder o texto."""
    painel.desmarcar_todas()
    assert painel.marcadas == set()
    painel.marcar_todas()
    assert "Carimbo" in painel.marcadas, "camada so de textos: %s" % sorted(painel.marcadas)
    assert painel.marcadas == {c.nome for c in desenho[1].camadas
                               if c.tem_desenho and not c.oculta}
    painel.mostrar_ocultas.set(True)
    painel.marcar_todas()
    assert painel.marcadas == {c.nome for c in desenho[1].camadas if c.tem_desenho}


def test_marcar_todas_leva_os_textos_para_a_conversao(painel, desenho):
    """O que a pessoa quer de 'Marcar todas': tudo, inclusive os textos, chega ao QGIS."""
    from conversor import convert
    dxf, _previa, pasta = desenho
    painel.desmarcar_todas()
    painel.marcar_todas()
    selecao = painel.selecao()
    saida = str(pasta / "marcar_todas.gpkg")
    convert.cad_para_qgis(dxf, saida, 31982, formato="GPKG", gerar_projeto=False,
                          camadas=selecao["camadas"], feicoes_escolhidas=selecao["feicoes"],
                          registrar=lambda *_: None)
    assert "Carimbo_Texto" in convert.listar_camadas(saida), \
        "os 3 textos da camada Carimbo -> %s" % convert.listar_camadas(saida)


def test_buscar_mostra_so_as_que_combinam_e_avisa_quando_nao_ha(painel):
    painel.filtrar("PONT")
    assert painel.nomes_na_lista() == ["Pontos"], "sem diferenciar maiuscula"
    assert painel.aviso_busca.get() == "", "achou: sem aviso"
    painel.filtrar("zzz")
    assert painel.nomes_na_lista() == []
    assert "zzz" in painel.aviso_busca.get(), \
        "nao achou: diz o que buscou e oferece limpar -> %r" % painel.aviso_busca.get()
    painel.filtrar("")
    assert len(painel.nomes_na_lista()) > 5, "limpar a busca traz tudo de volta"


def test_marcar_todas_com_busca_so_marca_as_visiveis_na_lista(painel):
    painel.desmarcar_todas()
    painel.filtrar("Vis")
    painel.marcar_todas()
    assert painel.marcadas == {"Visivel"}, "so o que a busca mostra -> %s" % painel.marcadas


def test_linha_da_camada_marcada_fica_em_negrito_na_lista(painel):
    painel.desmarcar_todas()
    painel.alternar("Pontos")
    assert "marcada" in painel.arvore.item(painel._iid["Pontos"], "tags")
    assert "marcada" not in painel.arvore.item(painel._iid["Visivel"], "tags")
    painel.alternar("Pontos")
    assert "marcada" not in painel.arvore.item(painel._iid["Pontos"], "tags")


# ---------------------------------------------------------------------------
# o desenho
def test_o_desenho_mostra_todas_as_camadas_ligadas_mesmo_desmarcadas(painel):
    painel.desmarcar_todas()
    assert pixels_da_camada(painel, "Visivel") > 0 and pixels_da_camada(painel, "Pontos") > 0, \
        "marcar e escolher o que levar; o desenho continua mostrando o que o AutoCAD mostra"
    assert painel.mensagem_do_desenho() == ""


def test_camada_desligada_so_aparece_no_desenho_com_a_caixinha(painel):
    assert pixels_da_camada(painel, "Desligada") == 0, "o AutoCAD nao a mostra"
    painel.mostrar_ocultas.set(True)
    assert pixels_da_camada(painel, "Desligada") > 0, "com a caixinha, aparece"
    painel.mostrar_ocultas.set(False)
    assert pixels_da_camada(painel, "Desligada") == 0


def test_camada_marcada_fica_em_negrito_no_desenho(painel):
    painel.desmarcar_todas()
    fina = pixels_da_camada(painel, "Visivel")
    painel.alternar("Visivel")
    grossa = pixels_da_camada(painel, "Visivel")
    assert grossa > 2 * fina, "marcada fica mais grossa -> %d contra %d pixels" % (grossa, fina)


def test_marcar_ou_escolher_na_lista_nao_troca_a_cor_da_camada(painel):
    # os pontos sao azuis no desenho. Azul de corrego nao pode virar outra cor
    painel.desmarcar_todas()
    painel.ver_tudo()
    x, y = pixel_de(painel, X0 + 50, Y0 + 20)
    assert tuple(painel.imagem[y, x]) == AZUL, "desmarcada: azul"
    painel.alternar("Pontos")
    assert tuple(painel.imagem[y, x]) == AZUL, "marcada: o mesmo azul, so mais grossa"
    painel.selecionar("Pontos")
    assert tuple(painel.imagem[y, x]) == AZUL, "escolhida na lista: o mesmo azul, com contorno"


def test_ver_tudo_enquadra_tudo_o_que_aparece(painel, desenho):
    painel.desmarcar_todas()
    painel.ver_tudo()
    exibidas = {c.nome for c in desenho[1].camadas if c.tem_geometria and not c.oculta}
    largura, altura = painel.tamanho()
    esperada = pr.ajustar(desenho[1].caixa_de(exibidas, com_ocultas=False), largura, altura)
    assert painel.vista.escala == pytest.approx(esperada.escala), \
        "enquadra as camadas ligadas, sem contar as escondidas"


def test_se_o_autocad_nao_mostra_nada_a_previa_explica_e_a_caixinha_resolve(raiz, tmp_path):
    from conversor.gui_camadas import PainelCamadas
    doc = ezdxf.new("R2010")
    doc.layers.add("A", color=3).freeze()
    doc.modelspace().add_line((0, 0), (10, 10), dxfattribs={"layer": "A"})
    caminho = str(tmp_path / "tudo_desligado.dxf")
    doc.saveas(caminho)
    p = PainelCamadas(raiz)
    try:
        p.definir_previa(previa.ler(caminho))
        assert "desligadas" in p.mensagem_do_desenho(), p.mensagem_do_desenho()
        p.mostrar_ocultas.set(True)
        assert p.mensagem_do_desenho() == "" and pixels_da_camada(p, "A") > 0
    finally:
        p.destroy()


# ---------------------------------------------------------------------------
# clicar no desenho escolhe a linha clicada
def escolhidas_de(painel):
    """[(camada, pecas)] das linhas escolhidas, em ordem, para os testes lerem de uma vez."""
    grupos = painel.previa.grupos
    return sorted((grupos[g].camada, grupos[g].pecas) for g in painel.escolhidas)


def ponto_de_clique(painel):
    return pixel_de(painel, X0 + 50, Y0 + 20)           # um dos tres pontos


def borda_de_clique(painel):
    return pixel_de(painel, X0 + 50, Y0 + 60)           # lado de cima do quadrado


def test_clique_escolhe_so_a_linha_clicada_e_nao_marca_a_camada(painel):
    painel.ver_tudo()
    painel.clicar(*borda_de_clique(painel))
    assert painel.marcadas == set(), "a camada nao e marcada -> %s" % painel.marcadas
    assert escolhidas_de(painel) == [("Visivel", 1)], escolhidas_de(painel)
    assert painel.destaque is None, "sem o contorno branco da camada inteira"
    assert "Visivel" in painel.detalhe.get(), \
        "o detalhe diz de que camada e a linha -> %r" % painel.detalhe.get()


def test_clique_simples_troca_a_escolha_e_tira_as_camadas_marcadas(painel):
    painel.ver_tudo()
    painel.alternar("Carimbo")
    painel.clicar(*ponto_de_clique(painel))
    assert painel.marcadas == set(), \
        "o clique simples escolhe so isto, e tira o que estava marcado -> %s" % painel.marcadas
    assert escolhidas_de(painel) == [("Pontos", 1)]
    painel.clicar(*borda_de_clique(painel))
    assert escolhidas_de(painel) == [("Visivel", 1)], "e troca a escolha anterior"
    painel.clicar(*borda_de_clique(painel))
    assert escolhidas_de(painel) == [("Visivel", 1)], "clicar na que ja e a unica nao muda nada"


def test_ctrl_soma_e_tira_linhas_sem_mexer_nas_camadas_marcadas(painel):
    painel.ver_tudo()
    painel.clicar(*ponto_de_clique(painel))
    painel.alternar("Carimbo")
    painel.clicar(*borda_de_clique(painel), ctrl=True)
    assert escolhidas_de(painel) == [("Pontos", 1), ("Visivel", 1)], "Ctrl soma"
    assert painel.marcadas == {"Carimbo"}, "e nao mexe nas camadas marcadas na lista"
    painel.clicar(*borda_de_clique(painel), ctrl=True)
    assert escolhidas_de(painel) == [("Pontos", 1)], "Ctrl em uma ja escolhida tira ela"


def test_a_lista_mostra_quantas_linhas_de_cada_camada_foram_escolhidas(painel):
    painel.ver_tudo()
    painel.clicar(*borda_de_clique(painel))
    assert painel.estado_da_caixa("Visivel") == "parcial", "a camada inteira nao, so parte"
    assert coluna(painel, "Visivel") == "1 linha escolhida", coluna(painel, "Visivel")
    assert "marcada" in painel.arvore.item(painel._iid["Visivel"], "tags"), "em negrito na lista"
    assert "marcada" not in painel.arvore.item(painel._iid["Pontos"], "tags")
    assert "1 linha escolhida" in painel.resumo.get(), painel.resumo.get()
    painel.clicar(*ponto_de_clique(painel), ctrl=True)
    assert "2 linhas escolhidas" in painel.resumo.get(), painel.resumo.get()
    assert "Nenhuma" not in painel.resumo.get()


def test_o_resumo_junta_as_camadas_marcadas_e_as_linhas_escolhidas(painel):
    painel.ver_tudo()
    painel.alternar("Carimbo")
    painel.clicar(*borda_de_clique(painel), ctrl=True)
    resumo = painel.resumo.get()
    assert resumo == "Vai para a conversao: 1 camada inteira e 1 linha escolhida no desenho.", \
        resumo


def test_clicar_no_vazio_nao_mexe_nas_escolhas_nem_nas_marcas(painel):
    painel.ver_tudo()
    painel.alternar("Carimbo")
    painel.clicar(*ponto_de_clique(painel), ctrl=True)
    marcadas, escolhidas = set(painel.marcadas), set(painel.escolhidas)
    painel.clicar(1, 1)
    assert painel.marcadas == marcadas and painel.escolhidas == escolhidas, \
        "um clique perdido nao apaga o que foi escolhido"
    assert painel.destaque is None


def test_clicar_numa_camada_desligada_com_a_caixinha_escolhe_a_linha_dela(painel):
    painel.mostrar_ocultas.set(True)
    painel.ver_tudo()
    x, y = pixel_de(painel, gerar_camadas.X0 + 100000 + 10, Y0 + 10)    # o ponto da Desligada
    painel.clicar(x, y)
    assert escolhidas_de(painel) == [("Desligada", 1)], escolhidas_de(painel)


def test_desligar_a_caixinha_tira_as_linhas_escolhidas_nas_camadas_desligadas(painel):
    painel.mostrar_ocultas.set(True)
    painel.ver_tudo()
    painel.clicar(*pixel_de(painel, gerar_camadas.X0 + 100000 + 10, Y0 + 10))
    assert len(painel.escolhidas) == 1
    painel.mostrar_ocultas.set(False)
    assert painel.escolhidas == set(), "o que a lista nao mostra mais nao pode ir para a conversao"
    assert "desligada" in painel.detalhe.get().lower(), \
        "e a pessoa e avisada -> %r" % painel.detalhe.get()


def test_desmarcar_todas_tambem_tira_as_linhas_escolhidas(painel):
    painel.ver_tudo()
    painel.clicar(*borda_de_clique(painel))
    painel.desmarcar_todas()
    assert painel.escolhidas == set() and painel.marcadas == set()
    assert "Nada escolhido" in painel.resumo.get(), painel.resumo.get()
    assert coluna(painel, "Visivel") == "" and painel.estado_da_caixa("Visivel") == "vazia"


def test_desenho_novo_comeca_sem_linhas_escolhidas(painel, desenho):
    painel.ver_tudo()
    painel.clicar(*borda_de_clique(painel))
    painel.definir_previa(desenho[1], dxf_pronto=desenho[0])
    assert painel.escolhidas == set()


def test_a_selecao_leva_as_feicoes_das_linhas_escolhidas(painel):
    painel.ver_tudo()
    painel.clicar(*borda_de_clique(painel))
    grupo = painel.previa.grupos[next(iter(painel.escolhidas))]
    sel = painel.selecao()
    assert sel["camadas"] == set(), "nenhuma camada inteira"
    assert sel["feicoes"] == set(grupo.fids) and len(sel["feicoes"]) == 1, sel["feicoes"]


def test_sem_linhas_escolhidas_a_selecao_nao_tem_feicoes(painel):
    assert painel.selecao()["feicoes"] == set()


# ---------------------------------------------------------------------------
# os caminhos do mouse (os mesmos que o Tk chama)
def test_arrastar_move_a_vista_e_nao_vira_clique(painel):
    painel.ver_tudo()
    marcadas = set(painel.marcadas)
    escolhidas = set(painel.escolhidas)
    x0 = painel.vista.x0
    painel._apertou(evento(x=100, y=100))
    painel._arrastou(evento(x=115, y=100))
    painel._arrastou(evento(x=130, y=100))
    painel._soltou(evento(x=130, y=100))
    assert painel.vista.x0 < x0, "arrastar 30 px para a direita leva o desenho para a direita"
    assert painel.destaque is None and painel.marcadas == marcadas, "e um arrasto nao e um clique"
    assert painel.escolhidas == escolhidas


def test_soltar_sem_mexer_e_um_clique_e_o_ctrl_do_teclado_soma(painel):
    painel.ver_tudo()
    x, y = pixel_de(painel, X0 + 50, Y0 + 20)
    painel._apertou(evento(x=x, y=y))
    painel._soltou(evento(x=x, y=y, state=0))
    assert escolhidas_de(painel) == [("Pontos", 1)]
    bx, by = pixel_de(painel, X0 + 50, Y0 + 60)
    painel._apertou(evento(x=bx, y=by))
    painel._soltou(evento(x=bx, y=by, state=0x0004))          # Control apertado
    assert escolhidas_de(painel) == [("Pontos", 1), ("Visivel", 1)]


def test_roda_do_mouse_aproxima_e_afasta(painel):
    painel.ver_tudo()
    escala = painel.vista.escala
    painel._roda(evento(delta=120, x=100, y=100))
    assert painel.vista.escala > escala, "para cima aproxima"
    painel._roda(evento(delta=-120, x=100, y=100))
    assert painel.vista.escala == pytest.approx(escala), "para baixo afasta, voltando ao que era"


def test_espaco_alterna_a_camada_selecionada(painel):
    painel.selecionar("Carimbo")
    assert "Carimbo" not in painel.marcadas
    painel._espaco(None)
    assert "Carimbo" in painel.marcadas
    painel._espaco(None)
    assert "Carimbo" not in painel.marcadas


def test_escolher_na_lista_mostra_o_que_a_camada_desligada_e(painel):
    painel.mostrar_ocultas.set(True)
    painel.selecionar("Desligada")
    assert painel.destaque == "Desligada" and "Desligada" not in painel.marcadas, \
        "da para ver o que ela e antes de marcar"
    assert "desligada no autocad" in painel.detalhe.get().lower(), \
        "o detalhe diz que ela esta desligada no AutoCAD -> %r" % painel.detalhe.get()


# ---------------------------------------------------------------------------
# as cores de cada camada ficam dentro dela
HEX_VERMELHO, HEX_AZUL, HEX_VERDE = "#ff0000", "#0000ff", "#00ff00"


@pytest.fixture
def painel_por_cor(raiz, tmp_path):
    """Camada A com linhas vermelhas e azuis, camada B de uma cor so."""
    from conversor.gui_camadas import PainelCamadas
    doc = ezdxf.new("R2010")
    doc.layers.add("A", color=3)
    doc.layers.add("B", color=3)
    msp = doc.modelspace()
    for y in (0, 5, 7):
        msp.add_line((0, y), (100, y), dxfattribs={"layer": "A", "color": 1})
    msp.add_line((0, 30), (100, 30), dxfattribs={"layer": "A", "color": 5})
    msp.add_line((0, 60), (100, 60), dxfattribs={"layer": "B"})
    caminho = str(tmp_path / "pc.dxf")
    doc.saveas(caminho)
    p = PainelCamadas(raiz)
    p.definir_previa(previa.ler(caminho))
    raiz.update_idletasks()
    yield p
    p.destroy()


def coluna(painel, chave, nome="vai"):
    """O que a lista mostra numa coluna ("conteudo": o que tem; "vai": o que vai para a
    conversao) da linha da camada ou da cor."""
    return painel.arvore.set(painel._iid[chave], nome)


def test_a_lista_e_das_camadas_e_as_cores_ficam_dentro_delas(painel_por_cor):
    p = painel_por_cor
    assert p.nomes_na_lista() == ["A", "B"]
    assert p.cores_na_lista("A") == [("A", HEX_VERMELHO), ("A", HEX_AZUL)], \
        "a cor com mais linhas primeiro -> %s" % p.cores_na_lista("A")
    assert p.cores_na_lista("B") == [], "camada de uma cor so nao tem o que abrir"
    assert p.arvore.item(p._iid[("A", HEX_AZUL)], "text") == "azul", "a cor pelo nome"
    assert not p.arvore.item(p._iid["A"], "open"), "fechada, ate a pessoa abrir"


def test_a_amostra_da_camada_mostra_as_cores_que_ela_tem(painel_por_cor):
    p = painel_por_cor
    assert p.cores_da_amostra("A") == [HEX_VERMELHO, HEX_AZUL]
    assert p.cores_da_amostra(("A", HEX_AZUL)) == [HEX_AZUL]
    assert p.cores_da_amostra("B") == [HEX_VERDE]


def test_a_opcao_de_separar_por_cor_comeca_desligada(painel_por_cor):
    assert painel_por_cor.separar_por_cor.get() is False


def test_marcar_uma_cor_deixa_a_camada_pela_metade(painel_por_cor):
    p = painel_por_cor
    p.alternar(("A", HEX_AZUL))
    assert p.estado_da_caixa(("A", HEX_AZUL)) == "marcada"
    assert p.estado_da_caixa("A") == "parcial"
    assert p.marcadas == set(), "a camada inteira, nao -> %s" % p.marcadas
    assert coluna(p, "A") == "so azul" and coluna(p, ("A", HEX_AZUL)) == "tudo"
    p.alternar(("A", HEX_VERMELHO))
    assert p.estado_da_caixa("A") == "marcada" and p.marcadas == {"A"}
    assert coluna(p, "A") == "tudo"


def test_a_caixa_da_camada_pela_metade_marca_tudo_e_depois_tira_tudo(painel_por_cor):
    p = painel_por_cor
    p.alternar(("A", HEX_AZUL))
    p.alternar("A")
    assert p.cores_marcadas == {("A", HEX_VERMELHO), ("A", HEX_AZUL)}, p.cores_marcadas
    p.alternar("A")
    assert p.cores_marcadas == set() and p.estado_da_caixa("A") == "vazia"
    assert coluna(p, "A") == ""


def test_linha_clicada_deixa_a_camada_e_a_cor_pela_metade(painel_por_cor):
    p = painel_por_cor
    p.ver_tudo()
    p.clicar(*pixel_de(p, 50, 30))                    # a linha azul de A
    assert p.estado_da_caixa("A") == "parcial"
    assert p.estado_da_caixa(("A", HEX_AZUL)) == "parcial"
    assert p.estado_da_caixa(("A", HEX_VERMELHO)) == "vazia"
    assert coluna(p, "A") == "1 linha escolhida", coluna(p, "A")
    assert coluna(p, ("A", HEX_AZUL)) == "1 linha escolhida"
    assert "marcada" in p.arvore.item(p._iid["A"], "tags"), "em negrito: vai para a conversao"


def test_desmarcar_a_camada_tambem_tira_as_linhas_clicadas_nela(painel_por_cor):
    p = painel_por_cor
    p.ver_tudo()
    p.clicar(*pixel_de(p, 50, 30))
    p.alternar("A")                                   # pela metade -> inteira
    assert p.estado_da_caixa("A") == "marcada"
    p.alternar("A")                                   # inteira -> nada dela
    assert p.escolhidas == set() and p.estado_da_caixa("A") == "vazia"


def test_clicar_no_desenho_escolhe_so_a_linha_e_nao_a_cor(painel_por_cor):
    # a camada A tem 3 linhas vermelhas e 1 azul: clicar em uma vermelha nao leva as tres
    p = painel_por_cor
    p.ver_tudo()
    p.clicar(*pixel_de(p, 50, 0))
    assert p.cores_marcadas == set(), "nem a cor, nem a camada: so a linha"
    assert escolhidas_de(p) == [("A", 1)]
    assert p.previa.grupos[next(iter(p.escolhidas))].cor == HEX_VERMELHO
    p.clicar(*pixel_de(p, 50, 30), ctrl=True)
    cores = sorted(p.previa.grupos[g].cor for g in p.escolhidas)
    assert cores == [HEX_AZUL, HEX_VERMELHO], "Ctrl soma a azul -> %s" % cores
    assert coluna(p, "A") == "2 linhas escolhidas"
    assert coluna(p, ("A", HEX_VERMELHO)) == "1 linha escolhida"


def test_a_opcao_de_separar_por_cor_nao_mexe_na_lista_nem_no_que_foi_escolhido(painel_por_cor):
    """Antes ela trocava a lista inteira: o zoom voltava ao desenho todo, o texto escolhido
    sumia do rodape e, com a camada marcada, o texto de outra cor ficava fino."""
    p = painel_por_cor
    p.ver_tudo()
    p.alternar(("A", HEX_AZUL))
    p.clicar(*pixel_de(p, 50, 60), ctrl=True)         # a linha de B
    p._roda(evento(delta=120, x=100, y=100))

    def foto():
        return (p.nomes_na_lista(), p.cores_na_lista("A"), set(p.cores_marcadas),
                set(p.escolhidas), p.detalhe.get(), p.resumo.get(),
                (p.vista.escala, p.vista.x0, p.vista.y_topo))
    antes = foto()
    p.separar_por_cor.set(True)
    assert foto() == antes
    p.separar_por_cor.set(False)
    assert foto() == antes


def test_a_selecao_filtra_a_cor_so_da_camada_pela_metade(painel_por_cor):
    p = painel_por_cor
    p.alternar(("A", HEX_AZUL))
    p.alternar("B")
    sel = p.selecao()
    assert sel["camadas"] == {"A", "B"}
    assert sel["cores"] == {"A": {HEX_AZUL}}, "B vai inteira, sem filtro -> %s" % sel["cores"]
    assert sel["separar_por_cor"] == set(), "a opcao de separar esta desligada"


def test_camada_inteira_nao_filtra_cor(painel_por_cor):
    p = painel_por_cor
    p.alternar("A")
    sel = p.selecao()
    assert sel["camadas"] == {"A"} and sel["cores"] is None and sel["separar_por_cor"] == set()


def test_com_a_opcao_a_camada_de_varias_cores_sai_uma_camada_por_cor(painel_por_cor):
    p = painel_por_cor
    p.alternar("A")
    p.alternar("B")
    p.separar_por_cor.set(True)
    sel = p.selecao()
    assert sel["cores"] is None
    assert sel["separar_por_cor"] == {"A"}, \
        "so A tem mais de uma cor: so ela sai dividida -> %s" % sel["separar_por_cor"]


def test_a_selecao_com_linhas_escolhidas_e_a_opcao_divide_a_camada_delas(painel_por_cor):
    p = painel_por_cor
    p.separar_por_cor.set(True)
    p.ver_tudo()
    p.clicar(*pixel_de(p, 50, 0))
    sel = p.selecao()
    assert sel["camadas"] == set() and sel["cores"] is None
    assert sel["separar_por_cor"] == {"A"}, \
        "A tem duas cores: as linhas escolhidas dela saem separadas por cor -> %s" % \
        sel["separar_por_cor"]
    assert len(sel["feicoes"]) == 1


def test_so_a_linha_escolhida_fica_em_negrito_no_desenho(painel_por_cor):
    p = painel_por_cor
    p.ver_tudo()
    antes = pixels_da_camada(p, "A")
    p.clicar(*pixel_de(p, 50, 0))
    x, y = pixel_de(p, 50, 0)
    x30, y30 = pixel_de(p, 50, 30)
    assert pixels_da_camada(p, "A") > antes, "a linha escolhida engrossou"
    assert p.ids[y + 1, x] in ids_de(p, "A"), "a escolhida: 3 pixels de espessura"
    assert p.ids[y30 + 1, x30] == 0, "as outras da mesma camada continuam finas"


def test_so_a_cor_marcada_fica_em_negrito(painel_por_cor):
    p = painel_por_cor
    fina = pixels_da_camada(p, ("A", HEX_AZUL))
    p.alternar(("A", HEX_AZUL))
    assert pixels_da_camada(p, ("A", HEX_AZUL)) > 2 * fina, "a azul engrossa"
    p.alternar(("A", HEX_AZUL))
    assert pixels_da_camada(p, ("A", HEX_AZUL)) == fina


def _tem_contorno(painel, x, y):
    px, py = pixel_de(painel, x, y)
    janela = painel.imagem[max(py - 4, 0):py + 5, max(px - 4, 0):px + 5].reshape(-1, 3)
    return any(tuple(int(v) for v in c) == pr.CONTORNO for c in janela)


def test_escolher_a_camada_na_lista_contorna_todas_as_cores_dela(painel_por_cor):
    p = painel_por_cor
    p.ver_tudo()
    p.selecionar("A")
    assert _tem_contorno(p, 50, 0) and _tem_contorno(p, 50, 30), "a vermelha e a azul"
    assert not _tem_contorno(p, 50, 60), "B nao"
    p.selecionar(("A", HEX_AZUL))
    assert _tem_contorno(p, 50, 30) and not _tem_contorno(p, 50, 0), "so a cor escolhida"


def converter_a_selecao(painel, tmp_path, nome):
    """Converte o DXF do painel_por_cor com o que o painel manda (como a aba faz) e devolve
    {camada de saida: [cor_cad de cada feicao]}."""
    import fiona
    from conversor import convert
    sel = painel.selecao()
    saida = str(tmp_path / nome)
    convert.cad_para_qgis(str(tmp_path / "pc.dxf"), saida, 31982, gerar_projeto=False,
                          registrar=lambda *_: None, camadas=sel["camadas"], cores=sel["cores"],
                          separar_por_cor=sel["separar_por_cor"])
    feicoes = {}
    for camada in convert.listar_camadas(saida):
        with fiona.open(saida, layer=camada) as f:
            feicoes[camada] = sorted(ft["properties"]["cor_cad"] for ft in f)
    return feicoes


def test_a_conversao_leva_so_a_cor_marcada_mesmo_sem_a_opcao(painel_por_cor, tmp_path):
    p = painel_por_cor
    p.alternar("B")
    p.alternar(("A", HEX_AZUL))
    assert converter_a_selecao(p, tmp_path, "so_azul.gpkg") == {
        "A_LineString": [HEX_AZUL], "B_LineString": ["#00ff00"]}, \
        "de A so a linha azul; B inteira, sem filtro"


def test_a_conversao_com_a_opcao_divide_so_a_camada_de_varias_cores(painel_por_cor, tmp_path):
    p = painel_por_cor
    p.alternar("A")
    p.alternar("B")
    p.separar_por_cor.set(True)
    assert converter_a_selecao(p, tmp_path, "dividido.gpkg") == {
        "A_vermelho_LineString": [HEX_VERMELHO] * 3, "A_azul_LineString": [HEX_AZUL],
        "B_LineString": ["#00ff00"]}
    p.alternar(("A", HEX_VERMELHO))                   # tira o vermelho: A fica so azul
    assert converter_a_selecao(p, tmp_path, "dividido_azul.gpkg") == {
        "A_azul_LineString": [HEX_AZUL], "B_LineString": ["#00ff00"]}


# ---------------------------------------------------------------------------
def _com_lixo(tmp_path):
    doc = ezdxf.new("R2010")
    doc.layers.add("CURVAS")
    msp = doc.modelspace()
    bom = [(448000 + 20 * i, 6743000 + 30 * (i % 7)) for i in range(120)]
    msp.add_lwpolyline(bom, dxfattribs={"layer": "CURVAS"})
    for _ in range(3):
        msp.add_lwpolyline([(0, 0), (0, 0)], dxfattribs={"layer": "CURVAS"})
    caminho = str(tmp_path / "lixo.dxf")
    doc.saveas(caminho)
    return caminho


def test_aviso_de_feicoes_longe_e_a_caixa_para_a_conversao(raiz, tmp_path):
    from conversor.gui_camadas import PainelCamadas
    p = PainelCamadas(raiz)
    try:
        lida = previa.ler(_com_lixo(tmp_path))
        p.definir_previa(lida, dxf_pronto=None)
        assert "3" in p.aviso_fora.get() and "km" in p.aviso_fora.get(), \
            "avisa quantas e a que distancia -> %r" % p.aviso_fora.get()
        assert p.selecao()["caixa"] == lida.caixa_area, "por padrao, deixa de fora"
        p.ignorar_fora.set(False)
        assert p.selecao()["caixa"] is None, "se a pessoa quiser, leva tudo"
    finally:
        p.destroy()


def test_sem_feicoes_longe_nao_ha_aviso(painel):
    assert painel.aviso_fora.get() == ""
    assert painel.selecao()["caixa"] is None


def test_selecao_leva_as_camadas_marcadas_e_o_dxf_pronto(painel, desenho):
    sel = painel.selecao()
    assert sel["camadas"] == painel.marcadas and sel["dxf"] == desenho[0]


# ---------------------------------------------------------------------------
# o desenho fica parado: os textos em volta mudam sem empurrar ele
@pytest.fixture
def painel_na_janela(raiz, desenho):
    """O painel num espaco de tamanho fixo, como na janela do programa: a altura que sobra vai
    para o desenho. (O tamanho vem do `place`, e nao da janela: a janela escondida dos testes
    nunca aparece, e o Windows deixa de aplicar o tamanho pedido a ela.)"""
    from conversor.gui_camadas import PainelCamadas
    p = PainelCamadas(raiz)
    p.place(x=0, y=0, width=620, height=900)   # estreito: as frases quebram
    p.definir_previa(desenho[1], dxf_pronto=desenho[0])
    raiz.update()
    assert p.tela.winfo_height() > 200, p.winfo_geometry()
    yield p
    p.destroy()


def altura_do_desenho(painel):
    painel.update()
    return painel.tela.winfo_height()


def test_marcar_a_primeira_caixinha_nao_muda_o_tamanho_do_desenho(painel_na_janela):
    p = painel_na_janela
    antes = altura_do_desenho(p)
    assert antes > 200
    primeira = p.nomes_na_lista()[0]
    p.alternar(primeira)
    assert altura_do_desenho(p) == antes, "a frase do resumo mudou e empurrou o desenho"
    p.alternar(primeira)
    assert altura_do_desenho(p) == antes


def test_o_detalhe_e_a_busca_nao_mudam_o_tamanho_do_desenho(painel_na_janela):
    p = painel_na_janela
    p.mostrar_ocultas.set(True)
    antes = altura_do_desenho(p)
    for nome in p.nomes_na_lista():
        p.selecionar(nome)                       # cada camada tem um detalhe de um tamanho
        assert altura_do_desenho(p) == antes, "detalhe de %s: %r" % (nome, p.detalhe.get())
    p.filtrar("zzz")
    assert "zzz" in p.aviso_busca.get()
    assert altura_do_desenho(p) == antes, "o aviso da busca empurrou o desenho"
    p.filtrar("")
    assert altura_do_desenho(p) == antes


def test_frases_de_uma_ou_duas_linhas_nao_mudam_o_tamanho_do_desenho(painel_na_janela):
    from tkinter import font as tkfont
    p = painel_na_janela
    fonte = tkfont.nametofont("TkDefaultFont")
    largura = float(str(p._rotulos_de_texto[0].cget("wraplength")))
    longa = "palavra"
    while fonte.measure(longa) < 1.5 * largura:           # linha e meia: quebra em duas
        longa += " palavra"
    antes = altura_do_desenho(p)
    for resumo, detalhe in (("curta", ""), (longa, ""), ("curta", longa), (longa, longa)):
        p.resumo.set(resumo)
        p.detalhe.set(detalhe)
        assert altura_do_desenho(p) == antes, \
            "resumo de %d e detalhe de %d letras" % (len(resumo), len(detalhe))


# ---------------------------------------------------------------------------
# a leitura em segundo plano, com os estados
def test_carregar_le_em_segundo_plano_e_chega_no_pronto(raiz, desenho):
    from conversor.gui_camadas import PainelCamadas
    p = PainelCamadas(raiz)
    try:
        p.carregar(desenho[0])
        assert p.estado == "carregando" and p.mensagem_de_estado.get(), \
            "enquanto le, diz o que esta fazendo -> %r" % p.mensagem_de_estado.get()
        assert esperar(raiz, lambda: p.estado == "pronto"), "terminou -> %s" % p.estado
        assert "Pontos" in p.nomes_na_lista()
    finally:
        p.destroy()


def test_arquivo_que_nao_abre_mostra_erro_com_tentar_de_novo(raiz, tmp_path):
    from conversor.gui_camadas import PainelCamadas
    ruim = tmp_path / "quebrado.dxf"
    ruim.write_text("isto nao e um DXF", encoding="utf-8")
    p = PainelCamadas(raiz)
    try:
        p.carregar(str(ruim))
        assert esperar(raiz, lambda: p.estado in ("erro", "pronto")), "terminou"
        assert p.estado == "erro", p.estado
        assert p.mensagem_de_estado.get() and "Traceback" not in p.mensagem_de_estado.get(), \
            "mensagem em palavras, sem codigo de erro -> %r" % p.mensagem_de_estado.get()
        assert p.botao_tentar_de_novo_visivel(), "e um jeito de tentar de novo"
    finally:
        p.destroy()


def test_resultado_de_uma_leitura_antiga_e_descartado(raiz, desenho, tmp_path):
    from conversor.gui_camadas import PainelCamadas
    p = PainelCamadas(raiz)
    try:
        p.carregar(desenho[0])
        p.limpar()                                  # a pessoa trocou de desenho
        assert p.estado == "vazio"
        for _ in range(60):
            raiz.update()
            time.sleep(0.02)
        assert p.estado == "vazio", "a leitura que ficou para tras nao reaparece -> %s" % p.estado
    finally:
        p.destroy()


def test_sem_desenho_escolhido_diz_qual_e_o_proximo_passo(raiz):
    from conversor.gui_camadas import PainelCamadas
    p = PainelCamadas(raiz)
    try:
        assert p.estado == "vazio"
        assert "escolha" in p.mensagem_de_estado.get().lower(), p.mensagem_de_estado.get()
    finally:
        p.destroy()


def test_desenho_sem_nenhuma_geometria_diz_isso(raiz, tmp_path):
    from conversor.gui_camadas import PainelCamadas
    doc = ezdxf.new("R2010")
    doc.modelspace().add_text("so texto").set_placement((1, 1))
    caminho = str(tmp_path / "so_texto.dxf")
    doc.saveas(caminho)
    p = PainelCamadas(raiz)
    try:
        p.carregar(caminho)
        assert esperar(raiz, lambda: p.estado != "carregando")
        assert p.estado == "sem_geometria", p.estado
        assert "pontos, linhas" in p.mensagem_de_estado.get(), p.mensagem_de_estado.get()
    finally:
        p.destroy()
