# -*- coding: utf-8 -*-
"""
Converter so as camadas que a pessoa marcou.

Cada caminho por onde uma entidade chega ao resultado precisa respeitar a
escolha: o laco do GDAL (linhas, pontos, textos), as hachuras (lidas pelo
ezdxf), as imagens e a folha de impressao. Se um deles escapa, uma camada
desmarcada vaza para a entrega.
"""
import os

import ezdxf
import fiona
import numpy as np
import pytest

import gerar_camadas
import gerar_carimbo
from conversor import convert, fora_da_area


def converter(dxf, pasta, nome="s.gpkg", **opcoes):
    """Converte para GeoPackage; devolve (resultado, camadas gravadas)."""
    saida = os.path.join(str(pasta), nome)
    res = convert.cad_para_qgis(dxf, saida, 31982, gerar_projeto=False,
                                registrar=lambda *_: None, **opcoes)
    return res, sorted(convert.listar_camadas(saida))


@pytest.fixture(scope="module")
def camadas_dxf(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("filtro_camadas")
    dxf, _ = gerar_camadas.gerar(str(pasta / "desenho"))
    return dxf, pasta


def test_so_as_camadas_escolhidas_saem(camadas_dxf):
    dxf, pasta = camadas_dxf
    _, camadas = converter(dxf, pasta, "a.gpkg", camadas={"Pontos"})
    assert camadas == ["Pontos_Point"], "so a camada Pontos -> %s" % camadas


def test_camada_escolhida_leva_tudo_o_que_tem_nela(camadas_dxf):
    dxf, pasta = camadas_dxf
    _, camadas = converter(dxf, pasta, "b.gpkg", camadas={"Desligada"})
    assert camadas == ["Desligada_Hachura", "Desligada_LineString", "Desligada_Point",
                       "Desligada_Texto"], \
        "linha, ponto, texto e hachura (lida pelo ezdxf) dela, e mais nada -> %s" % camadas


def test_hachura_de_camada_nao_escolhida_nao_sai(camadas_dxf):
    dxf, pasta = camadas_dxf
    _, camadas = converter(dxf, pasta, "c.gpkg", camadas={"Visivel", "Pontos"})
    vazadas = [c for c in camadas if c.startswith(("Desligada", "Congelada"))]
    assert not vazadas, "as hachuras das camadas desmarcadas nao vazam -> %s" % vazadas


def test_folha_de_impressao_so_entra_se_o_desenho_so_tem_ela(camadas_dxf):
    dxf, pasta = camadas_dxf
    res, _ = converter(dxf, pasta, "d.gpkg", camadas={"Visivel"})
    # a camada Visivel tem um quadrado e um texto na aba Model, e outros dois
    # na folha de impressao: a folha continua de fora
    assert res["feicoes"] == 2, "so o que e do desenho (quadrado e texto) -> %d" % res["feicoes"]
    so_papel = gerar_camadas.gerar_so_papel(str(pasta / "so_papel"))
    res2, _ = converter(so_papel, pasta, "e.gpkg", camadas={"0"})
    assert res2["feicoes"] >= 2, "desenho feito so no papel, camada escolhida -> %d" % res2["feicoes"]
    with pytest.raises(convert.ErroConversao):
        converter(so_papel, pasta, "f.gpkg", camadas={"OutraCamada"})


def test_imagem_e_hachura_so_da_camada_escolhida(tmp_path):
    dxf, _ = gerar_carimbo.gerar(str(tmp_path / "carimbo"))
    res, camadas = converter(dxf, tmp_path, "g.gpkg", camadas={"Carimbo"})
    assert res["imagens"] == 0, "a imagem esta na camada Logo, desmarcada -> %d" % res["imagens"]
    assert not [c for c in camadas if c.startswith("Logo")], \
        "nada da camada Logo (hachura, texto) -> %s" % camadas
    res, camadas = converter(dxf, tmp_path, "h.gpkg", camadas={"Logo"})
    assert res["imagens"] == 1, "marcando a Logo, a imagem que existe vem -> %d" % res["imagens"]
    assert "Logo_Hachura" in camadas and not [c for c in camadas if c.startswith("Carimbo")], \
        "e a hachura dela, sem o carimbo -> %s" % camadas


def test_nenhuma_camada_escolhida_e_erro_claro(camadas_dxf):
    dxf, pasta = camadas_dxf
    with pytest.raises(convert.ErroConversao, match="camada"):
        converter(dxf, pasta, "i.gpkg", camadas=set())


def test_sem_filtro_continua_convertendo_tudo(camadas_dxf):
    dxf, pasta = camadas_dxf
    _, todas = converter(dxf, pasta, "j.gpkg")
    _, nenhum_filtro = converter(dxf, pasta, "k.gpkg", camadas=None)
    assert todas == nenhum_filtro and "Pontos_Point" in todas and "Visivel_LineString" in todas


# ---------------------------------------------------------------------------
# feicao fora da area principal
def _desenho_com_lixo(pasta):
    doc = ezdxf.new("R2010")
    doc.layers.add("CURVAS")
    msp = doc.modelspace()
    bom = [(448000 + 20 * i, 6743000 + 30 * (i % 7)) for i in range(120)]
    msp.add_lwpolyline(bom, dxfattribs={"layer": "CURVAS", "elevation": 500.0})
    msp.add_lwpolyline([(0, 0), (0, 0)], dxfattribs={"layer": "CURVAS", "elevation": 500.0})
    dxf = str(pasta / "lixo.dxf")
    doc.saveas(dxf)
    return dxf, np.array(bom, dtype=float)


def test_feicao_fora_da_caixa_nao_vai_e_a_do_terreno_fica(tmp_path):
    dxf, bom = _desenho_com_lixo(tmp_path)
    caixa = fora_da_area.caixa_principal(np.vstack([bom, [[0.0, 0.0], [0.0, 0.0]]]))
    saida = os.path.join(str(tmp_path), "l.gpkg")
    convert.cad_para_qgis(dxf, saida, 31982, gerar_projeto=False, registrar=lambda *_: None,
                          descartar_fora_da_caixa=caixa)
    with fiona.open(saida, layer="CURVAS_LineString") as f:
        assert len(f) == 1, "so a curva do terreno fica -> %d feicoes" % len(f)
    saida2 = os.path.join(str(tmp_path), "m.gpkg")
    convert.cad_para_qgis(dxf, saida2, 31982, gerar_projeto=False, registrar=lambda *_: None)
    with fiona.open(saida2, layer="CURVAS_LineString") as f:
        assert len(f) == 2, "sem a caixa, nada e descartado -> %d feicoes" % len(f)


# ---------------------------------------------------------------------------
# DWG: o DXF que o ODA gerou na previa e reaproveitado
def test_dxf_pronto_dispensa_a_conversao_do_dwg(camadas_dxf):
    dxf, pasta = camadas_dxf
    saida = os.path.join(str(pasta), "n.gpkg")
    res = convert.cad_para_qgis(os.path.join(str(pasta), "nao_existe.dwg"), saida, 31982,
                                gerar_projeto=False, registrar=lambda *_: None,
                                dxf_pronto=dxf)
    assert res["feicoes"] > 0, "converteu o DXF que ja estava pronto, sem chamar o ODA"
