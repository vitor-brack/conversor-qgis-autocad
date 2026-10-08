# -*- coding: utf-8 -*-
"""
Confere no QGIS de verdade as texturas de hachura e o logo formatado.

Cada camada e desenhada sozinha e os pixels sao contados: as linhas do padrao
aparecem dentro da hachura? cada amostra da legenda tem a sua cor? "Geo" sai
azul e "sana" verde? o topo das letras fica na altura da ancora, como no
AutoCAD?

No carimbo, conta as linhas que o QGIS DESENHOU, pela altura da caixa de cada
rotulo -- e nao as que o texto pede. Contar as quebras do texto nao pegaria o
QGIS jogando fora a quebra e desenhando tudo numa linha so, que foi o que
aconteceu no mapa real.

Roda com o Python do QGIS:
    python-qgis-ltr.bat verificar_texturas_no_qgis.py plot.qgs esperado.json saida.png
"""
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")

from qgis.core import (QgsApplication, QgsMapRendererSequentialJob, QgsMapSettings,
                       QgsProject, QgsRectangle)
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor

X0, Y0 = 412000.0, 6711000.0
PX_POR_M = 6
EXTENSAO = (-10, -130, 300, 140)           # em metros, relativo a X0/Y0

# medidas da Arial nos rotulos do QGIS (ver conversor/textos_cad.py)
CAP, ASC, DESC = 0.7167, 0.905, 0.215
LINHA_CAD = 5.0 / 3.0
QUEBRA = "¶"

ok = fail = 0


def checar(nome, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("  [OK]   %s %s" % (nome, extra))
    else:
        fail += 1
        print("  [FALHA] %s %s" % (nome, extra))


def renderizar(projeto, camadas):
    xmin, ymin, xmax, ymax = EXTENSAO
    ms = QgsMapSettings()
    ms.setLayers(camadas)
    ms.setDestinationCrs(projeto.crs())
    ms.setBackgroundColor(QColor(255, 255, 255))
    ms.setExtent(QgsRectangle(X0 + xmin, Y0 + ymin, X0 + xmax, Y0 + ymax))
    ms.setOutputSize(QSize((xmax - xmin) * PX_POR_M, (ymax - ymin) * PX_POR_M))
    job = QgsMapRendererSequentialJob(ms)
    job.start()
    job.waitForFinished()
    return job


def desenhar(projeto, camadas):
    return renderizar(projeto, camadas).renderedImage()


def sem_html(texto):
    """Rotulo em HTML -> texto puro, com as linhas separadas por quebra comum."""
    import html
    import re
    texto = texto.replace(QUEBRA, "\n")
    return html.unescape(re.sub(r"<[^>]+>", "", texto))


def pixel(x, y):
    """metros (relativos) -> pixel"""
    return int((x - EXTENSAO[0]) * PX_POR_M), int((EXTENSAO[3] - y) * PX_POR_M)


def contar(img, caixa, teste):
    x1, y1 = pixel(caixa[0], caixa[3])
    x2, y2 = pixel(caixa[2], caixa[1])
    n = 0
    for px in range(x1, x2):
        for py in range(y1, y2):
            if teste(QColor(img.pixel(px, py))):
                n += 1
    return n, (x2 - x1) * (y2 - y1)


def perto(cor_hex, tolerancia=70):
    alvo = QColor(cor_hex)
    return lambda c: (abs(c.red() - alvo.red()) + abs(c.green() - alvo.green())
                      + abs(c.blue() - alvo.blue())) < tolerancia


def fora_da_reta(cor_hex):
    """Pixel que nao e mistura de branco com a cor-alvo: outra cor de verdade."""
    alvo = QColor(cor_hex)
    d = (alvo.red() - 255, alvo.green() - 255, alvo.blue() - 255)
    norma = float(d[0] ** 2 + d[1] ** 2 + d[2] ** 2) or 1.0

    def teste(c):
        v = (c.red() - 255, c.green() - 255, c.blue() - 255)
        a = (v[0] * d[0] + v[1] * d[1] + v[2] * d[2]) / norma
        return sum((v[i] - a * d[i]) ** 2 for i in range(3)) ** 0.5 >= 45
    return teste


def tinta(cor_hex):
    """Pixel desenhado com a cor-alvo, mesmo suavizado.

    Uma linha fina e desenhada com suavizacao: o pixel sai como uma mistura da
    cor com o branco do fundo (o preto vira cinza, o azul vira azul-claro).
    Esse pixel fica na reta entre o branco e a cor; a conta mede quanto ele
    avancou nessa reta e o quanto se afastou dela.
    """
    alvo = QColor(cor_hex)
    d = (alvo.red() - 255, alvo.green() - 255, alvo.blue() - 255)
    norma = float(d[0] ** 2 + d[1] ** 2 + d[2] ** 2) or 1.0

    def teste(c):
        v = (c.red() - 255, c.green() - 255, c.blue() - 255)
        a = (v[0] * d[0] + v[1] * d[1] + v[2] * d[2]) / norma
        resto = sum((v[i] - a * d[i]) ** 2 for i in range(3)) ** 0.5
        return a > 0.15 and resto < 45
    return teste


def main():
    caminho_qgs, caminho_json, saida_png = sys.argv[1:4]
    esperado = json.load(open(caminho_json, encoding="utf-8"))
    QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", ""), True)
    app = QgsApplication([], False)
    app.initQgis()

    projeto = QgsProject.instance()
    checar("o QGIS aceitou o projeto", projeto.read(caminho_qgs))
    camadas = {c.name(): c for c in projeto.mapLayers().values()}
    checar("todas as camadas validas", all(c.isValid() for c in camadas.values()),
           "-> %s" % sorted(camadas))
    desenhar(projeto, list(camadas.values())).save(saida_png)

    print("\n=== TEXTURA DO PERFIL (padrao CROSS) ===")
    perfil = camadas.get(esperado["perfil"]["camada"])
    checar("camada de textura do perfil existe", perfil is not None)
    if perfil:
        img = desenhar(projeto, [perfil])
        pintado, total = contar(img, esperado["perfil"]["area"], tinta(esperado["perfil"]["cor"]))
        checar("cruzes desenhadas abaixo do terreno", 0.01 < pintado / total < 0.5,
               "-> %.1f%% da area com tinta" % (100.0 * pintado / total))
        acima, total_acima = contar(img, (5, 47, 170, 58), tinta(esperado["perfil"]["cor"]))
        checar("nada acima do terreno (a borda em spline recorta)", acima == 0,
               "-> %d pixels" % acima)

    print("\n=== AMOSTRAS DA LEGENDA ===")
    legenda = camadas.get("Legenda_Textura")
    checar("camada de textura da legenda existe", legenda is not None)
    if legenda:
        img = desenhar(projeto, [legenda])
        for cor, caixa in esperado["legenda"]:
            pintado, total = contar(img, caixa, tinta(cor))
            branco, _ = contar(img, caixa, perto("#ffffff", 30))
            outras, _ = contar(img, caixa, fora_da_reta(cor))
            checar("amostra %s com padrao (nem vazia, nem chapada)" % cor,
                   0.02 < pintado / total < 0.8 and branco > 0.1 * total,
                   "-> %.0f%% tinta, %.0f%% fundo" % (100.0 * pintado / total, 100.0 * branco / total))
            checar("amostra %s so na sua cor" % cor, outras < 0.02 * total,
                   "-> %.1f%% de outras cores" % (100.0 * outras / total))

    print("\n=== LOGO ===")
    texto = camadas.get("Logo_Texto")
    checar("camada do logo existe", texto is not None)
    if texto:
        cfg = texto.labeling().settings()
        checar("rotulo em HTML", cfg.format().allowHtmlFormatting() and cfg.fieldName == "txt_html",
               "-> campo %s" % cfg.fieldName)
        img = desenhar(projeto, [texto])
        logo = esperado["logo"]
        caixa = (logo["x"] - 2, logo["ancora_y"] - 20, logo["x"] + 80, logo["ancora_y"] + 6)
        azul = [], []
        verde = [], []
        x1, y1 = pixel(caixa[0], caixa[3])
        x2, y2 = pixel(caixa[2], caixa[1])
        for px in range(x1, x2):
            for py in range(y1, y2):
                c = QColor(img.pixel(px, py))
                if c.blue() > 160 and c.red() < 90 and c.green() < 90:
                    azul[0].append(px), azul[1].append(py)
                elif c.green() > 160 and c.red() < 90 and c.blue() < 90:
                    verde[0].append(px), verde[1].append(py)
        checar("'Geo' em azul", len(azul[0]) > 200, "-> %d pixels" % len(azul[0]))
        checar("'sana' em verde", len(verde[0]) > 200, "-> %d pixels" % len(verde[0]))
        if azul[0] and verde[0]:
            checar("'Geo' antes de 'sana'", max(azul[0]) <= min(verde[0]) + 2)
            topo = EXTENSAO[3] - min(azul[1]) / float(PX_POR_M)
            desvio = topo - logo["ancora_y"]
            checar("topo das letras na altura da ancora (como no AutoCAD)",
                   abs(desvio) < 0.06 * logo["altura"],
                   "-> topo em %.2f, ancora em %.2f (desvio %.2f m)"
                   % (topo, logo["ancora_y"], desvio))

    print("\n=== CARIMBO (texto formatado de varias linhas) ===")
    carimbo = camadas.get("Carimbo_Texto")
    checar("camada do carimbo existe", carimbo is not None)
    if carimbo:
        cfg = carimbo.labeling().settings()
        checar("rotulo em HTML", cfg.format().allowHtmlFormatting() and cfg.fieldName == "txt_html",
               "-> campo %s" % cfg.fieldName)
        job = renderizar(projeto, [carimbo])
        job.renderedImage().save(saida_png[:-4] + "_carimbo.png")
        rotulos = {}
        for lp in job.takeLabelingResults().allLabels():
            rotulos.setdefault(sem_html(lp.labelText), []).append(lp.labelRect)
        for e in esperado["carimbo"]:
            nome = e["texto"].split("\n")[0][:32]
            h = e["altura"]
            tam = h / CAP
            ax, ay = e["ancora"]
            alinhado = {"Left": lambda r: r.xMinimum(), "Right": lambda r: r.xMaximum(),
                        "Center": lambda r: r.center().x()}[e["h"]]
            # cada linha e um rotulo: o que tem o texto da linha e esta alinhado
            # na ancora
            linhas = []
            for texto in e["texto"].split("\n"):
                candidatos = sorted(rotulos.get(texto, []),
                                    key=lambda r: abs(alinhado(r) - (X0 + ax)))
                linhas.append(candidatos[0] if candidatos else None)
            faltam = [t for t, r in zip(e["texto"].split("\n"), linhas) if r is None]
            checar("'%s': as %d linha(s) desenhadas, nenhuma palavra colada"
                   % (nome, e["linhas"]), not faltam, "-> faltou %r" % faltam)
            if faltam:
                continue
            desvio_h = max(abs(alinhado(r) - (X0 + ax)) for r in linhas)
            checar("  alinhado na ancora (%s)" % e["h"], desvio_h < 0.3,
                   "-> desvio %.2f m" % desvio_h)
            # o espacamento entre as linhas DESENHADAS, que e o que o olho ve
            if len(linhas) > 1:
                passos = [(linhas[k].yMinimum() - linhas[k + 1].yMinimum()) / h
                          for k in range(len(linhas) - 1)]
                checar("  espacamento entre as linhas igual ao do AutoCAD (5/3 da altura)",
                       all(abs(p - LINHA_CAD) < 0.03 for p in passos),
                       "-> %s" % ", ".join("%.3f" % p for p in passos))
            # a primeira linha na base do AutoCAD (a caixa e a da Arial; a
            # Bookman tem a parte de baixo um pouco diferente, dai a folga)
            n = len(linhas)
            primeira = {"Top": ay - h, "Bottom": ay + 0.2778 * h + (n - 1) * LINHA_CAD * h,
                        "Half": ay + (h + (n - 1) * LINHA_CAD * h + 0.2778 * h) / 2 - h}[e["v"]]
            desvio = linhas[0].yMinimum() + DESC * tam - Y0 - primeira
            checar("  na altura do AutoCAD (%s)" % e["v"], abs(desvio) < 0.12 * h + 0.05,
                   "-> desvio %.2f m (altura da letra %.1f)" % (desvio, h))
            x1, y1, x2, y2 = e["celula"]
            folga = 0.3
            fora = [r for r in linhas
                    if not (r.xMinimum() >= X0 + x1 - folga and r.xMaximum() <= X0 + x2 + folga
                            and r.yMinimum() >= Y0 + y1 - folga
                            and r.yMaximum() <= Y0 + y2 + folga)]
            checar("  dentro da sua celula do carimbo", not fora,
                   "-> %s" % ["x %.1f..%.1f y %.1f..%.1f" % (r.xMinimum() - X0, r.xMaximum() - X0,
                                                            r.yMinimum() - Y0, r.yMaximum() - Y0)
                              for r in fora])

    print("\n=== PERFIL FUTURO (borda remendada como a do mapa real) ===")
    fut = esperado["futuro"]
    futuro = camadas.get(fut["camada"])
    checar("camada de textura do perfil futuro existe", futuro is not None)
    if futuro:
        img = desenhar(projeto, [futuro])
        tinta_qualquer = lambda c: c.lightness() < 235
        solo, total = contar(img, (3, -124, 97, -113), tinta_qualquer)
        checar("solo hachurado", solo > 0.02 * total, "-> %d pixels" % solo)
        branco, _ = contar(img, fut["escavacao"], tinta_qualquer)
        checar("escavacao inteiramente branca", branco == 0, "-> %d pixels" % branco)
        fatia, _ = contar(img, fut["topo"], tinta_qualquer)
        checar("nada na faixa do topo (a fatia do ezdxf)", fatia == 0, "-> %d pixels" % fatia)

    print("\n=== COTAS (pontas de seta e pontos de definicao) ===")
    cot = esperado["cotas"]
    pintados = camadas.get(cot["camada"])
    checar("pontas de seta e SOLID solto na camada pintada",
           pintados is not None and pintados.featureCount() == cot["solidos"],
           "-> %s" % (pintados.featureCount() if pintados else None))
    if pintados:
        img = desenhar(projeto, [pintados])
        for x, y in cot["pontas"]:
            azul, _ = contar(img, (x - 1.2, y - 1.8, x + 1.2, y + 1.8), perto(cot["cor"], 120))
            checar("ponta de seta desenhada em (%g, %g)" % (x, y), azul > 5, "-> %d pixels" % azul)
        x, y = cot["solto"]
        azul, _ = contar(img, (x - 2, y - 2, x + 2, y + 2), perto(cot["cor"], 120))
        checar("SOLID solto desenhado e pintado", azul > 10, "-> %d pixels" % azul)
    checar("nenhuma camada de pontos de definicao (Defpoints)",
           not [n for n in camadas if n.lower().startswith("defpoints")])

    print("\n=== TITULO COMPRIMIDO (fator 0,85) ===")
    # textos_cad e Python puro: da para usar a tabela de larguras da Arial aqui
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from conversor import textos_cad
    comp = esperado["comprimido"]
    legenda = camadas.get("Legenda_Texto")
    rotulo = None
    if legenda:
        job = renderizar(projeto, [legenda])
        rotulo = next((lp.labelRect for lp in job.takeLabelingResults().allLabels()
                       if sem_html(lp.labelText) == comp["texto"]), None)
    checar("titulo comprimido desenhado", rotulo is not None)
    if rotulo:
        normal = textos_cad.largura_texto(comp["texto"], comp["altura"])
        checar("na largura normal da letra, sem encavalar (o QGIS 4 o espremia a 85%)",
               abs(rotulo.width() / normal - 1.0) < 0.05,
               "-> %.1f m, normal %.1f m (85%% seria %.1f)"
               % (rotulo.width(), normal, 0.85 * normal))

    print("\n=== MARTELO (hachuras solidas dentro de bloco) ===")
    martelo = camadas.get("Logo_Hachura")
    checar("hachuras do bloco convertidas", martelo is not None and martelo.featureCount() == 2)
    if martelo:
        img = desenhar(projeto, [martelo])
        cinza, _ = contar(img, (11, 109, 23, 111), perto("#545454", 40))
        azul, _ = contar(img, (15.5, 95, 17.5, 106), perto("#0000ff", 60))
        checar("cabeca cinza preenchida", cinza > 50, "-> %d pixels" % cinza)
        checar("cabo azul (cor herdada do bloco)", azul > 50, "-> %d pixels" % azul)

    print("\n%d passaram, %d falharam" % (ok, fail))
    app.exitQgis()
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
