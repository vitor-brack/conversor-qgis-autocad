# -*- coding: utf-8 -*-
"""
Monta um DXF com os casos da folha "PLOT" do mapa real:

  - um PERFIL: grade de linhas, terreno em spline e, abaixo dele, hachura com
    padrao CROSS (as cruzes), cuja borda inclui a spline -- o GDAL nao fecha
    essa borda e a hachura sumia;
  - uma LEGENDA com tres amostras de padrao (DASH azul, GRAVEL marrom, ANSI31
    azul-petroleo), que chegavam como cor lisa;
  - o LOGO: MTEXT ancorado pelo topo com "Geo" azul e "sana" verde na fonte
    Arial Rounded MT Bold, e um martelo feito de hachuras solidas num bloco;
  - um CARIMBO com o texto do mapa real: Bookman Old Style negrito (o real e
    Times New Roman num estilo de largura 1,4 -- ver o README), num estilo de
    texto largo (fator 1,15), com quebras escritas (\\P) e um titulo que o
    proprio AutoCAD quebra na largura do quadro. Cada texto grava a fonte de
    um jeito que o AutoCAD aceita -- familia, arquivo, arquivo sem extensao,
    nome completo -- e um deles usa uma fonte que nao existe. Foi num carimbo
    assim que as linhas grudaram ("daJazida");
  - um PERFIL FUTURO com a borda remendada do PLOT.dwg, uma COTA e um titulo
    COMPRIMIDO (ver _perfil_futuro, _cotas e gerar).

O arquivo e gravado como o ODA File Converter grava: bytes UTF-8 com
$DWGCODEPAGE = ANSI_1252 no cabecalho.

Devolve o caminho e o que se espera de cada caso.
"""
import os
import sys

import ezdxf

X0, Y0 = 412000.0, 6711000.0
BS = chr(92)


def p(x, y):
    return (X0 + x, Y0 + y)


def gerar(pasta):
    os.makedirs(pasta, exist_ok=True)
    doc = ezdxf.new("R2004")
    msp = doc.modelspace()
    for nome, cor in [("Perfil", 7), ("Grade", 7), ("Legenda", 7), ("Logo", 7)]:
        doc.layers.add(nome, color=cor)

    # ---- PERFIL: grade, terreno e hachura CROSS abaixo do terreno
    for i in range(13):
        cor = 6 if i % 5 == 0 else 7
        msp.add_line(p(0, i * 5), p(180, i * 5), dxfattribs={"layer": "Grade", "color": cor})
    terreno = [p(0, 40), p(20, 45), p(50, 38), p(90, 35), p(120, 25), p(150, 18), p(180, 2)]
    # com pontos de controle, como o AutoCAD grava (so com pontos de passagem
    # o GDAL nao le a spline)
    msp.add_cad_spline_control_frame(terreno, dxfattribs={"layer": "Perfil"})
    h = msp.add_hatch(dxfattribs={"layer": "Perfil"})
    # atencao: set_pattern_fill tem cor propria (padrao 7) e sobrescreve a da
    # hachura -- a cor precisa ir aqui
    h.set_pattern_fill("CROSS", color=256, scale=0.5)
    borda = h.paths.add_edge_path()
    borda.add_line(p(180, 2), p(180, 0))
    borda.add_line(p(180, 0), p(0, 0))
    borda.add_line(p(0, 0), p(0, 40))
    borda.add_spline(fit_points=terreno)

    # ---- LEGENDA: tres amostras de padrao
    amostras = [("DASH", 5, 0.25, "Bacia de Sedimentação"),
                ("GRAVEL", 30, 0.12, "Rejeito Matacões"),
                ("ANSI31", 132, 0.12, "Rejeito Solo")]
    for i, (padrao, cor, escala, rotulo) in enumerate(amostras):
        y = 70 - i * 18
        canto = [p(220, y), p(232, y), p(232, y + 12), p(220, y + 12)]
        msp.add_lwpolyline(canto, close=True, dxfattribs={"layer": "Legenda", "color": 7})
        hh = msp.add_hatch(dxfattribs={"layer": "Legenda"})
        hh.set_pattern_fill(padrao, color=cor, scale=escala)
        hh.paths.add_polyline_path(canto, is_closed=True)
        msp.add_text(rotulo, height=4, dxfattribs={"layer": "Legenda"}).set_placement(p(238, y + 4))
    msp.add_text("LEGENDA", height=8, dxfattribs={"layer": "Legenda"}).set_placement(p(222, 88))

    # ---- LOGO: MTEXT colorido ancorado pelo topo, e o martelo num bloco
    logo = ("{" + BS + "fArial Rounded MT Bold|b1|i0|c0|p34;" + BS + "C5;Geo"
            + BS + "C3;sana}")
    msp.add_mtext(logo, dxfattribs={"layer": "Logo", "char_height": 10,
                                    "insert": p(30, 118), "attachment_point": 1})
    martelo = doc.blocks.new("MARTELO")
    cabeca = martelo.add_hatch(color=250)
    cabeca.paths.add_polyline_path([(0, 8), (14, 8), (14, 12), (0, 12)], is_closed=True)
    cabo = martelo.add_hatch(color=0)                           # ByBlock: fica azul
    cabo.paths.add_polyline_path([(5, -6), (8, -6), (8, 8), (5, 8)], is_closed=True)
    msp.add_blockref("MARTELO", p(10, 100), dxfattribs={"layer": "Logo", "color": 5})

    # bloco com hachura de padrao inserido ESPELHADO: o ezdxf original devolve
    # cada linha duas vezes nesse caso, uma delas fora do desenho
    simbolo = doc.blocks.new("SIMBOLO")
    hs = simbolo.add_hatch()
    hs.set_pattern_fill("ANSI31", color=1, scale=0.1)
    hs.paths.add_polyline_path([(0, 0), (8, 0), (8, 8), (0, 8)], is_closed=True)
    msp.add_blockref("SIMBOLO", p(270, 10), dxfattribs={"layer": "Legenda", "xscale": -1})

    carimbo = _carimbo(doc, msp)
    futuro = _perfil_futuro(msp)
    cotas = _cotas(doc, msp)
    # titulo com letra comprimida (fator 0,85), como os titulos das plantas do
    # mapa real: no QGIS 4 as letras se encavalavam e os espacos sumiam
    comprimido = "PLANTA ESQUEMATICA DA SITUACAO"
    msp.add_text(comprimido, height=4, dxfattribs={"layer": "Legenda", "width": 0.85}
                 ).set_placement(p(130, 125))

    caminho = os.path.join(pasta, "plot.dxf")
    doc.saveas(caminho, encoding="cp1252")
    # como o ODA grava: bytes UTF-8, cabecalho ANSI_1252
    texto = open(caminho, encoding="cp1252").read()
    open(caminho, "w", encoding="utf-8").write(texto)

    esperado = {
        "perfil": {"camada": "Perfil_Textura", "cor": "#000000",
                   "area": (5, 3, 170, 28)},              # onde as cruzes aparecem
        "legenda": [("#0000ff", (221, 71, 231, 81)), ("#ff7f00", (221, 53, 231, 63)),
                    ("#00a5a5", (221, 35, 231, 45))],
        "logo": {"ancora_y": 118.0, "altura": 10.0, "x": 30.0},
        "carimbo": carimbo,
        "futuro": futuro,
        "cotas": cotas,
        "comprimido": {"texto": comprimido, "x": 130.0, "y": 125.0, "altura": 4.0,
                       "fator": 0.85},
    }
    return caminho, esperado


def _perfil_futuro(msp):
    """Perfil com escavacao e a borda da hachura REMENDADA como a do mapa real
    (perfil futuro A-A' do PLOT.dwg): a curva do terreno aparece duas vezes,
    uma em cada sentido, as arestas nao estao em ordem, e a superficie futura
    termina 2 unidades antes do canto onde a borda continua. O AutoCAD
    preenche so o solo abaixo da superficie futura; o ezdxf, ligando as
    arestas na ordem gravada, criava uma fatia ao longo do topo com
    pedacinhos do padrao.

    Padrao ANSI31 (linhas continuas a 45 graus): toda linha que cruzasse a
    fatia deixaria um pedaco nela, entao o defeito nao passa despercebido.
    """
    from ezdxf.math import open_uniform_knot_vector

    terreno = [(0, -95), (15, -96), (35, -99), (55, -98), (75, -99), (90, -97.5), (100, -97)]
    futura = [(100, -97), (90, -97.6), (85, -112), (20, -112), (14, -98.5), (2, -95.2)]
    nos = list(open_uniform_knot_vector(len(terreno), 4))
    msp.add_spline([p(*v) for v in terreno], dxfattribs={"layer": "PerfilFuturo"})
    msp.add_lwpolyline([p(*v) for v in futura], dxfattribs={"layer": "PerfilFuturo"})
    h = msp.add_hatch(dxfattribs={"layer": "PerfilFuturo"})
    h.set_pattern_fill("ANSI31", color=256, scale=0.3)
    borda = h.paths.add_edge_path()
    borda.add_line(p(100, -125), p(100, -97))                               # direita
    borda.add_spline(control_points=[p(*v) for v in terreno], knot_values=nos)  # terreno ->
    for a, b in zip(futura, futura[1:]):                                    # superficie futura
        borda.add_line(p(*a), p(*b))
    borda.add_spline(control_points=[p(*v) for v in reversed(terreno)], knot_values=nos)
    borda.add_line(p(0, -95), p(0, -125))                                   # esquerda
    borda.add_line(p(0, -125), p(100, -125))                                # fundo
    return {
        "camada": "PerfilFuturo_Textura",
        # o que o AutoCAD preenche: abaixo da superficie futura (o vao de 2
        # unidades no canto esquerdo fecha em linha reta)
        "solo": [(0, -125), (100, -125)] + futura + [(0, -95)],
        "escavacao": (25, -110, 80, -100),       # tem de ficar branca
        "topo": (20, -97.2, 80, -95.3),          # onde ficava a fatia (longe das pontas)
    }


def _cotas(doc, msp):
    """Uma cota (feita pelo ezdxf, que monta o bloco como o AutoCAD: pontas de
    seta em SOLID e pontos de definicao na camada Defpoints) e um SOLID
    solto. As pontas sumiam e os pontos de definicao viravam bolinhas."""
    doc.layers.add("Cotas", color=5)
    cota = msp.add_linear_dim(base=p(175, -105), p1=p(160, -122), p2=p(160, -110), angle=90,
                              dimstyle="Standard", override={"dimasz": 1.5, "dimtxt": 2.0},
                              dxfattribs={"layer": "Cotas"})
    cota.render()
    msp.add_solid([p(190, -122), p(193, -116), p(196, -122)], dxfattribs={"layer": "Cotas"})
    return {"camada": "Cotas_Hachura", "solidos": 3, "cor": "#0000ff",
            "pontas": [(175, -122), (175, -110)], "solto": (193, -120)}


def _carimbo(doc, msp):
    """Carimbo abaixo do perfil (y de -75 a -8). Devolve o que se espera de cada
    texto: linhas como o AutoCAD as desenha, celula onde tem de caber, ancora e
    alinhamento, e como a fonte foi gravada."""
    doc.layers.add("Carimbo", color=7)
    doc.layers.add("Grade_Carimbo", color=8)
    doc.styles.add("LARGO", font="bookosb.ttf").dxf.width = 1.15

    celulas = {"logo": (0, -28, 50, -8), "titulo": (50, -28, 136, -8),
               "empreendedor": (0, -42, 96, -28), "data": (96, -42, 136, -28),
               "projeto": (0, -58, 96, -42), "area": (96, -58, 136, -42),
               "resp": (0, -75, 96, -58), "obs": (96, -75, 136, -58)}
    for x1, y1, x2, y2 in celulas.values():
        msp.add_lwpolyline([p(x1, y1), p(x2, y1), p(x2, y2), p(x1, y2)], close=True,
                           dxfattribs={"layer": "Grade_Carimbo"})

    def fonte(nome, negrito=True):
        return BS + "f%s|b%d|i0|c0|p18;" % (nome, 1 if negrito else 0)

    magenta = BS + "C6;"
    P = BS + "P"
    # (conteudo, celula, ancora, attachment_point, altura, largura do quadro,
    #  linhas esperadas, alinhamento no QGIS, como a fonte foi gravada)
    textos = [
        ("{" + fonte("Bookman Old Style") + magenta + "Projeto de Licenciamento de Extração "
         "Mineral de Saibro da Jazida Novo Paris - Holanda - Plano de Controle Ambiental}",
         "titulo", (93, -18), 5, 2.5, 84.5,
         ["Projeto de Licenciamento de Extração", "Mineral de Saibro da Jazida Novo",
          "Paris - Holanda - Plano de Controle", "Ambiental"], "familia"),
        ("{" + fonte("bookosb.ttf", False) + "Empreendedor}", "empreendedor", (1, -29), 1,
         2.0, 0, ["Empreendedor"], "arquivo"),
        ("{" + fonte("Bookman Old Style Bold", False) + magenta + "Município de Brochier}",
         "empreendedor", (48, -37), 5, 2.0, 75, ["Município de Brochier"], "nome completo"),
        ("{" + fonte("BOOKOSB", False) + "Data}", "data", (97, -29), 1, 2.0, 0, ["Data"],
         "arquivo sem extensao"),
        ("{" + fonte("Fonte Que Nao Existe") + magenta + "05/2026}", "data", (116, -37), 5,
         2.0, 30, ["05/2026"], "inexistente"),
        ("{" + fonte("Bookman Old Style") + "Projeto}", "projeto", (1, -43), 1, 2.0, 0,
         ["Projeto"], "familia"),
        ("{" + fonte("Bookman Old Style") + magenta + "Projeto de Extração Mineral -" + P
         + "Planta de Detalhe Pré e Pós Extração -" + P + "Brochier - RS}",
         "projeto", (48, -51.5), 5, 2.0, 75,
         ["Projeto de Extração Mineral -", "Planta de Detalhe Pré e Pós Extração -",
          "Brochier - RS"], "familia"),
        ("{" + fonte("Bookman Old Style") + "Resp. Técnico}", "resp", (1, -59), 1, 2.0, 0,
         ["Resp. Técnico"], "familia"),
        ("{" + fonte("Bookman Old Style") + magenta + "Fulano de Tal da Silva CREA-" + P
         + "000000- D}", "resp", (48, -65), 2, 2.0, 75,
         ["Fulano de Tal da Silva CREA-", "000000- D"], "familia"),
        # sem formatacao nenhuma, na mesma camada dos formatados: vai para o
        # rotulo em HTML pelo caminho do texto simples
        ("Observação:" + P + "linha dois", "obs", (97, -59), 1, 1.8, 0,
         ["Observação:", "linha dois"], "sem fonte"),
    ]
    esperado = []
    for conteudo, celula, (ax, ay), anexo, altura, largura, linhas, forma in textos:
        msp.add_mtext(conteudo, dxfattribs={
            "layer": "Carimbo", "style": "LARGO", "char_height": altura, "width": largura,
            "insert": p(ax, ay), "attachment_point": anexo})
        esperado.append({
            "texto": "\n".join(linhas), "linhas": len(linhas), "celula": celulas[celula],
            # numeracao do MTEXT: 1 2 3 em cima, 4 5 6 no meio, 7 8 9 embaixo
            "ancora": (ax, ay), "h": ("Left", "Center", "Right")[(anexo - 1) % 3],
            "v": ("Top", "Half", "Bottom")[(anexo - 1) // 3],
            "altura": altura, "forma": forma})
    return esperado


if __name__ == "__main__":
    destino = sys.argv[1] if len(sys.argv) > 1 else "texturas"
    caminho, _ = gerar(os.path.abspath(destino))
    print("gerado:", caminho)
