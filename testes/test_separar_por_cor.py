# -*- coding: utf-8 -*-
"""
Converter so as cores escolhidas de uma camada, cada uma como uma camada de saida.

No desenho real, quase tudo estava na camada 0 e o desenhista diferenciou pela cor
(um azul pode ser um corrego). O filtro por cor tem de valer para os mesmos caminhos
do filtro por camada: o laco do GDAL (linhas, pontos, textos) e as hachuras lidas
pelo ezdxf.
"""
import os

import ezdxf
import fiona
import pytest

from conversor import convert, previa

VERMELHO, AZUL, VERDE = "#ff0000", "#0000ff", "#00ff00"


@pytest.fixture(scope="module")
def dxf(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("por_cor")
    doc = ezdxf.new("R2010")
    doc.layers.add("A", color=3)
    doc.layers.add("B", color=3)
    msp = doc.modelspace()
    for y in (0, 5, 7):
        msp.add_line((0, y), (10, y), dxfattribs={"layer": "A", "color": 1})
    msp.add_line((0, 9), (10, 9), dxfattribs={"layer": "A", "color": 5})
    msp.add_text("vermelho", dxfattribs={"layer": "A", "color": 1}).set_placement((1, 1))
    h1 = msp.add_hatch(color=1, dxfattribs={"layer": "A"})
    h1.paths.add_polyline_path([(20, 0), (25, 0), (25, 5), (20, 5)], is_closed=True)
    h2 = msp.add_hatch(color=5, dxfattribs={"layer": "A"})
    h2.paths.add_polyline_path([(30, 0), (35, 0), (35, 5), (30, 5)], is_closed=True)
    msp.add_line((40, 0), (50, 10), dxfattribs={"layer": "B"})
    caminho = str(pasta / "d.dxf")
    doc.saveas(caminho)
    return caminho, pasta


def converter(dxf, nome, **opcoes):
    caminho, pasta = dxf
    saida = os.path.join(str(pasta), nome)
    convert.cad_para_qgis(caminho, saida, 31982, gerar_projeto=False,
                          registrar=lambda *_: None, **opcoes)
    return saida, sorted(fiona.listlayers(saida))


def contar(saida, camada):
    with fiona.open(saida, layer=camada) as f:
        return len(f)


def test_filtrar_por_cor_leva_so_a_cor_pedida_em_linhas_textos_e_hachuras(dxf):
    saida, camadas = converter(dxf, "so_azul.gpkg", camadas={"A"}, cores={"A": {AZUL}})
    assert camadas == ["A_Hachura", "A_LineString"], \
        "so o azul: sem o texto vermelho -> %s" % camadas
    assert contar(saida, "A_LineString") == 1, "a unica linha azul"
    assert contar(saida, "A_Hachura") == 1, "e so a hachura azul (lida pelo ezdxf)"


def test_camada_que_nao_esta_em_cores_leva_todas_as_cores(dxf):
    _, camadas = converter(dxf, "sem_filtro_de_cor.gpkg", camadas={"A", "B"}, cores={"A": {AZUL}})
    assert "B_LineString" in camadas and "A_LineString" in camadas


def test_separar_por_cor_faz_uma_camada_de_saida_para_cada_cor(dxf):
    saida, camadas = converter(
        dxf, "separado.gpkg", camadas={"A", "B"}, cores={"A": {VERMELHO, AZUL}},
        separar_por_cor={"A"})
    assert camadas == ["A_azul_Hachura", "A_azul_LineString", "A_vermelho_Hachura",
                       "A_vermelho_LineString", "A_vermelho_Texto", "B_LineString"], \
        "A sai em duas (vermelho e azul) e B, que nao foi separada, mantem o nome -> %s" % camadas
    assert contar(saida, "A_vermelho_LineString") == 3 and contar(saida, "A_azul_LineString") == 1
    with fiona.open(saida, layer="A_vermelho_LineString") as f:
        assert {ft["properties"]["Layer"] for ft in f} == {"A"}, "o campo Layer segue sendo a camada do CAD"
        assert {ft["properties"]["cor_cad"] for ft in f} == {VERMELHO}


def test_camada_separada_so_com_uma_cor_marcada_leva_o_nome_da_cor(dxf):
    _, camadas = converter(dxf, "uma_cor.gpkg", camadas={"A"}, cores={"A": {AZUL}},
                           separar_por_cor={"A"})
    assert camadas == ["A_azul_Hachura", "A_azul_LineString"], camadas


def test_sem_separar_por_camada_as_cores_se_juntam_mas_o_filtro_vale(dxf):
    saida, camadas = converter(dxf, "juntas.gpkg", camadas={"A"}, cores={"A": {VERMELHO, AZUL}},
                               separar_por_camada=False, separar_por_cor={"A"})
    assert "LineString" in camadas and not [c for c in camadas if "vermelho" in c], \
        "juntando por tipo, o nome da camada some e o filtro continua -> %s" % camadas
    assert contar(saida, "LineString") == 4


def test_os_itens_da_previa_batem_com_as_camadas_gravadas(dxf):
    # o que a lista oferece (uma linha por camada e cor) tem de ser o que sai
    p = previa.ler(dxf[0])
    multi = {u.camada for u in p.unidades if "·" in u.rotulo}
    cores = {}
    for u in p.unidades:
        cores.setdefault(u.camada, set()).add(u.cor)
    _, camadas = converter(dxf, "bate.gpkg", camadas=set(cores), cores=cores,
                           separar_por_cor=multi)
    gravadas = {c.rsplit("_", 1)[0] for c in camadas}
    esperadas = set()
    for u in p.unidades:
        esperadas.add(u.camada + "_" + dxf_nome(u.cor) if u.camada in multi else u.camada)
    assert gravadas == esperadas, "previa: %s / gravadas: %s" % (sorted(esperadas), sorted(gravadas))


def dxf_nome(cor):
    from conversor import dxf_estilo
    return convert._nome_seguro(dxf_estilo.nome_da_cor(cor))


def test_hachura_e_agrupada_e_filtrada_pela_cor_do_ezdxf(tmp_path, monkeypatch):
    from conversor import cad_ezdxf
    doc = ezdxf.new("R2010")
    doc.layers.add("H", color=7)
    msp = doc.modelspace()
    h = msp.add_hatch(color=3, dxfattribs={"layer": "H"})
    h.paths.add_polyline_path([(0, 0), (10, 0), (10, 10), (0, 10)], is_closed=True)
    msp.add_line((20, 0), (30, 0), dxfattribs={"layer": "H", "color": 3})
    caminho = str(tmp_path / "h.dxf")
    doc.saveas(caminho)
    desenho = cad_ezdxf.ler(caminho, lambda *_: None)
    for hachura in desenho["hachuras"]:
        hachura["cor"] = (255, 127, 0)                  # o ezdxf diz laranja; o GDAL, verde
    monkeypatch.setattr(cad_ezdxf, "ler", lambda *a, **k: desenho)

    def converter_h(nome, **opcoes):
        saida = os.path.join(str(tmp_path), nome)
        convert.cad_para_qgis(caminho, saida, 31982, gerar_projeto=False,
                              registrar=lambda *_: None, **opcoes)
        return saida, sorted(fiona.listlayers(saida))

    saida, camadas = converter_h("laranja_e_verde.gpkg", camadas={"H"},
                                 cores={"H": {"#ff7f00", "#00ff00"}}, separar_por_cor={"H"})
    assert camadas == ["H_ff7f00_Hachura", "H_verde_LineString"],         "a hachura vai para o grupo da cor do ezdxf -> %s" % camadas
    saida, camadas = converter_h("so_verde.gpkg", camadas={"H"}, cores={"H": {"#00ff00"}})
    assert camadas == ["H_LineString"],         "pedindo so o verde, a hachura (laranja de verdade) fica de fora -> %s" % camadas
