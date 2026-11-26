# -*- coding: utf-8 -*-
"""
Confere, dentro do QGIS de verdade, ONDE cada texto foi desenhado.

Nao basta o XML estar certo: o que importa e a caixa que o QGIS ocupa na tela.
Este script abre o projeto, renderiza, pega a caixa de cada rotulo e compara
com o ponto de ancoragem e o alinhamento que o texto tinha no AutoCAD.

Roda com o Python do QGIS:
    python-qgis-ltr.bat verificar_textos_no_qgis.py projeto.qgs esperado.json saida.png
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

CAP = 0.7167          # altura da maiuscula / tamanho, na Arial
ASC = 0.905           # caixa do QGIS acima da linha de base / tamanho
DESC = 0.215          # caixa do QGIS abaixo da linha de base / tamanho
ALTURA_LINHA = ASC + DESC
BAIXO_CAD = 0.2778    # "embaixo" do AutoCAD, abaixo da linha de base / altura
PASSO_CAD = 5.0 / 3.0  # de uma linha de MTEXT para a proxima / altura

ok = fail = 0


def checar(nome, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("  [OK]   %s %s" % (nome, extra))
    else:
        fail += 1
        print("  [FALHA] %s %s" % (nome, extra))


def main():
    caminho_qgs, caminho_json, saida_png = sys.argv[1:4]
    esperado = json.load(open(caminho_json, encoding="utf-8"))

    QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", ""), True)
    app = QgsApplication([], False)
    app.initQgis()

    projeto = QgsProject.instance()
    checar("o QGIS aceitou o projeto", projeto.read(caminho_qgs))
    camadas = list(projeto.mapLayers().values())
    invalidas = [c.name() for c in camadas if not c.isValid()]
    checar("todas as camadas validas", not invalidas, "-> %s" % invalidas)

    # ---- imagem
    print("\n=== IMAGEM ===")
    rasters = [c for c in camadas if c.type() == 1 or c.__class__.__name__ == "QgsRasterLayer"]
    checar("uma camada de imagem (a outra nao existe no disco)", len(rasters) == 1,
           "-> %s" % [c.name() for c in rasters])
    for r in rasters:
        e = r.extent()
        checar("imagem no lugar certo",
               abs(e.xMinimum() - 412310) < 0.01 and abs(e.yMinimum() - 6711110) < 0.01
               and abs(e.xMaximum() - 412340) < 0.01 and abs(e.yMaximum() - 6711120) < 0.01,
               "-> %s" % e.toString(2))
        checar("imagem com sistema de coordenadas", r.crs().authid() == "EPSG:31982",
               "-> %s" % r.crs().authid())
        rend = r.renderer()
        checar("imagem com as cores do arquivo (sem esticar contraste)",
               rend is not None and rend.type() == "multibandcolor"
               and all(getattr(rend, m)() is None or getattr(rend, m)().contrastEnhancementAlgorithm() == 0
                       for m in ("redContrastEnhancement", "greenContrastEnhancement",
                                 "blueContrastEnhancement")),
               "-> %s" % (rend.type() if rend else None))

    # ---- hachuras
    print("\n=== HACHURAS ===")
    for c in camadas:
        if not c.name().endswith("_Hachura"):
            continue
        rend = c.renderer()
        cats = rend.categories() if rend.type() == "categorizedSymbol" else []
        from qgis.PyQt.QtCore import Qt
        try:
            solido = Qt.BrushStyle.SolidPattern      # Qt6 (QGIS 4)
        except AttributeError:
            solido = Qt.SolidPattern                 # Qt5 (QGIS 3)
        for cat in cats:
            sl = cat.symbol().symbolLayer(0)
            padrao = str(cat.value()).endswith("padrão")
            alfa = sl.fillColor().alpha()
            checar("%s %s preenchida%s" % (c.name(), cat.value(),
                                          " (translucida)" if padrao else ""),
                   sl.brushStyle() == solido and (alfa < 128 if padrao else alfa == 255),
                   "-> estilo=%s alfa=%d" % (sl.brushStyle(), alfa))
        # a categoria precisa casar com as feicoes; senao o QGIS nao desenha nada
        casadas = 0
        total = 0
        valores = {str(cat.value()) for cat in cats}
        from qgis.core import QgsExpression, QgsExpressionContext, QgsExpressionContextUtils
        expr = QgsExpression(rend.classAttribute())
        ctx = QgsExpressionContext()
        ctx.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(c))
        for f in c.getFeatures():
            ctx.setFeature(f)
            total += 1
            casadas += 1 if str(expr.evaluate(ctx)) in valores else 0
        checar("%s: toda hachura cai numa categoria" % c.name(), total and casadas == total,
               "-> %d de %d" % (casadas, total))

    # ---- renderiza e mede os rotulos
    ms = QgsMapSettings()
    ms.setLayers(camadas)
    ms.setDestinationCrs(projeto.crs())
    ms.setBackgroundColor(QColor(255, 255, 255))
    ms.setExtent(QgsRectangle(411995, 6710995, 412345, 6711150))
    ms.setOutputSize(QSize(2100, 930))      # 6 px por metro
    job = QgsMapRendererSequentialJob(ms)
    job.start()
    job.waitForFinished()
    job.renderedImage().save(saida_png)
    import html as _html
    import re as _re

    def sem_html(t):
        """Rotulo em HTML -> texto puro, para comparar com o esperado."""
        t = _re.sub(r"<br\s*/?>", "\n", t)
        return _html.unescape(_re.sub(r"<[^>]+>", "", t))

    rotulos = {}
    for lp in job.takeLabelingResults().allLabels():
        rotulos.setdefault(sem_html(lp.labelText), []).append(lp)

    def linhas_do_mtext(texto, ax, hali, tol):
        """Os rotulos das linhas de um MTEXT, de cima para baixo.

        Cada linha e um rotulo proprio. Sao os que estao alinhados na ancora
        e cujo texto e um pedaco do MTEXT; juntos, de cima para baixo, tem de
        dar o texto inteiro (o que o conversor quebrou pela largura do quadro
        tambem)."""
        alvo = " ".join(texto.split())
        candidatos = []
        for t, lista in rotulos.items():
            if " ".join(t.split()) not in alvo:
                continue
            for lp in lista:
                r = lp.labelRect
                x = {"Left": r.xMinimum(), "Right": r.xMaximum(),
                     "Center": r.center().x()}[hali]
                if abs(x - ax) < tol:
                    candidatos.append((r.yMaximum(), t, r))
        candidatos.sort(key=lambda c: -c[0])
        if " ".join(" ".join(t.split()) for _, t, _ in candidatos) != alvo:
            return []
        return [r for _, _, r in candidatos]

    print("\n=== POSICAO DE CADA TEXTO ===")
    caixas = []
    for texto, dados in esperado.items():
        ax, ay, hali, vali, altura, angulo = dados[:6]
        largura_quadro = dados[6] if len(dados) > 6 else 0.0
        nome = texto.replace("\n", " / ")[:34]
        if len(dados) > 6:
            # MTEXT: cada linha e um rotulo, apoiado na sua linha de base
            tam = altura / CAP
            tol = 0.06 * tam + 0.05
            linhas = linhas_do_mtext(texto, ax, hali, tol)
            if not linhas:
                checar("'%s' desenhado" % nome, False, "-> nao apareceu no mapa")
                continue
            n = len(linhas)
            primeira = {"Top": ay - altura,
                        "Bottom": ay + BAIXO_CAD * altura + (n - 1) * PASSO_CAD * altura,
                        "Half": ay + (altura + (n - 1) * PASSO_CAD * altura
                                      + BAIXO_CAD * altura) / 2 - altura}[vali]
            desvios = [abs(r.yMinimum() + DESC * tam - (primeira - k * PASSO_CAD * altura))
                       for k, r in enumerate(linhas)]
            checar("'%s' em %d linha(s), cada uma na base do AutoCAD (%s)" % (nome, n, vali),
                   max(desvios) < tol, "-> desvio maximo %.2f (tolerancia %.2f)"
                   % (max(desvios), tol))
            for k, r in enumerate(linhas):
                caixas.append(("%s #%d" % (nome, k + 1),
                               QgsRectangle(r.xMinimum(), r.yMinimum() + 0.5 * DESC * tam,
                                            r.xMaximum(), r.yMaximum() - (ASC * tam - altura))))
            if largura_quadro:
                checar("'%s' cabe no quadro de %.0f" % (nome, largura_quadro),
                       n > 1 and max(r.width() for r in linhas) <= largura_quadro * 1.02,
                       "-> largura %.1f em %d linhas" % (max(r.width() for r in linhas), n))
            continue
        achados = rotulos.get(texto)
        if not achados:
            checar("'%s' desenhado" % nome, False, "-> nao apareceu no mapa")
            continue
        r = achados[0].labelRect
        tam_ = altura / CAP
        from qgis.core import QgsRectangle as _R
        if angulo:
            caixas.append((nome, r))
        else:
            caixas.append((nome, _R(r.xMinimum(), r.yMinimum() + 0.5 * DESC * tam_,
                                    r.xMaximum(), r.yMaximum() - (ASC * tam_ - altura))))
        tam = altura / CAP
        tol = 0.06 * tam + 0.05

        if angulo:
            checar("'%s' girado %g graus" % (nome, angulo),
                   r.height() > r.width() and abs(r.yMinimum() - ay) < tol,
                   "-> %.1f x %.1f, comeca em y=%.2f (ancora %.2f)"
                   % (r.width(), r.height(), r.yMinimum(), ay))
            continue

        h_ok = {"Left": abs(r.xMinimum() - ax), "Right": abs(r.xMaximum() - ax),
                "Center": abs(r.center().x() - ax)}[hali]
        checar("'%s' alinhado %s" % (nome, hali), h_ok < tol,
               "-> desvio %.2f (tolerancia %.2f)" % (h_ok, tol))

        # A conferencia e pela regra do AUTOCAD, nao pela do QGIS: onde fica
        # a linha de base das letras, que sai da caixa desenhada (baixo + DESC).
        base = r.yMinimum() + DESC * tam
        if vali == "Top":                      # topo da maiuscula na ancora
            v_ok = abs(base - (ay - altura))
        elif vali == "Bottom":                 # "embaixo" do AutoCAD na ancora
            v_ok = abs(base - (ay + BAIXO_CAD * altura))
        elif vali == "Half":                   # meio da maiuscula
            v_ok = abs(base + altura / 2.0 - ay)
        else:                                  # linha de base na ancora
            v_ok = abs(base - ay)
        checar("'%s' na altura do AutoCAD (%s)" % (nome, vali), v_ok < tol,
               "-> desvio %.2f (tolerancia %.2f)" % (v_ok, tol))

        # tamanho: a altura da caixa tem de corresponder a altura do CAD
        esperada = ALTURA_LINHA * tam
        checar("'%s' no tamanho do desenho" % nome,
               abs(r.height() - esperada) < 0.08 * esperada,
               "-> caixa %.2f, esperado %.2f (maiuscula %.2f)"
               % (r.height(), esperada, altura))

    # nenhum texto pode ficar em cima de outro
    print("\n=== SOBREPOSICAO ===")
    colisoes = []
    for i in range(len(caixas)):
        for j in range(i + 1, len(caixas)):
            a, b = caixas[i][1], caixas[j][1]
            inter = a.intersect(b)
            if not inter.isEmpty() and inter.width() * inter.height() > 0.05 * min(
                    a.width() * a.height(), b.width() * b.height()):
                colisoes.append((caixas[i][0], caixas[j][0]))
    checar("nenhum texto sobre outro", not colisoes, "-> %s" % colisoes)

    geo = [c for n, c in caixas if n == "Geo"]
    sana = [c for n, c in caixas if n == "sana"]
    if geo and sana:
        folga = sana[0].xMinimum() - geo[0].xMaximum()
        checar("'Geo' e 'sana' lado a lado", -0.5 < folga < 1.5, "-> folga %.2f" % folga)

    print("\n%d passaram, %d falharam" % (ok, fail))
    app.exitQgis()
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
