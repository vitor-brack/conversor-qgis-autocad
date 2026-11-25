# -*- coding: utf-8 -*-
"""
As linhas escolhidas no desenho (uma a uma, nao a camada inteira) saem em negrito,
por cima, na cor que o desenho da a elas. O resto da camada continua fino.
"""
import ezdxf
import numpy as np
import pytest

from conversor import previa, previa_raster as pr


@pytest.fixture
def desenho(tmp_path):
    doc = ezdxf.new("R2010")
    doc.layers.add("A", color=3)
    doc.layers.add("Apagada", color=1).off()
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "A", "color": 1})
    msp.add_line((0, 5), (10, 5), dxfattribs={"layer": "A", "color": 1})
    msp.add_line((0, 9), (10, 9), dxfattribs={"layer": "A", "color": 5})
    msp.add_line((0, 20), (10, 20), dxfattribs={"layer": "Apagada"})
    caminho = str(tmp_path / "d.dxf")
    doc.saveas(caminho)
    return previa.ler(caminho)


def grupo_em(p, y, camada="A", cor=None):
    return p.achar_grupo(5, y, 0.5, camada, cor=cor, com_ocultas=True)


def test_so_a_linha_escolhida_vira_negrito_o_resto_da_camada_fica_fino(desenho):
    p = desenho
    indice = {c.nome: i for i, c in enumerate(p.camadas)}
    escolhida = grupo_em(p, 5)
    des = pr.montar_desenhos(p, {"A"}, indice, linhas_marcadas={escolhida})
    grossos = [d for d in des if d.grosso]
    assert len(grossos) == 1, "so uma forma em negrito -> %d" % len(grossos)
    g = grossos[0]
    assert g.id == indice["A"] and g.rgb == (255, 0, 0), "mesma camada e a cor da linha"
    assert g.xy.tolist() == [[0.0, 5.0], [10.0, 5.0]], "so os vertices da linha escolhida"
    assert g.inicio.tolist() == [0, 2]
    finos = [d for d in des if not d.grosso]
    assert sum(len(d.inicio) - 1 for d in finos) == 3, \
        "o desenho comum continua inteiro por baixo: as 3 linhas -> %s" % [d.xy.tolist() for d in finos]


def test_sem_linhas_escolhidas_nada_fica_em_negrito(desenho):
    indice = {c.nome: i for i, c in enumerate(desenho.camadas)}
    assert not any(d.grosso for d in pr.montar_desenhos(desenho, {"A"}, indice))


def test_varias_linhas_escolhidas_em_cores_diferentes(desenho):
    p = desenho
    indice = {c.nome: i for i, c in enumerate(p.camadas)}
    des = pr.montar_desenhos(p, {"A"}, indice,
                             linhas_marcadas={grupo_em(p, 0), grupo_em(p, 9)})
    assert sorted(d.rgb for d in des if d.grosso) == [(0, 0, 255), (255, 0, 0)], \
        "cada uma na sua cor"


def test_por_cor_o_negrito_leva_o_id_da_camada_e_cor(desenho):
    p = desenho
    indice = {u.chave: i for i, u in enumerate(p.unidades)}
    azul = ("A", "#0000ff")
    des = pr.montar_desenhos(p, {azul, ("A", "#ff0000")}, indice, por_cor=True,
                             linhas_marcadas={grupo_em(p, 9)})
    grossos = [d for d in des if d.grosso]
    assert [d.id for d in grossos] == [indice[azul]]


def test_linha_de_camada_que_nao_esta_no_desenho_nao_aparece(desenho):
    p = desenho
    indice = {c.nome: i for i, c in enumerate(p.camadas)}
    desligada = grupo_em(p, 20, camada="Apagada")
    assert desligada is not None
    des = pr.montar_desenhos(p, {"A"}, indice, com_ocultas=False, linhas_marcadas={desligada})
    assert not any(d.grosso for d in des), "camada fora do desenho nao desenha negrito"


def test_o_negrito_da_linha_escolhida_engrossa_so_ela_na_imagem(desenho):
    p = desenho
    indice = {c.nome: i for i, c in enumerate(p.camadas)}
    vista = pr.Vista(5.0, -2.0, 12.0)
    fino, _ = pr.desenhar(pr.montar_desenhos(p, {"A"}, indice), vista, 80, 80)
    grosso, _ = pr.desenhar(pr.montar_desenhos(p, {"A"}, indice,
                                               linhas_marcadas={grupo_em(p, 5)}), vista, 80, 80)
    pintado = lambda img: (img != np.array(pr.FUNDO, dtype=np.uint8)).any(axis=2)
    linhas = lambda img, y: int(pintado(img)[int(round((12.0 - y) * 5.0)) - 3:
                                             int(round((12.0 - y) * 5.0)) + 4].sum())
    assert linhas(grosso, 5) > linhas(fino, 5), "a linha escolhida engrossa"
    assert linhas(grosso, 0) == linhas(fino, 0), "a outra continua igual"
