# -*- coding: utf-8 -*-
"""
Contagem no singular: "1 feição", não "1 feições". O verbo concorda: "1 feição foi
ignorada", "2 feições foram ignoradas".

As contagens aparecem no log ("O que aconteceu"), na linha de comando e nas telas. Aqui
ficam as que saem da conversão e da linha de comando; as das telas estão em
test_registro_ao_lado.py e test_gui_camadas.py (precisam da janela).
"""
import os

import ezdxf
import fiona
import numpy as np
import pytest
from fiona.crs import from_epsg

from conversor import convert, fora_da_area, textos


def test_quantos_concorda_com_o_numero():
    assert textos.quantos(1, "feição", "feições") == "1 feição"
    assert textos.quantos(0, "feição", "feições") == "0 feições"
    assert textos.quantos(2, "feição", "feições") == "2 feições"
    # a lista de camadas escreve "?" quando o arquivo nao diz quantas tem
    assert textos.quantos("?", "feição", "feições") == "? feições"


def _desenho(tmp_path, linhas):
    """Um DXF com uma LINE por cor da lista, todas na camada A."""
    doc = ezdxf.new("R2010")
    doc.layers.add("A")
    msp = doc.modelspace()
    for i, cor in enumerate(linhas):
        msp.add_line((0, i * 10), (10, i * 10), dxfattribs={"layer": "A", "color": cor})
    caminho = str(tmp_path / "d.dxf")
    doc.saveas(caminho)
    return caminho


def _converter(dxf, tmp_path, **opcoes):
    log = []
    convert.cad_para_qgis(dxf, str(tmp_path / "s.gpkg"), 31982, gerar_projeto=False,
                          registrar=log.append, **opcoes)
    return log


def test_o_log_da_conversao_conta_uma_feicao_no_singular(tmp_path):
    log = _converter(_desenho(tmp_path, [1]), tmp_path)
    assert "1 feição em 1 camada, 1 cor distinta." in log, log
    assert "  camada 'A_LineString': 1 feição" in log, log
    assert not [m for m in log if "1 feições" in m or "1 camadas" in m], log


def test_o_log_da_conversao_continua_no_plural_com_mais_de_uma(tmp_path):
    log = _converter(_desenho(tmp_path, [1, 5]), tmp_path)
    assert "2 feições em 1 camada, 2 cores distintas." in log, log
    assert "  camada 'A_LineString': 2 feições" in log, log


def test_a_gravacao_em_shapefile_e_em_geojson_conta_no_singular(tmp_path):
    dxf = _desenho(tmp_path, [1])
    for formato, esperado in (("ESRI Shapefile", "  A_LineString.shp: 1 feição"),
                              ("GeoJSON", "  A_LineString.geojson: 1 feição")):
        log = []
        convert.cad_para_qgis(dxf, str(tmp_path / formato.split()[0]), 31982, formato=formato,
                              gerar_projeto=False, registrar=log.append)
        assert esperado in log, (formato, log)


def test_uma_feicao_longe_do_desenho_ficou_de_fora(tmp_path):
    doc = ezdxf.new("R2010")
    doc.layers.add("CURVAS")
    msp = doc.modelspace()
    bom = [(448000 + 20 * i, 6743000 + 30 * (i % 7)) for i in range(120)]
    msp.add_lwpolyline(bom, dxfattribs={"layer": "CURVAS"})
    msp.add_lwpolyline([(0, 0), (0, 0)], dxfattribs={"layer": "CURVAS"})
    dxf = str(tmp_path / "lixo.dxf")
    doc.saveas(dxf)
    caixa = fora_da_area.caixa_principal(np.vstack([np.array(bom, dtype=float),
                                                    [[0.0, 0.0], [0.0, 0.0]]]))
    log = _converter(dxf, tmp_path, descartar_fora_da_caixa=caixa)
    assert "1 feição longe do desenho (fora da área principal) ficou de fora." in log, log


def test_uma_feicao_sem_geometria_foi_ignorada(tmp_path):
    gpkg = str(tmp_path / "p.gpkg")
    with fiona.open(gpkg, "w", driver="GPKG", layer="p", crs=from_epsg(31982),
                    schema={"geometry": "Point", "properties": {"n": "int"}}) as c:
        c.write({"type": "Feature", "properties": {"n": 1},
                 "geometry": {"type": "Point", "coordinates": (412000.0, 6712000.0)}})
        c.write({"type": "Feature", "properties": {"n": 2}, "geometry": None})
    log = []
    convert.qgis_para_cad([{"caminho": gpkg, "camada": "p"}], str(tmp_path / "s.dxf"), 31982,
                          salvar_csv=False, registrar=log.append)
    assert "1 feição sem geometria foi ignorada." in log, log
    assert "Gravando 1 feição em 1 camada..." in log, log


def test_a_linha_de_comando_conta_uma_feicao_no_singular(tmp_path, monkeypatch, capsys):
    from conversor import __main__ as cli
    dxf = _desenho(tmp_path, [1])
    saida = str(tmp_path / "cli.gpkg")
    monkeypatch.setattr("sys.argv", ["conversor", "paraqgis", dxf, saida, "--sem-projeto"])
    assert cli.main() == 0
    assert "Concluído: 1 feição\n" in capsys.readouterr().out
