# -*- coding: utf-8 -*-
"""
Abre o .qgs gerado dentro do QGIS de verdade e confere o que ele entendeu.

Os outros testes validam a ESTRUTURA do XML. Este valida o RESULTADO: se o
QGIS aceitou as camadas, se aplicou as cores do AutoCAD e se ligou os rotulos.
No fim renderiza o mapa para PNG, que e a unica prova visual de que o desenho
chegou inteiro.

Precisa do QGIS instalado e roda com o Python DELE, nao com o do projeto:

    "C:\\Program Files\\QGIS 3.44.12\\bin\\python-qgis-ltr.bat" testes\\verificar_no_qgis.py <projeto.qgs> <saida.png>
"""

import os
import sys

from qgis.core import (QgsApplication, QgsMapSettings, QgsProject,
                       QgsRectangle, QgsMapRendererParallelJob)
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor

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
    caminho_qgs = sys.argv[1]
    saida_png = sys.argv[2] if len(sys.argv) > 2 else None
    esperado = {}
    for par in sys.argv[3:]:                   # camada=#rrggbb
        nome, _, cor = par.partition("=")
        esperado[nome] = cor.lower()

    QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", ""), True)
    app = QgsApplication([], False)
    app.initQgis()

    print("QGIS %s" % QgsApplication.applicationVersion())
    print("\n=== ABRINDO O PROJETO ===")
    projeto = QgsProject.instance()
    lido = projeto.read(caminho_qgs)
    checar("o QGIS aceitou o projeto", lido)

    camadas = list(projeto.mapLayers().values())
    checar("carregou camadas", len(camadas) > 0, "-> %d" % len(camadas))
    checar("CRS do projeto", projeto.crs().authid() == "EPSG:31982",
           "-> %s" % projeto.crs().authid())

    print("\n=== CAMADAS ===")
    for camada in sorted(camadas, key=lambda c: c.name()):
        valida = camada.isValid()
        n = camada.featureCount() if valida else -1
        checar("'%s' valida" % camada.name(), valida, "(%d feicoes)" % n)
        if not valida:
            print("        motivo:", camada.dataProvider().error().summary())
            continue

        # ---- cores herdadas do AutoCAD
        renderizador = camada.renderer()
        tipo_rend = renderizador.type() if renderizador else "(nenhum)"
        cores = []
        if tipo_rend == "categorizedSymbol":
            for cat in renderizador.categories():
                cores.append((str(cat.value()), cat.symbol().color().name().lower()))
        elif hasattr(renderizador, "symbol") and renderizador.symbol() is not None:
            cores.append(("(unica)", renderizador.symbol().color().name().lower()))

        if tipo_rend == "categorizedSymbol":
            # a cor pintada tem de ser a mesma que esta gravada na feicao
            erradas = [(v, c) for v, c in cores if v.lower() != c]
            checar("  '%s' pinta cada categoria com a sua cor" % camada.name(),
                   not erradas, "(%d categorias)" % len(cores) if not erradas
                   else "-> divergentes: %s" % erradas[:3])
        elif cores:
            alvo = esperado.get(camada.name())
            if alvo:
                checar("  cor de '%s'" % camada.name(), cores[0][1] == alvo,
                       "-> %s (esperado %s)" % (cores[0][1], alvo))
            else:
                print("         %s: %s" % (tipo_rend, cores[0][1]))

        # as cores desenhadas batem com as gravadas no arquivo de dados?
        campos = [f.name() for f in camada.fields()]
        if "cor_cad" in campos and tipo_rend in ("categorizedSymbol", "singleSymbol"):
            gravadas = {f["cor_cad"] for f in camada.getFeatures() if f["cor_cad"]}
            pintadas = {c for _, c in cores}
            if tipo_rend == "categorizedSymbol":
                checar("  '%s' cobre todas as cores do desenho" % camada.name(),
                       gravadas <= {v.lower() for v, _ in cores},
                       "-> %d no dado, %d categorias" % (len(gravadas), len(cores)))
            elif len(gravadas) == 1:
                checar("  '%s' cor unica confere" % camada.name(),
                       gravadas == pintadas, "-> %s" % (gravadas | pintadas))

        # ---- rotulos
        if camada.labelsEnabled():
            cfg = camada.labeling().settings()
            print("         rotulos LIGADOS  campo=%s  tamanho=%s"
                  % (cfg.fieldName, cfg.format().size()))
            checar("  rotulo de '%s' usa o campo Text" % camada.name(),
                   cfg.fieldName == "Text")
            # a cor do rotulo tem de vir do campo, senao um titulo vermelho
            # sairia preto junto com o resto
            try:
                from qgis.core import QgsPalLayerSettings
                prop = cfg.dataDefinedProperties().property(QgsPalLayerSettings.Color)
                checar("  cor do rotulo de '%s' vem do campo" % camada.name(),
                       prop.isActive() and prop.field() == "cor_cad",
                       "-> ativo=%s campo=%s" % (prop.isActive(), prop.field()))
            except Exception as erro:
                checar("  cor do rotulo por campo", False, "-> %s" % erro)

    # ---- desenha o mapa
    if saida_png and camadas:
        print("\n=== RENDERIZANDO ===")
        # Usa o enquadramento gravado no projeto, que e o que o usuario ve ao
        # abrir. So calcula um se o projeto nao trouxer.
        extensao = None
        try:
            guardada = projeto.viewSettings().defaultViewExtent()
            if guardada is not None and not guardada.isNull():
                extensao = QgsRectangle(guardada)
                print("  usando o enquadramento gravado no projeto")
        except Exception:
            pass
        if extensao is None:
            extensao = QgsRectangle()
            extensao.setNull()
            for camada in camadas:
                if camada.isValid():
                    extensao.combineExtentWith(camada.extent())
            extensao.scale(1.05)
            print("  projeto nao trouxe enquadramento; calculado a partir das camadas")

        cfg = QgsMapSettings()
        cfg.setLayers(camadas)
        cfg.setBackgroundColor(QColor(255, 255, 255))
        cfg.setOutputSize(QSize(1600, 1100))
        cfg.setExtent(extensao)
        cfg.setDestinationCrs(projeto.crs())
        try:
            cfg.setFlag(QgsMapSettings.DrawLabeling, True)
        except Exception:
            pass

        tarefa = QgsMapRendererParallelJob(cfg)
        tarefa.start()
        tarefa.waitForFinished()
        imagem = tarefa.renderedImage()
        imagem.save(saida_png)
        checar("mapa renderizado", os.path.exists(saida_png),
               "-> %s (%.0f KB)" % (saida_png, os.path.getsize(saida_png) / 1024.0))

    print("\n%d passaram, %d falharam" % (ok, fail))
    app.exitQgis()
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
