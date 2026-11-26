# -*- coding: utf-8 -*-
"""
A tabela colada no desenho (uma figura OLE) tem de chegar ao QGIS.

Colar uma tabela do Excel no AutoCAD cria um OLE2FRAME: a figura mora DENTRO do desenho,
nao num arquivo ao lado (como a IMAGE). A previa ja a mostrava; a conversao a ignorava.
Agora ela vira uma imagem no lugar dela no mapa: dentro do .gpkg (em pedacos PNG, o jeito
de o GeoPackage guardar imagem) ou, em Shapefile e GeoJSON, um PNG com o arquivo de mundo.
"""
import os
import sqlite3
import struct
import xml.etree.ElementTree as ET
import zlib
from contextlib import closing

import ezdxf
import fiona
import numpy as np
import pytest

from conversor import convert
from gerar_ole import arquivo_composto, bmp32, com_ole

VERMELHO, AZUL, VERDE = (255, 0, 0), (0, 0, 255), (0, 255, 0)
CAIXA = (100.0, 200.0, 400.0, 240.0)       # 300 x 40 unidades: um pixel por unidade


def figura():
    rgb = np.zeros((40, 300, 3), dtype=np.uint8)
    rgb[:20] = VERMELHO
    rgb[20:] = AZUL
    rgb[:, 280:] = VERDE                    # cai no segundo pedaco de 256 pixels
    return rgb


@pytest.fixture(scope="module")
def dxf(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("figuras")
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_line((0, 0), (500, 300))                                   # camada 0
    msp.add_line((0, 50), (500, 50), dxfattribs={"layer": "Outra"})
    com_ole(msp, b"\0" * 128 + arquivo_composto("CONTENTS", bmp32(figura())),
            (CAIXA[0], CAIXA[3]), (CAIXA[2], CAIXA[1]))
    caminho = str(pasta / "d.dxf")
    doc.saveas(caminho)
    return caminho, pasta


def converter(dxf, nome, formato="GPKG", **opcoes):
    caminho, pasta = dxf
    saida = os.path.join(str(pasta), nome)
    opcoes.setdefault("gerar_projeto", False)
    log = []
    convert.cad_para_qgis(caminho, saida, 31982, formato=formato, registrar=log.append,
                          **opcoes)
    return saida, log


def ler_png(dados):
    """HxWx3 ou HxWx4 de um PNG de 8 bits sem entrelacamento (o que o programa grava)."""
    assert dados[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, cabeca = 8, b"", None
    while pos < len(dados):
        tamanho, tipo = struct.unpack(">I4s", dados[pos:pos + 8])
        corpo = dados[pos + 8:pos + 8 + tamanho]
        if tipo == b"IHDR":
            cabeca = struct.unpack(">IIBBBBB", corpo)
        elif tipo == b"IDAT":
            idat += corpo
        pos += 12 + tamanho
    largura, altura, bits, cor, _c, _f, entrelacado = cabeca
    assert bits == 8 and cor in (2, 6) and not entrelacado
    canais = 4 if cor == 6 else 3
    cru = np.frombuffer(zlib.decompress(idat), dtype=np.uint8).reshape(altura, 1 + largura * canais)
    assert not cru[:, 0].any(), "so o filtro 0 (o que o programa usa)"
    return cru[:, 1:].reshape(altura, largura, canais)


def tabelas_de_imagem(gpkg):
    with closing(sqlite3.connect(gpkg)) as con:
        return [r[0] for r in con.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type = 'tiles'")]


def ler_figura_do_gpkg(gpkg, tabela):
    """(extensao do gpkg_contents, srs, pixels) da imagem guardada em pedacos no .gpkg."""
    with closing(sqlite3.connect(gpkg)) as con:
        x0, y0, x1, y1, srs = con.execute(
            "SELECT min_x, min_y, max_x, max_y, srs_id FROM gpkg_contents "
            "WHERE table_name = ?", (tabela,)).fetchone()
        tx0, _ty0, _tx1, ty1 = con.execute(
            "SELECT min_x, min_y, max_x, max_y FROM gpkg_tile_matrix_set "
            "WHERE table_name = ?", (tabela,)).fetchone()
        zoom, mw, mh, tw, th, px, py = con.execute(
            "SELECT zoom_level, matrix_width, matrix_height, tile_width, tile_height, "
            "pixel_x_size, pixel_y_size FROM gpkg_tile_matrix WHERE table_name = ?",
            (tabela,)).fetchone()
        mosaico = np.zeros((mh * th, mw * tw, 4), dtype=np.uint8)
        for coluna, linha, dados in con.execute(
                'SELECT tile_column, tile_row, tile_data FROM "%s" WHERE zoom_level = ?'
                % tabela, (zoom,)):
            pedaco = ler_png(dados)
            assert pedaco.shape[2] == 4, "pedaco com transparencia, para a sobra nao pintar"
            mosaico[linha * th:(linha + 1) * th, coluna * tw:(coluna + 1) * tw] = pedaco
    esq, topo = round((x0 - tx0) / px), round((ty1 - y1) / py)
    largura, altura = round((x1 - x0) / px), round((y1 - y0) / py)
    return (x0, y0, x1, y1), srs, mosaico[topo:topo + altura, esq:esq + largura]


def test_o_gpkg_leva_a_tabela_colada_no_lugar_dela(dxf):
    gpkg, log = converter(dxf, "um.gpkg")
    assert tabelas_de_imagem(gpkg) == ["0_Figura"], "a figura da camada 0"
    extensao, srs, pixels = ler_figura_do_gpkg(gpkg, "0_Figura")
    assert extensao == pytest.approx(CAIXA), "no lugar da figura no desenho"
    assert srs == 31982
    assert pixels.shape == (40, 300, 4)
    assert (pixels[..., 3] == 255).all(), "a figura inteira e opaca"
    assert (pixels[..., :3] == figura()).all(), "os mesmos pixels do BMP colado"
    assert any("0_Figura" in linha for linha in log), "o log conta que a figura foi"


def test_a_tabela_nao_entra_na_lista_de_camadas_de_dados(dxf):
    gpkg, _ = converter(dxf, "dois.gpkg")
    assert "0_Figura" not in convert.listar_camadas(gpkg)
    assert "0_Figura" not in fiona.listlayers(gpkg)
    with closing(sqlite3.connect(gpkg)) as con:
        estilos = {r[0] for r in con.execute("SELECT f_table_name FROM layer_styles")}
    assert estilos == set(convert.listar_camadas(gpkg)), "as cores continuam indo junto"
    for camada in convert.listar_camadas(gpkg):
        with fiona.open(gpkg, layer=camada) as f:
            assert len(f) > 0, "o GDAL continua lendo os dados -> %s" % camada


def test_sem_a_caixinha_das_imagens_a_tabela_fica_de_fora(dxf):
    gpkg, _ = converter(dxf, "tres.gpkg", incluir_imagens=False)
    assert tabelas_de_imagem(gpkg) == []


def test_a_tabela_so_vai_com_a_camada_dela_marcada(dxf):
    sem, _ = converter(dxf, "quatro_sem.gpkg", camadas={"Outra"})
    assert tabelas_de_imagem(sem) == []
    com, _ = converter(dxf, "quatro_com.gpkg", camadas={"0"})
    assert tabelas_de_imagem(com) == ["0_Figura"]


def test_shapefile_leva_a_tabela_em_png_com_arquivo_de_mundo(dxf):
    saida, _ = converter(dxf, "cinco", formato="ESRI Shapefile")
    png = os.path.join(saida, "0_Figura.png")
    with open(png, "rb") as fp:
        assert (ler_png(fp.read())[..., :3] == figura()).all()
    with open(os.path.join(saida, "0_Figura.pgw"), encoding="ascii") as fp:
        mundo = [float(v) for v in fp.read().split()]
    # pixel de 1 x 1, centro do pixel do canto superior esquerdo
    assert mundo == pytest.approx([1, 0, 0, -1, CAIXA[0] + 0.5, CAIXA[3] - 0.5])
    assert os.path.exists(png + ".aux.xml"), "o sistema de coordenadas, para o QGIS"


def test_o_projeto_abre_a_tabela_de_dentro_do_gpkg(dxf):
    gpkg, _ = converter(dxf, "seis.gpkg", gerar_projeto=True)
    raiz = ET.parse(os.path.splitext(gpkg)[0] + ".qgs").getroot()
    rasters = [c for c in raiz.iter("maplayer") if c.get("type") == "raster"]
    assert [c.findtext("datasource") for c in rasters] == ["GPKG:./seis.gpkg:0_Figura"], \
        "caminho relativo, como o proprio QGIS grava"
    assert [c.findtext("provider") for c in rasters] == ["gdal"]


def test_reprojetando_a_tabela_fica_no_sistema_do_desenho(dxf):
    gpkg, _ = converter(dxf, "sete.gpkg", epsg_destino=4674)
    _extensao, srs, _pixels = ler_figura_do_gpkg(gpkg, "0_Figura")
    assert srs == 31982, "a imagem fica no sistema do desenho; o QGIS a reprojeta"
    with closing(sqlite3.connect(gpkg)) as con:
        definicao = con.execute("SELECT definition FROM gpkg_spatial_ref_sys "
                                "WHERE srs_id = 31982").fetchone()
    assert definicao and "SIRGAS 2000 / UTM zone 22S" in definicao[0], \
        "o .gpkg precisa descrever o sistema da imagem -> %r" % (definicao,)
