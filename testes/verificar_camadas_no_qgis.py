# -*- coding: utf-8 -*-
"""
Confere no QGIS de verdade o desenho de gerar_camadas.py: camadas desligadas e
congeladas desmarcadas (e sem desenho ao abrir), pontos no estilo do AutoCAD
(circulo com cruz, no tamanho do desenho) e o rotulo comprimido terminando
antes do valor ao lado.

Roda com o Python do QGIS:
    python-qgis-ltr.bat verificar_camadas_no_qgis.py c.qgs esperado.json saida.png
"""
import json
import math
import os
import sys
import warnings

warnings.filterwarnings("ignore")

from qgis.core import (QgsApplication, QgsMapRendererSequentialJob, QgsMapSettings,
                       QgsProject, QgsRectangle)
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor

X0, Y0 = 500000.0, 7000000.0
PX = 10                                 # pixels por unidade do desenho
ok = fail = 0


def checar(nome, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("  [OK]   %s %s" % (nome, extra))
    else:
        fail += 1
        print("  [FALHA] %s %s" % (nome, extra))


def renderizar(projeto, camadas, janela):
    xmin, ymin, xmax, ymax = janela
    ms = QgsMapSettings()
    ms.setLayers(camadas)
    ms.setDestinationCrs(projeto.crs())
    ms.setBackgroundColor(QColor(255, 255, 255))
    ms.setExtent(QgsRectangle(X0 + xmin, Y0 + ymin, X0 + xmax, Y0 + ymax))
    ms.setOutputSize(QSize(int((xmax - xmin) * PX), int((ymax - ymin) * PX)))
    job = QgsMapRendererSequentialJob(ms)
    job.start()
    job.waitForFinished()
    return job


def main():
    caminho_qgs, caminho_json, saida_png = sys.argv[1:4]
    esperado = json.load(open(caminho_json, encoding="utf-8"))
    QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", ""), True)
    app = QgsApplication([], False)
    app.initQgis()
    projeto = QgsProject.instance()
    checar("o QGIS aceitou o projeto", projeto.read(caminho_qgs))
    nos = projeto.layerTreeRoot().findLayers()
    checar("todas as camadas validas", all(n.layer().isValid() for n in nos))

    print("\n=== CAMADAS DESLIGADAS E CONGELADAS ===")
    escondidas = [n for n in nos if n.name().startswith(tuple(esperado["ocultas"]))]
    checar("camadas escondidas no AutoCAD vem desmarcadas",
           escondidas and not any(n.isVisible() for n in escondidas),
           "-> %s" % [(n.name(), n.isVisible()) for n in escondidas])
    marcadas = [n.layer() for n in nos if n.isVisible()]
    longe = esperado["longe"]
    for dx in (longe, -longe):
        job = renderizar(projeto, marcadas, (dx - 5, -5, dx + 60, 55))
        img = job.renderedImage()
        tinta = sum(1 for x in range(0, img.width(), 2) for y in range(0, img.height(), 2)
                    if QColor(img.pixel(x, y)).lightness() < 240)
        checar("nada desenhado a %+d km ao abrir (so o que esta marcado)" % (dx / 1000), tinta == 0,
               "-> %d pixels" % tinta)

    print("\n=== PONTOS NO ESTILO DO AUTOCAD (circulo com cruz) ===")
    job = renderizar(projeto, marcadas, (-5, -5, 105, 65))
    img = job.renderedImage()
    img.save(saida_png)
    s = esperado["pdsize"]
    alvo = QColor(esperado["cor_pontos"])

    def azul(x, y):
        """Ha tinta azul em volta deste ponto (em unidades do desenho)?"""
        px, py = int((x + 5) * PX), int((65 - y) * PX)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                c = QColor(img.pixel(px + dx, py + dy))
                if c.blue() > 150 and c.red() < 150 and c.green() < 150 and c.blue() - c.red() > 60:
                    return True
        return False

    for x, y in esperado["pontos"]:
        anel = sum(azul(x + s / 2 * math.cos(a), y + s / 2 * math.sin(a))
                   for a in [k * math.pi / 8 + math.pi / 16 for k in range(16)])
        bracos = sum(azul(x + d * ex, y + d * ey) for ex, ey in ((1, 0), (-1, 0), (0, 1), (0, -1))
                     for d in (0.75 * s, 0.95 * s))
        miolo = sum(azul(x + 0.25 * s * ex, y + 0.25 * s * ey)
                    for ex, ey in ((0.7, 0.7), (-0.7, 0.7), (0.7, -0.7), (-0.7, -0.7)))
        checar("ponto (%g, %g): circulo de diametro %g" % (x, y, s), anel >= 14, "-> %d/16" % anel)
        checar("ponto (%g, %g): cruz saindo do circulo, ate %g" % (x, y, s), bracos >= 7,
               "-> %d/8" % bracos)
        checar("ponto (%g, %g): por dentro, vazio fora da cruz" % (x, y), miolo == 0,
               "-> %d/4" % miolo)

    print("\n=== LINHAS SOBREPOSTAS ===")
    def distancia(c, hexa):
        alvo = QColor(hexa)
        return (abs(c.red() - alvo.red()) + abs(c.green() - alvo.green())
                + abs(c.blue() - alvo.blue()))

    for caso in esperado["sobrepostas"]:
        x, y = caso["ponto"]
        px, py = int((x + 5) * PX), int((65 - y) * PX)
        # a linha e fina e suavizada: o pixel do meio dela e o mais pintado
        c = min((QColor(img.pixel(px, py + d)) for d in range(-3, 4)),
                key=lambda cor: cor.lightness())
        checar("aparece a cor da linha de cima no AutoCAD (%s, %s)" % (caso["cor"], caso["como"]),
               distancia(c, caso["cor"]) < distancia(c, caso["cor_baixo"]),
               "-> pixel %s (de cima %s, de baixo %s)" % (c.name(), caso["cor"], caso["cor_baixo"]))

    print("\n=== LETRA COMPRIMIDA ===")
    import re as _re
    rot = esperado["rotulo"]
    retangulos = {}
    for lp in job.takeLabelingResults().allLabels():
        retangulos[_re.sub(r"<[^>]+>", "", lp.labelText)] = lp.labelRect
    r1, r2 = retangulos.get(rot["texto"]), retangulos.get(rot["valor"])
    checar("rotulo e valor desenhados", r1 is not None and r2 is not None)
    if r1 is not None and r2 is not None:
        checar("o rotulo acaba antes do valor (na largura normal, ia por cima)",
               r1.xMaximum() < r2.xMinimum(),
               "-> rotulo ate x=%.1f, valor em x=%.1f" % (r1.xMaximum() - X0, r2.xMinimum() - X0))

    print("\n=== QUADRO EM SIMPLEX COM O 45 NO VAO ===")
    q = esperado["quadro"]
    x_ini, y_ini = q["insercao"]
    job = renderizar(projeto, marcadas, (x_ini - 2, y_ini - 6, x_ini + 30, y_ini + 7))
    caixas = {}
    for lp in job.takeLabelingResults().allLabels():
        caixas[_re.sub(r"<[^>]+>", "", lp.labelText)] = lp.labelRect
    antes, valor, depois, primeira = (caixas.get(q[k]) for k in ("antes", "valor", "depois", "primeira"))
    checar("os trechos e o 45 desenhados", None not in (antes, valor, depois, primeira),
           "-> %s" % sorted(caixas))
    if None not in (antes, valor, depois, primeira):
        checar("'%s' acaba antes do 45" % q["antes"], antes.xMaximum() < valor.xMinimum(),
               "-> %.2f < %.2f" % (antes.xMaximum() - X0, valor.xMinimum() - X0))
        checar("o 45 acaba antes do '%s'" % q["depois"], valor.xMaximum() < depois.xMinimum(),
               "-> %.2f < %.2f" % (valor.xMaximum() - X0, depois.xMinimum() - X0))
        borda = x_ini + q["borda"] * q["escala"]
        checar("a primeira linha acaba antes da borda do quadro", primeira.xMaximum() - X0 < borda,
               "-> %.2f < %.2f" % (primeira.xMaximum() - X0, borda))

    print("\n%d passaram, %d falharam" % (ok, fail))
    app.exitQgis()
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
