# -*- coding: utf-8 -*-
"""
Monta um DXF com um carimbo parecido com o de um mapa real, reunindo os casos
que desalinharam o texto na primeira versao:

  - rotulos alinhados a esquerda, cujo segundo ponto de alinhamento o AutoCAD
    grava como (0, 0);
  - valores centralizados no meio de cada celula;
  - texto alinhado a direita;
  - atributos de bloco (ATTRIB), que e como carimbos costumam ser feitos;
  - MTEXT de tres linhas ancorado pelo topo;
  - MTEXT de uma linha so, que o AutoCAD quebra pela largura do quadro;
  - duas palavras ancoradas no MESMO ponto, uma pela base e outra pelo topo --
    o truque de CAD que aparecia empilhado ("CENTRAL" sobre "TRIAGEM NOVA");
  - texto girado 90 graus;
  - um logotipo feito de hachuras solidas e letras grandes;
  - uma hachura com padrao;
  - uma imagem raster (IMAGE), com o PNG ao lado do desenho.

Devolve tambem o que se espera de cada texto, para o teste conferir no QGIS.
"""
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fiona
from fiona.crs import CRS

from conversor import convert, textos_cad

X0, Y0 = 412000.0, 6711000.0


def _png(caminho, largura, altura):
    """PNG RGB simples (faixas coloridas), sem depender de biblioteca de imagem."""
    linhas = b""
    for y in range(altura):
        linhas += b"\x00"
        for x in range(largura):
            if x < largura // 3:
                linhas += bytes((200, 30, 30))
            elif x < 2 * largura // 3:
                linhas += bytes((240, 200, 20))
            else:
                linhas += bytes((30, 60, 200))

    def bloco(tipo, dados):
        return (struct.pack(">I", len(dados)) + tipo + dados
                + struct.pack(">I", zlib.crc32(tipo + dados) & 0xffffffff))

    with open(caminho, "wb") as fp:
        fp.write(b"\x89PNG\r\n\x1a\n")
        fp.write(bloco(b"IHDR", struct.pack(">IIBBBBB", largura, altura, 8, 2, 0, 0, 0)))
        fp.write(bloco(b"IDAT", zlib.compress(linhas)))
        fp.write(bloco(b"IEND", b""))


def _molde(pasta):
    origem = os.path.join(pasta, "_m.gpkg")
    with fiona.open(origem, "w", driver="GPKG", layer="u", crs=CRS.from_epsg(31982),
                    schema={"geometry": "LineString", "properties": {"a": "str"}}) as c:
        c.write({"type": "Feature", "properties": {"a": "x"},
                 "geometry": {"type": "LineString",
                              "coordinates": [(X0, Y0), (X0 + 1, Y0 + 1)]}})
    caminho = os.path.join(pasta, "_m.dxf")
    convert.qgis_para_cad([{"caminho": origem, "camada": "u"}], caminho, 31982,
                          registrar=lambda *_: None)
    texto = open(caminho, encoding="utf-8").read()
    for extra in ("_m.gpkg", "_m.dxf", "_m.prj", "_m.crs.txt", "_m.conversor.json",
                  "_m_atributos.csv"):
        if os.path.exists(os.path.join(pasta, extra)):
            os.remove(os.path.join(pasta, extra))
    return texto


class _Handles:
    def __init__(self):
        self.n = 0xC0000

    def __call__(self):
        self.n += 1
        return "%X" % self.n


def gerar(pasta):
    os.makedirs(pasta, exist_ok=True)
    corpo = _molde(pasta)
    h = _Handles()
    ents = []
    esperado = {}   # texto -> (x_ancora, y_ancora, hali, vali, altura, angulo)

    def linha(camada, cor, x1, y1, x2, y2):
        ents.append("  0\nLINE\n  5\n%s\n100\nAcDbEntity\n  8\n%s\n 62\n%6d\n100\nAcDbLine\n"
                    " 10\n%r\n 20\n%r\n 30\n0\n 11\n%r\n 21\n%r\n 31\n0\n"
                    % (h(), camada, cor, X0 + x1, Y0 + y1, X0 + x2, Y0 + y2))

    def text(conteudo, x, y, altura, h72=0, v73=0, ang=0.0, cor=7, camada="Carimbo"):
        """TEXT como o AutoCAD grava: com alinhamento, 10/20 e o ponto real em 11/21."""
        ax, ay = X0 + x, Y0 + y
        if h72 == 0 and v73 == 0:
            p10, p11 = (ax, ay), (0.0, 0.0)          # o AutoCAD grava 11/21 zerado
        else:
            largura = textos_cad.largura_texto(conteudo, altura) * 0.8
            deslocamento = {0: 0.0, 1: largura / 2, 2: largura, 4: largura / 2}[h72]
            p10, p11 = (ax - deslocamento, ay), (ax, ay)
        ents.append("  0\nTEXT\n  5\n%s\n100\nAcDbEntity\n  8\n%s\n 62\n%6d\n100\nAcDbText\n"
                    " 10\n%r\n 20\n%r\n 30\n0\n 40\n%r\n  1\n%s\n 50\n%r\n 72\n%6d\n"
                    " 11\n%r\n 21\n%r\n 31\n0\n100\nAcDbText\n 73\n%6d\n"
                    % (h(), camada, cor, p10[0], p10[1], altura, conteudo, ang, h72,
                       p11[0], p11[1], v73))
        hali = {0: "Left", 1: "Center", 2: "Right", 4: "Center"}[h72]
        vali = {0: "Base", 1: "Bottom", 2: "Half", 3: "Top"}[v73 if h72 != 4 else 2]
        esperado[conteudo] = (ax, ay, hali, vali, altura, ang)

    def mtext(conteudo, x, y, altura, anexo, largura=0.0, cor=7, camada="Carimbo"):
        ents.append("  0\nMTEXT\n  5\n%s\n100\nAcDbEntity\n  8\n%s\n 62\n%6d\n100\nAcDbMText\n"
                    " 10\n%r\n 20\n%r\n 30\n0\n 40\n%r\n 41\n%r\n 71\n%6d\n 72\n     1\n"
                    "  1\n%s\n" % (h(), camada, cor, X0 + x, Y0 + y, altura, largura,
                                   anexo, conteudo))
        hali = {1: "Left", 2: "Center", 3: "Right", 4: "Left", 5: "Center", 6: "Right",
                7: "Left", 8: "Center", 9: "Right"}[anexo]
        vali = {1: "Top", 2: "Top", 3: "Top", 4: "Half", 5: "Half", 6: "Half",
                7: "Bottom", 8: "Bottom", 9: "Bottom"}[anexo]
        chave = conteudo.replace("\\P", "\n")
        esperado[chave] = (X0 + x, Y0 + y, hali, vali, altura, 0.0, largura)

    def hatch(camada, cor, pontos, padrao="SOLID"):
        s = ("  0\nHATCH\n  5\n%s\n100\nAcDbEntity\n  8\n%s\n 62\n%6d\n100\nAcDbHatch\n"
             " 10\n0\n 20\n0\n 30\n0\n210\n0\n220\n0\n230\n1\n  2\n%s\n 70\n%6d\n 71\n     0\n"
             " 91\n     1\n 92\n     2\n 72\n     0\n 73\n     1\n 93\n%6d\n"
             % (h(), camada, cor, padrao, 1 if padrao == "SOLID" else 0, len(pontos)))
        for x, y in pontos:
            s += " 10\n%r\n 20\n%r\n" % (X0 + x, Y0 + y)
        s += " 97\n     0\n 75\n     0\n 76\n     1\n"
        if padrao != "SOLID":
            s += " 52\n0\n 41\n1\n 77\n     0\n 78\n     0\n"
        s += " 98\n     0\n"
        ents.append(s)

    # ---- moldura e celulas do carimbo (vermelho, como no original)
    for x1, y1, x2, y2 in [(0, 0, 300, 0), (300, 0, 300, 140), (300, 140, 0, 140),
                           (0, 140, 0, 0), (200, 0, 200, 110), (200, 22, 300, 22),
                           (200, 44, 300, 44), (200, 66, 300, 66), (200, 88, 300, 88),
                           (0, 110, 300, 110), (90, 110, 90, 140), (10, 60, 190, 60)]:
        linha("Carimbo", 1, x1, y1, x2, y2)

    # rotulos a esquerda e valores centralizados nas celulas da direita
    for i, (rotulo, valor) in enumerate([("Prancha", "01"), ("Desenho", "Fulano"),
                                         ("Área", "57.968,00 m²"),
                                         ("Escala", "1/1000")]):
        base_y = 1 + 22 * i
        text(rotulo, 202, base_y + 16, 3.5)
        text(valor, 250, base_y + 8, 4.5, h72=1, v73=2, cor=14)
    text("Prancha 01 de 03", 196, 104, 3.0, h72=2)                         # direita

    # MTEXT de tres linhas, ancorado pelo topo e centralizado
    mtext("Projeto Potenciométrico\\PAdaptado da Planta Planialtimétrica"
          "\\PFornecida Pelo Município", 195, 137, 5.0, anexo=2, cor=14)
    # MTEXT de uma linha, que o AutoCAD quebra pela largura do quadro
    mtext("Rua 02 Leste 1182, Centro Administrativo, Teutônia/RS", 10, 50, 3.0,
          anexo=1, largura=80.0, cor=40)

    # duas palavras no MESMO ponto: uma pela base (fica acima), outra pelo topo
    text("CENTRAL", 100, 85, 6.0, h72=1, v73=0)
    text("TRIAGEM NOVA", 100, 83, 6.0, h72=1, v73=3)

    # texto girado
    text("LIMITE LESTE", 290, 20, 4.0, ang=90.0, cor=3)

    # ---- logotipo: hachuras solidas e letras grandes, lado a lado
    hatch("Logo", 1, [(8, 118), (30, 118), (30, 128), (8, 128)])          # cabeca
    hatch("Logo", 33, [(18, 112), (22, 112), (22, 118), (18, 118)])       # cabo
    text("Geo", 38, 118, 12.0, cor=5, camada="Logo")
    x_sana = 38 + textos_cad.largura_texto("Geo", 12.0)
    text("sana", x_sana, 118, 12.0, cor=150, camada="Logo")
    # hachura com padrao, numa area de fundo
    hatch("Fundo", 3, [(10, 5), (80, 5), (80, 35), (10, 35)], padrao="ANSI31")

    # ---- atributos de bloco
    bloco = ("  0\nBLOCK\n  5\n%s\n100\nAcDbEntity\n  8\n0\n100\nAcDbBlockBegin\n"
             "  2\nRESP\n 70\n     2\n 10\n0\n 20\n0\n 30\n0\n  3\nRESP\n  1\n\n"
             "  0\nATTDEF\n  5\n%s\n100\nAcDbEntity\n  8\n0\n100\nAcDbText\n"
             " 10\n0\n 20\n0\n 30\n0\n 40\n3\n  1\n-\n100\nAcDbAttributeDefinition\n"
             "  3\nNome?\n  2\nNOME\n 70\n     0\n"
             "  0\nENDBLK\n  5\n%s\n100\nAcDbEntity\n  8\n0\n100\nAcDbBlockEnd\n"
             % (h(), h(), h()))
    ax, ay = X0 + 100, Y0 + 65
    ents.append("  0\nINSERT\n  5\n%s\n100\nAcDbEntity\n  8\nCarimbo\n100\nAcDbBlockReference\n"
                " 66\n     1\n  2\nRESP\n 10\n%r\n 20\n%r\n 30\n0\n"
                "  0\nATTRIB\n  5\n%s\n100\nAcDbEntity\n  8\nCarimbo\n 62\n     6\n100\nAcDbText\n"
                " 10\n%r\n 20\n%r\n 30\n0\n 40\n4\n  1\nFulano de Tal da Silva\n 72\n     1\n"
                " 11\n%r\n 21\n%r\n 31\n0\n100\nAcDbAttribute\n  2\nNOME\n 70\n     0\n 74\n     0\n"
                "  0\nSEQEND\n  5\n%s\n100\nAcDbEntity\n  8\nCarimbo\n"
                % (h(), X0 + 60, Y0 + 60, h(), ax - 40, ay, ax, ay, h()))
    esperado["Fulano de Tal da Silva"] = (ax, ay, "Center", "Base", 4.0, 0.0)

    # ---- imagem raster, com o arquivo ao lado do desenho
    _png(os.path.join(pasta, "logo_teste.png"), 60, 20)
    imagem_h, imagedef_h = h(), h()
    ents.append("  0\nIMAGE\n  5\n%s\n100\nAcDbEntity\n  8\nLogo\n100\nAcDbRasterImage\n"
                " 90\n     0\n 10\n%r\n 20\n%r\n 30\n0\n 11\n0.5\n 21\n0\n 31\n0\n"
                " 12\n0\n 22\n0.5\n 32\n0\n 13\n60\n 23\n20\n340\n%s\n 70\n     7\n"
                "280\n     0\n281\n    50\n282\n    50\n283\n     0\n"
                % (imagem_h, X0 + 310, Y0 + 110, imagedef_h))
    # e uma imagem cujo arquivo nao existe, para o aviso
    faltante_h, faltante_def = h(), h()
    ents.append("  0\nIMAGE\n  5\n%s\n100\nAcDbEntity\n  8\nLogo\n100\nAcDbRasterImage\n"
                " 90\n     0\n 10\n%r\n 20\n%r\n 30\n0\n 11\n1\n 21\n0\n 31\n0\n"
                " 12\n0\n 22\n1\n 32\n0\n 13\n10\n 23\n10\n340\n%s\n"
                % (faltante_h, X0 + 400, Y0 + 400, faltante_def))
    objetos = ("  0\nIMAGEDEF\n  5\n%s\n100\nAcDbRasterImageDef\n 90\n     0\n"
               "  1\nE:\\PM TEUTONIA\\logo_teste.png\n 10\n60\n 20\n20\n"
               "  0\nIMAGEDEF\n  5\n%s\n100\nAcDbRasterImageDef\n 90\n     0\n"
               "  1\nE:\\PM TEUTONIA\\foto_que_nao_existe.jpg\n 10\n10\n 20\n10\n"
               % (imagedef_h, faltante_def))

    # ---- monta o arquivo
    marca = corpo.index("  0\nENDSEC", corpo.index("\nBLOCKS\n"))
    corpo = corpo[:marca] + bloco + corpo[marca:]
    marca = corpo.index("  0\nENDSEC", corpo.index("\nENTITIES\n"))
    corpo = corpo[:marca] + "".join(ents) + corpo[marca:]
    marca = corpo.index("  0\nENDSEC", corpo.index("\nOBJECTS\n"))
    corpo = corpo[:marca] + objetos + corpo[marca:]

    registros = ""
    for i, (nome, aci) in enumerate([("Carimbo", 7), ("Logo", 7), ("Fundo", 7)]):
        registros += ("  0\nLAYER\n  5\n%X\n100\nAcDbSymbolTableRecord\n"
                      "100\nAcDbLayerTableRecord\n  2\n%s\n 70\n     0\n 62\n%6d\n"
                      "  6\nContinuous\n" % (0xCF000 + i, nome, aci))
    marca = corpo.index("  0\nENDTAB", corpo.index("\nLAYER\n"))
    corpo = corpo[:marca] + registros + corpo[marca:]

    destino = os.path.join(pasta, "carimbo.dxf")
    # UTF-8 com cabecalho ANSI, como sai do ODA File Converter
    open(destino, "w", encoding="utf-8").write(corpo)
    return destino, esperado


if __name__ == "__main__":
    pasta = sys.argv[1] if len(sys.argv) > 1 else "carimbo"
    caminho, esperado = gerar(os.path.abspath(pasta))
    print("gerado:", caminho, "|", len(esperado), "textos")
