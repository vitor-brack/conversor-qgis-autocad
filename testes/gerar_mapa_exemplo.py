# -*- coding: utf-8 -*-
"""
Monta um DXF parecido com um mapa potenciometrico de verdade: curvas de nivel,
limite da area, pocos rotulados, setas de fluxo e um quadro de convencoes.

Serve para os testes terem algo com a cara do arquivo real -- varias camadas,
cores ACI diferentes e bastante texto -- em vez de dois pontos soltos.
"""
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fiona
from fiona.crs import CRS

from conversor import convert

# camada -> indice de cor do AutoCAD
CORES_ACI = {
    "Curvas_Nivel": 30,      # laranja
    "Limite_Area": 6,        # magenta
    "Pocos": 5,              # azul
    "Fluxo": 3,              # verde
    "Convencoes": 7,         # preto
}

X0, Y0 = 412000.0, 6712000.0


def gerar(destino_dxf):
    pasta = os.path.dirname(destino_dxf)
    origem = os.path.join(pasta, "_fonte.gpkg")
    crs = CRS.from_epsg(31982)

    # curvas de nivel: ondas concentricas, com cota em Z
    with fiona.open(origem, "w", driver="GPKG", layer="Curvas_Nivel", crs=crs,
                    schema={"geometry": "LineString",
                            "properties": {"cota": "int"}}) as c:
        for k in range(9):
            cota = 100 + k * 5
            raio = 60 + k * 32
            pontos = []
            for passo in range(73):
                ang = math.radians(passo * 5)
                r = raio * (1 + 0.18 * math.sin(3 * ang) + 0.07 * math.cos(5 * ang))
                pontos.append((X0 + 340 + r * math.cos(ang),
                               Y0 + 300 + r * math.sin(ang) * 0.8,
                               float(cota)))
            c.write({"type": "Feature", "properties": {"cota": cota},
                     "geometry": {"type": "LineString", "coordinates": pontos}})

    # limite da area
    with fiona.open(origem, "w", driver="GPKG", layer="Limite_Area", crs=crs,
                    schema={"geometry": "Polygon", "properties": {"n": "str"}}) as c:
        anel = [(X0, Y0), (X0 + 700, Y0 + 40), (X0 + 660, Y0 + 620),
                (X0 + 120, Y0 + 600), (X0, Y0)]
        c.write({"type": "Feature", "properties": {"n": "area"},
                 "geometry": {"type": "Polygon", "coordinates": [anel]}})

    # pocos de monitoramento, com codigo para virar texto
    pocos = [("PM-01", 120, 150), ("PM-02", 300, 480), ("PM-03", 560, 200),
             ("PM-04", 480, 540), ("PM-05", 200, 350), ("PM-06", 620, 420)]
    with fiona.open(origem, "w", driver="GPKG", layer="Pocos", crs=crs,
                    schema={"geometry": "Point",
                            "properties": {"cod": "str", "nivel": "float"}}) as c:
        for cod, dx, dy in pocos:
            c.write({"type": "Feature",
                     "properties": {"cod": cod, "nivel": 118.5 + dx / 100.0},
                     "geometry": {"type": "Point", "coordinates": (X0 + dx, Y0 + dy)}})

    # setas de fluxo
    with fiona.open(origem, "w", driver="GPKG", layer="Fluxo", crs=crs,
                    schema={"geometry": "LineString", "properties": {"n": "str"}}) as c:
        for i in range(5):
            bx, by = X0 + 150 + i * 110, Y0 + 120 + i * 80
            c.write({"type": "Feature", "properties": {"n": "f%d" % i},
                     "geometry": {"type": "LineString",
                                  "coordinates": [(bx, by), (bx + 70, by + 45)]}})

    # quadro de convencoes: textos alinhados como numa legenda
    legenda = ["CONVENCOES", "Curva de nivel (m)", "Poco de monitoramento",
               "Sentido do fluxo", "Limite da area", "Escala 1:2000"]
    with fiona.open(origem, "w", driver="GPKG", layer="Convencoes", crs=crs,
                    schema={"geometry": "Point", "properties": {"txt": "str"}}) as c:
        for i, texto in enumerate(legenda):
            c.write({"type": "Feature", "properties": {"txt": texto},
                     "geometry": {"type": "Point",
                                  "coordinates": (X0 + 760, Y0 + 560 - i * 45)}})

    # ---- QGIS -> DXF, duas passadas por causa dos campos de rotulo diferentes
    convert.qgis_para_cad(
        [{"caminho": origem, "camada": n}
         for n in ["Curvas_Nivel", "Limite_Area", "Fluxo"]],
        destino_dxf, 31982, registrar=lambda *_: None)
    base = os.path.splitext(destino_dxf)[0]
    convert.qgis_para_cad([{"caminho": origem, "camada": "Pocos"}],
                          base + "_p.dxf", 31982, campo_rotulo="cod",
                          altura_texto=14.0, registrar=lambda *_: None)
    convert.qgis_para_cad([{"caminho": origem, "camada": "Convencoes"}],
                          base + "_c.dxf", 31982, campo_rotulo="txt",
                          altura_texto=18.0, registrar=lambda *_: None)

    # junta as entidades dos tres arquivos num so
    def entidades(p):
        t = open(p, encoding="utf-8").read()
        i = t.index("\nENTITIES\n") + len("\nENTITIES\n")
        j = t.index("  0\nENDSEC", i)
        return t[i:j]

    corpo = open(destino_dxf, encoding="utf-8").read()
    corte = corpo.index("  0\nENDSEC", corpo.index("\nENTITIES\n"))
    junto = (corpo[:corte] + entidades(base + "_p.dxf")
             + entidades(base + "_c.dxf") + corpo[corte:])

    # declara as camadas que vieram dos outros arquivos e pinta todas
    registros = []
    for camada in ("Pocos", "Convencoes"):
        registros.append(
            "  0\nLAYER\n  5\n%X\n100\nAcDbSymbolTableRecord\n"
            "100\nAcDbLayerTableRecord\n  2\n%s\n 70\n     0\n 62\n%6d\n"
            "  6\nContinuous\n" % (0xA1000 + len(registros), camada,
                                   CORES_ACI[camada]))
    marca = junto.index("  0\nENDTAB", junto.index("\nLAYER\n"))
    junto = junto[:marca] + "".join(registros) + junto[marca:]

    for camada, aci in CORES_ACI.items():
        junto = re.sub(r"(\n  2\n%s\n 70\n\s*\d+\n 62\n)\s*-?\d+" % re.escape(camada),
                       lambda m, a=aci: m.group(1) + "%6d" % a, junto)

    junto = _acrescentar_casos_reais(junto)

    # Gravado em UTF-8 mantendo ANSI_1252 no cabecalho: e exatamente o que o
    # ODA File Converter produz ao converter um .dwg, e o que fazia o texto
    # acentuado chegar quebrado no QGIS.
    open(destino_dxf, "w", encoding="utf-8").write(junto)
    for sufixo in ("_p", "_c"):
        for ext in (".dxf", ".prj", ".crs.txt", ".conversor.json", "_atributos.csv"):
            alvo = base + sufixo + ext
            if os.path.exists(alvo):
                os.remove(alvo)
    return destino_dxf


def _acrescentar_casos_reais(corpo):
    """Injeta o que um desenho de verdade tem e o nosso exemplo nao tinha.

    Tres coisas, todas vistas no mapa que motivou este teste:
      - entidades pintadas a mao, em vez de herdarem a cor da camada;
      - um bloco cujas pecas tem cores diferentes entre si;
      - texto acentuado (o desenho e em portugues).
    """
    def linha(handle, camada, cor, x, y, dx=40, dy=25, extra=""):
        grupo_cor = "" if cor is None else " 62\n%6d\n" % cor
        return ("  0\nLINE\n  5\n%X\n100\nAcDbEntity\n  8\n%s\n%s%s100\nAcDbLine\n"
                " 10\n%g\n 20\n%g\n 30\n0\n 11\n%g\n 21\n%g\n 31\n0\n"
                % (handle, camada, grupo_cor, extra, x, y, x + dx, y + dy))

    def texto(handle, camada, cor, x, y, altura, conteudo):
        return ("  0\nTEXT\n  5\n%X\n100\nAcDbEntity\n  8\n%s\n 62\n%6d\n100\nAcDbText\n"
                " 10\n%g\n 20\n%g\n 30\n0\n 40\n%g\n  1\n%s\n 50\n0\n100\nAcDbText\n"
                % (handle, camada, cor, x, y, altura, conteudo))

    # ---- entidades pintadas individualmente, na mesma camada
    pintadas = ""
    for i, aci in enumerate([1, 3, 4, 5, 6, 30, 163, 210]):
        pintadas += linha(0xB10000 + i, "Detalhes", aci,
                          X0 + 40 + i * 55, Y0 + 660)
    # cor verdadeira de 24 bits, fora da paleta indexada
    pintadas += linha(0xB10010, "Detalhes", None, X0 + 40, Y0 + 700,
                      extra="420\n%d\n" % 0x8A2BE2)

    # ---- bloco com pecas de cores diferentes
    bloco = ("  0\nBLOCK\n  5\nB20000\n100\nAcDbEntity\n  8\n0\n100\nAcDbBlockBegin\n"
             "  2\nSIMBOLO\n 70\n     0\n 10\n0\n 20\n0\n 30\n0\n  3\nSIMBOLO\n  1\n\n"
             "  0\nLINE\n  5\nB20001\n100\nAcDbEntity\n  8\n0\n 62\n     0\n100\nAcDbLine\n"
             " 10\n0\n 20\n0\n 30\n0\n 11\n18\n 21\n0\n 31\n0\n"
             "  0\nLINE\n  5\nB20002\n100\nAcDbEntity\n  8\n0\n 62\n     1\n100\nAcDbLine\n"
             " 10\n18\n 20\n0\n 30\n0\n 11\n12\n 21\n6\n 31\n0\n"
             "  0\nENDBLK\n  5\nB20003\n100\nAcDbEntity\n  8\n0\n100\nAcDbBlockEnd\n")
    insercoes = ""
    for i, aci in enumerate([3, 5]):
        insercoes += ("  0\nINSERT\n  5\n%X\n100\nAcDbEntity\n  8\nSimbolos\n 62\n%6d\n"
                      "100\nAcDbBlockReference\n  2\nSIMBOLO\n 10\n%g\n 20\n%g\n 30\n0\n"
                      % (0xB30000 + i, aci, X0 + 60 + i * 120, Y0 + 740))

    # ---- texto acentuado, como no desenho original
    acentos = ""
    linhas = ["CONVENÇÕES", "COORDENADAS DOS PIEZÔMETROS",
              "Geográfica: Datum SIRGAS 2000", "COTA ALTIMÉTRICA",
              "PROFUNDIDADE DO NÍVEL FREÁTICO", "CARGA HIDRÁULICA",
              "Azimute 45° ± 2°"]
    for i, conteudo in enumerate(linhas):
        acentos += texto(0xB40000 + i, "Acentos", 1 if i == 0 else 7,
                         X0 + 760, Y0 + 300 - i * 30, 16.0, conteudo)

    # declara as camadas novas e injeta tudo
    registros = ""
    for i, (nome, aci) in enumerate([("Detalhes", 7), ("Simbolos", 7), ("Acentos", 7)]):
        registros += ("  0\nLAYER\n  5\n%X\n100\nAcDbSymbolTableRecord\n"
                      "100\nAcDbLayerTableRecord\n  2\n%s\n 70\n     0\n 62\n%6d\n"
                      "  6\nContinuous\n" % (0xB50000 + i, nome, aci))
    marca = corpo.index("  0\nENDTAB", corpo.index("\nLAYER\n"))
    corpo = corpo[:marca] + registros + corpo[marca:]

    marca = corpo.index("  0\nENDSEC", corpo.index("\nBLOCKS\n"))
    corpo = corpo[:marca] + bloco + corpo[marca:]

    marca = corpo.index("  0\nENDSEC", corpo.index("\nENTITIES\n"))
    return corpo[:marca] + pintadas + insercoes + acentos + corpo[marca:]


if __name__ == "__main__":
    destino = sys.argv[1] if len(sys.argv) > 1 else "mapa_exemplo.dxf"
    os.makedirs(os.path.dirname(os.path.abspath(destino)), exist_ok=True)
    print("gerado:", gerar(os.path.abspath(destino)))
