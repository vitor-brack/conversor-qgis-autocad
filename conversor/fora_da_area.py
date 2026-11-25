# -*- coding: utf-8 -*-
"""
Feicao perdida longe do desenho.

Num mapa real havia 9 polilinhas de dois vertices, os dois em (0, 0), dentro de
camadas de curva de nivel, num terreno a 448 km da origem. Entregues assim, elas
caem no meio do oceano; na previa, o "ver tudo" mostrava o terreno do tamanho de
um ponto.

A regra e geometrica e e a mesma na previa e na conversao: a area principal e a
caixa que contem de 5% a 95% dos vertices, com uma folga grande em volta (o que
tolera ate 5% de lixo, mesmo num desenho pequeno); so e
considerada fora a feicao com TODOS os vertices fora dela. Quem tem ao menos um
vertice dentro fica, para nao cortar dado bom.

Sem dependencia de interface nem do restante do conversor.
"""
import numpy as np

# Abaixo disto nao da para dizer o que e normal num desenho.
MINIMO_DE_VERTICES = 20
# Folga em volta da area principal, em larguras dela. Folga grande de proposito:
# um desenho com partes legitimamente afastadas nao perde nada, e o lixo de
# verdade (a centenas de larguras de distancia) continua de fora.
MARGEM = 5.0
# A area principal vai do percentil 5 ao 95 dos vertices: ate 5% de lixo de cada
# lado nao a puxa para longe do desenho.
PERCENTIS = (5, 95)


def caixa_principal(xy):
    """(xmin, ymin, xmax, ymax) da area principal, ou None se nao der para dizer.

    `xy` e uma sequencia Nx2 de vertices. Vertice que nao e numero finito nao
    entra na conta.
    """
    xy = np.asarray(xy, dtype=float)
    if xy.ndim != 2 or xy.shape[1] < 2:
        return None
    xy = xy[np.isfinite(xy[:, :2]).all(axis=1)]
    if len(xy) < MINIMO_DE_VERTICES:
        return None
    x0, x1 = np.percentile(xy[:, 0], PERCENTIS)
    y0, y1 = np.percentile(xy[:, 1], PERCENTIS)
    folga = MARGEM * max(x1 - x0, y1 - y0)
    if folga <= 0:
        return None
    return (float(x0 - folga), float(y0 - folga), float(x1 + folga), float(y1 + folga))


def _vertices(coords):
    """Os vertices de uma geometria GeoJSON, em qualquer aninhamento."""
    if not coords:
        return
    if isinstance(coords[0], (int, float)):
        yield coords
        return
    for parte in coords:
        yield from _vertices(parte)


def vertices_fora(xy, caixa):
    """Vetor de booleanos: True onde o vertice esta fora da caixa (ou nao e numero)."""
    xy = np.asarray(xy, dtype=float)
    xmin, ymin, xmax, ymax = caixa
    # comparacao com NaN e sempre falsa, entao o que nao e numero cai em "fora"
    dentro = ((xy[:, 0] >= xmin) & (xy[:, 0] <= xmax)
              & (xy[:, 1] >= ymin) & (xy[:, 1] <= ymax))
    return ~dentro


def todos_fora(coords, caixa):
    """True se TODOS os vertices da geometria estao fora da caixa."""
    if caixa is None:
        return False
    xy = [(v[0], v[1]) for v in _vertices(coords)]
    return bool(xy) and bool(vertices_fora(xy, caixa).all())
