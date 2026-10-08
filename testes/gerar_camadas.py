# -*- coding: utf-8 -*-
"""
Monta um DXF com os casos dos outros desenhos de teste (Desm_Ext.Condominio e
LOTEAMENTO):

  - camadas DESLIGADA e CONGELADA com linha, ponto, texto e hachura, longe do
    resto do desenho (no Condominio, 69% das entidades estavam em camadas
    desligadas, em coordenadas absurdas, e apareciam no QGIS);
  - a folha de impressao no ESPACO DE PAPEL (moldura e carimbo da aba Layout),
    que o GDAL mistura com o desenho;
  - pontos com estilo de ponto do AutoCAD: $PDMODE 34 (circulo com cruz) e
    $PDSIZE 2 (unidades do desenho);
  - um rotulo de letra comprimida a 57% seguido do valor, como no carimbo do
    INCRA do LOTEAMENTO -- na largura normal, o rotulo atropelava o valor; e
    um titulo em Verdana a 85%, como os do PLOT, que nao pode mudar;
  - linhas de cores diferentes uma por cima da outra, em camadas diferentes,
    como o contorno dos lotes do Condominio (roxo na "0", verde na "terreno"):
    a de cima no AutoCAD tem de ficar por cima no QGIS;
  - o quadro de "situacoes cartograficas" do LOTEAMENTO, copiado: textos em
    simplex a 83% num bloco inserido a 75%, com o atributo 45 nos quatro
    espacos de "MERIDIANO CENTRAL    %%d WGr" -- na Arial o "CENTRAL" passava
    por cima do 45 -- e a primeira linha terminando rente a borda do quadro.

Devolve o caminho e o que se espera de cada caso.
"""
import os
import sys

import ezdxf
from ezdxf.enums import TextEntityAlignment

X0, Y0 = 500000.0, 7000000.0
LONGE = 100000.0           # as camadas escondidas ficam 100 km para o lado


def p(x, y):
    return (X0 + x, Y0 + y)


def gerar(pasta):
    os.makedirs(pasta, exist_ok=True)
    doc = ezdxf.new("R2004")
    doc.header["$PDMODE"] = 34
    doc.header["$PDSIZE"] = 2.0
    msp = doc.modelspace()
    doc.layers.add("Visivel", color=7)
    doc.layers.add("Pontos", color=5)
    doc.layers.add("Carimbo", color=7)
    desligada = doc.layers.add("Desligada", color=1)
    desligada.off()
    congelada = doc.layers.add("Congelada", color=3)
    congelada.freeze()

    # ---- o desenho visivel: um quadrado de 100 x 60 e tres pontos
    msp.add_lwpolyline([p(0, 0), p(100, 0), p(100, 60), p(0, 60)], close=True,
                       dxfattribs={"layer": "Visivel"})
    msp.add_text("AREA VISIVEL", height=3, dxfattribs={"layer": "Visivel"}).set_placement(p(5, 52))
    pontos = [(20, 20), (50, 20), (80, 20)]
    for x, y in pontos:
        msp.add_point(p(x, y), dxfattribs={"layer": "Pontos"})

    # ---- camadas que o AutoCAD nao mostra, bem longe
    for camada, dx in (("Desligada", LONGE), ("Congelada", -LONGE)):
        msp.add_line(p(dx, 0), p(dx + 50, 50), dxfattribs={"layer": camada})
        msp.add_point(p(dx + 10, 10), dxfattribs={"layer": camada})
        msp.add_text("ESCONDIDO", height=3, dxfattribs={"layer": camada}).set_placement(p(dx, 30))
        h = msp.add_hatch(color=256, dxfattribs={"layer": camada})
        h.paths.add_polyline_path([p(dx, 0), p(dx + 20, 0), p(dx + 20, 20), p(dx, 20)], is_closed=True)

    # ---- folha de impressao: espaco de papel, em coordenadas de papel
    papel = doc.paperspace()
    papel.add_lwpolyline([(0, 0), (420, 0), (420, 297), (0, 297)], close=True,
                         dxfattribs={"layer": "Visivel"})
    papel.add_text("CARIMBO DA FOLHA", height=5, dxfattribs={"layer": "Visivel"}).set_placement((300, 20))

    # ---- rotulo comprimido (57%) e o valor logo depois, como no INCRA
    rotulo = "Matrículas/Transcrições:"
    msp.add_text(rotulo, height=1.68, dxfattribs={"layer": "Carimbo", "width": 0.5727}
                 ).set_placement(p(5, 40))
    # No AutoCAD o rotulo (57%) tem 14,6 de largura e acaba em x = 19,6; o
    # valor comeca com a folga do desenho real (32% do rotulo), em x = 24,3.
    # Na largura normal da Arial o rotulo iria ate x = 30,5, por cima do valor.
    msp.add_text("1.234", height=2.52, dxfattribs={"layer": "Carimbo"}).set_placement(p(24.3, 40))
    # titulo em Verdana a 85%, como os do PLOT: nao pode encolher
    doc.styles.add("VERDANA", font="verdana.ttf")
    titulo = "PLANTA ESQUEMATICA DA SITUACAO ATUAL"
    msp.add_text(titulo, height=3.5, dxfattribs={"layer": "Carimbo", "style": "VERDANA",
                                                  "width": 0.85}).set_placement(p(5, 30))

    # ---- linhas de cores diferentes, uma por cima da outra, em camadas
    # diferentes. A ordem alfabetica erra nos dois casos de proposito.
    # A) como no Condominio: roxa na "0", verde na "terreno" desenhada depois
    msp.add_line(p(10, 50), p(90, 50), dxfattribs={"layer": "0", "color": 6})
    msp.add_lwpolyline([p(10, 50), p(90, 50)], dxfattribs={"layer": "terreno", "color": 3})
    # B) a vermelha foi desenhada ANTES, mas trazida para frente (DRAWORDER),
    #    o que fica na tabela SORTENTSTABLE
    frente = msp.add_line(p(10, 45), p(90, 45), dxfattribs={"layer": "Zfrente", "color": 1})
    msp.add_line(p(10, 45), p(90, 45), dxfattribs={"layer": "Atras", "color": 5})
    msp.set_redraw_order([(frente.dxf.handle, "FFFFF")])

    # ---- o quadro do LOTEAMENTO, com as medidas de la (unidades do bloco)
    doc.styles.add("SIMPLEX", font="simplex")
    quadro = doc.blocks.new("QUADRO_CARTOGRAFICO")
    simplex = {"layer": "Quadro", "style": "SIMPLEX", "height": 1.12, "width": 0.8273}
    for texto, y in (("PROJEÇÃO UNIVERSAL TRANSVERSA DE MERCATOR", 5.774),
                     ("MERIDIANO CENTRAL    %%d WGr", 0.0), ("LATITUDE  =", -5.342)):
        quadro.add_text(texto, dxfattribs=simplex).set_placement((0.0, y))
    quadro.add_attdef("MERIDIANO", dxfattribs=simplex).set_placement(
        (QUADRO["centro_45"], 0.0), align=TextEntityAlignment.CENTER)
    quadro.add_line((QUADRO["borda"], -8.0), (QUADRO["borda"], 8.0), dxfattribs={"layer": "Quadro"})
    msp.add_blockref("QUADRO_CARTOGRAFICO", p(*QUADRO["insercao"]),
                     dxfattribs={"layer": "Quadro", "xscale": QUADRO["escala"],
                                 "yscale": QUADRO["escala"]}).add_auto_attribs({"MERIDIANO": "45"})

    caminho = os.path.join(pasta, "camadas.dxf")
    doc.saveas(caminho)
    esperado = {
        "visivel": (0, 0, 100, 60),
        "ocultas": ["Desligada", "Congelada"],
        "longe": LONGE,
        "pontos": pontos, "pdsize": 2.0, "cor_pontos": "#0000ff",
        "papel": ["CARIMBO DA FOLHA"],
        "rotulo": {"texto": rotulo, "altura": 1.68, "fator": 0.5727, "valor": "1.234"},
        "titulo": {"texto": titulo, "altura": 3.5},
        "sobrepostas": [
            {"cima": "terreno_LineString", "baixo": "0_LineString", "ponto": (50, 50),
             "cor": "#00ff00", "cor_baixo": "#ff00ff", "como": "desenhada depois"},
            {"cima": "Zfrente_LineString", "baixo": "Atras_LineString", "ponto": (50, 45),
             "cor": "#ff0000", "cor_baixo": "#0000ff",
             "como": "trazida para frente (SORTENTSTABLE)"},
        ],
        "quadro": dict(QUADRO, altura=1.12 * QUADRO["escala"], fator=0.8273,
                       antes="MERIDIANO CENTRAL", depois="° WGr", valor="45",
                       primeira="PROJEÇÃO UNIVERSAL TRANSVERSA DE MERCATOR",
                       recuo="MERIDIANO CENTRAL    "),
    }
    return caminho, esperado


# O quadro do LOTEAMENTO em unidades do bloco: o 45 centrado a 16 do inicio
# dos textos, a borda direita a 36,55 (a primeira linha termina 1 antes dela no
# AutoCAD), o bloco inserido a 75% em (5, 8) do desenho.
QUADRO = {"centro_45": 16.0, "borda": 36.547, "escala": 0.75, "insercao": (5.0, 8.0)}


def gerar_so_papel(pasta):
    """Um desenho feito todo no espaco de papel: ai a folha e o desenho."""
    os.makedirs(pasta, exist_ok=True)
    doc = ezdxf.new("R2004")
    papel = doc.paperspace()
    papel.add_lwpolyline([(0, 0), (420, 0), (420, 297), (0, 297)], close=True)
    papel.add_text("SO NO PAPEL", height=5).set_placement((300, 20))
    caminho = os.path.join(pasta, "so_papel.dxf")
    doc.saveas(caminho)
    return caminho


if __name__ == "__main__":
    destino = sys.argv[1] if len(sys.argv) > 1 else "camadas"
    print("gerado:", gerar(os.path.abspath(destino))[0])
