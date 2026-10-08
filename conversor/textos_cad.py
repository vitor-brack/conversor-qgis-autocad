# -*- coding: utf-8 -*-
"""
Como reproduzir no QGIS um texto do AutoCAD no lugar e no tamanho certos.

O QGIS trata texto como rotulo de mapa: por padrao ele escolhe onde colocar.
Texto de CAD nao funciona assim -- cada um tem um ponto de ancoragem exato, um
alinhamento (esquerda, centro, direita x base, meio, topo), uma altura, uma
rotacao e as vezes uma largura comprimida. Um carimbo ou uma tabela so fica
legivel se tudo isso for respeitado; ignorar o alinhamento foi o que empilhou
palavras e desalinhou a tabela no mapa real.

O projeto do QGIS resolve isso com propriedades definidas por campo (posicao,
alinhamento, tamanho, rotacao), que e tambem como o importador de DWG do
proprio QGIS faz. Este modulo calcula os valores desses campos.

As constantes da fonte foram MEDIDAS no QGIS com QFontMetricsF, nao lembradas.
"""

# Altura da maiuscula dividida pelo tamanho da fonte, na Arial. O AutoCAD mede
# a altura do texto pela maiuscula; o QGIS mede o tamanho pela caixa da fonte.
# Sem essa conversao todo texto sai cerca de 30% menor que no desenho.
CAP_ARIAL = 0.7167

# Altura da caixa de uma linha de rotulo na Arial, em tamanhos de fonte
# (medido: 1,105 no QGIS 3.44, 1,12 no 4.2). So serve para estimar o espaco
# que um texto ocupa; o QGIS nunca monta texto de varias linhas (ver
# linhas_de_base).
LINHA_ARIAL = 1.11

# Caixa que o QGIS desenha em volta de uma linha de texto, acima e abaixo da
# linha de base, em tamanhos de fonte (medido: 0,90/0,22 no 3.44, 0,91/0,21 no 4.2).
ASCENDENTE_QGIS = 0.905
DESCENDENTE_QGIS = 0.215

# Quanto o "embaixo" do AutoCAD fica abaixo da linha de base, em alturas de
# texto. Medido no renderizador do ezdxf, que reproduz o AutoCAD.
DESCIDA_CAD = 0.2778

# Espacamento padrao entre linhas de um MTEXT, em alturas de texto (5/3).
LINHA_CAD = 5.0 / 3.0

# Avanco de cada caractere da Arial, em milesimos do tamanho da fonte.
_LARGURAS = {
    ' ': 278, '!': 278, '"': 355, '#': 556, '$': 556, '%': 889, '&': 667, "'": 191,
    '(': 333, ')': 333, '*': 389, '+': 584, ',': 278, '-': 333, '.': 278, '/': 278,
    '0': 556, '1': 556, '2': 556, '3': 556, '4': 556, '5': 556, '6': 556, '7': 556,
    '8': 556, '9': 556, ':': 278, ';': 278, '<': 584, '=': 584, '>': 584, '?': 556,
    '@': 1015, 'A': 667, 'B': 667, 'C': 722, 'D': 722, 'E': 667, 'F': 611, 'G': 778,
    'H': 722, 'I': 278, 'J': 500, 'K': 667, 'L': 556, 'M': 833, 'N': 722, 'O': 778,
    'P': 667, 'Q': 778, 'R': 722, 'S': 667, 'T': 611, 'U': 722, 'V': 667, 'W': 944,
    'X': 667, 'Y': 667, 'Z': 611, '[': 278, '\\': 278, ']': 278, '^': 469, '_': 556,
    '`': 333, 'a': 556, 'b': 556, 'c': 500, 'd': 556, 'e': 556, 'f': 278, 'g': 556,
    'h': 556, 'i': 222, 'j': 222, 'k': 500, 'l': 222, 'm': 833, 'n': 556, 'o': 556,
    'p': 556, 'q': 556, 'r': 333, 's': 500, 't': 278, 'u': 556, 'v': 500, 'w': 722,
    'x': 500, 'y': 500, 'z': 500, '{': 334, '|': 260, '}': 334, '~': 584,
    'ª': 370, '°': 400, '±': 549, '²': 333, '³': 333,
    'º': 365, 'À': 667, 'Á': 667, 'Â': 667, 'Ã': 667,
    'Ç': 722, 'É': 667, 'Ê': 667, 'Í': 278, 'Ó': 778,
    'Ô': 778, 'Õ': 778, 'Ø': 778, 'Ú': 722, 'Ü': 722,
    'à': 556, 'á': 556, 'â': 556, 'ã': 556, 'ç': 500,
    'é': 556, 'ê': 556, 'í': 278, 'ó': 556, 'ô': 556,
    'õ': 556, 'ú': 556, 'ü': 556, '⌀': 843,
}
_LARGURA_PADRAO = 556


def tamanho_qgis(altura_cad):
    """Tamanho da fonte no QGIS (unidades de mapa) para a altura do AutoCAD."""
    return float(altura_cad) / CAP_ARIAL


def linhas_de_base(vertical, n, altura_cad, espacamento=1.0):
    """Onde fica a linha de base de cada linha de um MTEXT, em relacao a
    ancora (positivo = acima), pela regra do AutoCAD.

    O MTEXT se ancora pela caixa do texto, que vai do topo da maiuscula da
    primeira linha ate DESCIDA_CAD abaixo da base da ultima; as linhas se
    sucedem a LINHA_CAD alturas, vezes o fator de espacamento do proprio
    MTEXT. Com uma linha so, da o mesmo que correcao_vertical.

    Cada linha vira um rotulo proprio, apoiado nessa base. Deixar o QGIS
    montar as linhas nao funciona: a altura de linha que vem de campo e
    ignorada (3.44 e 4.2, em qualquer unidade), entao o espacamento saia 5%
    mais apertado que no AutoCAD e ainda mudava com a fonte.
    """
    h = float(altura_cad or 0.0)
    passo = LINHA_CAD * h * (espacamento if espacamento and espacamento > 0 else 1.0)
    if vertical == "Top":
        primeira = -h
    elif vertical == "Bottom":
        primeira = DESCIDA_CAD * h + (n - 1) * passo
    elif vertical == "Half":
        primeira = (h + (n - 1) * passo + DESCIDA_CAD * h) / 2.0 - h
    else:
        primeira = 0.0
    return [primeira - k * passo for k in range(n)]


# Posicao de ancoragem da style string do OGR -> alinhamento do QGIS.
#     7 8 9     topo
#     4 5 6     meio
#     1 2 3     linha de base
#    10 11 12   base da caixa
_HORIZONTAL = {1: "Left", 4: "Left", 7: "Left", 10: "Left",
               2: "Center", 5: "Center", 8: "Center", 11: "Center",
               3: "Right", 6: "Right", 9: "Right", 12: "Right"}


def alinhamento(ancora, eh_mtext=False):
    """(horizontal, vertical) no vocabulario do QGIS.

    Para MTEXT, o GDAL traduz a ancoragem "embaixo" como 1/2/3 (linha de base),
    mas o MTEXT se alinha pela base da CAIXA de texto -- que no QGIS e Bottom.
    """
    try:
        ancora = int(ancora)
    except (TypeError, ValueError):
        ancora = 1
    horizontal = _HORIZONTAL.get(ancora, "Left")
    if ancora in (4, 5, 6):
        vertical = "Half"
    elif ancora in (7, 8, 9):
        vertical = "Top"
    elif ancora in (10, 11, 12):
        vertical = "Bottom"
    else:
        vertical = "Bottom" if eh_mtext else "Base"
    return horizontal, vertical


def correcao_vertical(vertical, eh_mtext, altura_cad):
    """Quanto subir o ponto (em unidades do desenho) para o QGIS pintar o
    texto na altura em que o AutoCAD pinta.

    Os dois concordam na linha de base, mas nao no que e "topo", "meio" e
    "embaixo". O AutoCAD mede pelo topo da MAIUSCULA; o QGIS, pela caixa da
    fonte, que sobra acima dela. Um texto ancorado pelo topo -- o padrao de
    todo MTEXT -- ficava 0,26 da altura mais baixo que no desenho.

    As contas saem das medidas da fonte, nao de ajuste no olho:
      AutoCAD, linha de base em relacao a ancora
        Topo: -H    Meio (TEXT): -H/2    Meio (MTEXT): -(H - 0,278H)/2
        Embaixo: +0,278H     Base: 0
      QGIS, com a caixa [-DESC, +ASC] em volta da linha de base
        Top: -ASC   Half: -(ASC - DESC)/2   Bottom: +DESC   Base: 0
    A correcao e a diferenca. Nao depende do numero de linhas.
    """
    h = float(altura_cad or 0.0)
    s = tamanho_qgis(h)
    asc, desc = ASCENDENTE_QGIS * s, DESCENDENTE_QGIS * s
    if vertical == "Top":
        return asc - h
    if vertical == "Bottom":
        return DESCIDA_CAD * h - desc
    if vertical == "Half":
        caixa_cad = h - DESCIDA_CAD * h if eh_mtext else h
        return ((asc - desc) - caixa_cad) / 2.0
    return 0.0


def usa_deslocamento(ancora):
    """Se o ponto de ancoragem real e o ponto + (dx, dy) da style string.

    Texto alinhado a esquerda na linha de base (ancoragem 1) nao usa o segundo
    ponto de alinhamento, e o AutoCAD o grava como (0, 0). O GDAL devolve mesmo
    assim o deslocamento ate la -- aplica-lo manda o texto para a origem do
    desenho, a quilometros de distancia. A ancoragem 1 tambem e o que o GDAL
    usa para texto "alinhado" e "ajustado", que comecam no PRIMEIRO ponto.
    """
    try:
        return int(ancora) != 1
    except (TypeError, ValueError):
        return False


def largura_texto(texto, altura_cad, esticamento=100):
    """Largura aproximada, em unidades de mapa, de uma linha desenhada na Arial."""
    milesimos = sum(_LARGURAS.get(ch, _LARGURA_PADRAO) for ch in texto)
    return milesimos / 1000.0 * tamanho_qgis(altura_cad) * (esticamento / 100.0)


# ---------------------------------------------------------------------------
# Fontes de traco do AutoCAD (.shx)
# ---------------------------------------------------------------------------
#
# A simplex.shx e a romans.shx sao a "Roman Simplex" das fontes Hershey
# (1967, dominio publico), com o mesmo avanco de cada letra. A tabela da o
# avanco em unidades da fonte, em que a maiuscula tem 21. So o espaco e do
# AutoCAD: 21 (no romans.shp, "*32,9,spc 2,8,(21,0)..."); a Hershey usa 16.
# Conferido no LOTEAMENTO: o AutoCAD grava onde comeca cada texto alinhado
# pelo centro ou pela direita, e "RS " deu 62 unidades (21 + 20 + 21) e o
# nome do proprietario, de 12 caracteres, 233 (a tabela da 232). O espaco
# largo e o que deixa lugar para os atributos que entram no meio de um texto
# ("MERIDIANO CENTRAL    %%d WGr", com o 45 nos quatro espacos).
_UNIDADES_SHX = 21.0
_HERSHEY_SIMPLEX = dict(zip(
    " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`"
    "abcdefghijklmnopqrstuvwxyz{|}~",
    (21, 10, 16, 21, 20, 24, 26, 10, 14, 14, 16, 26, 10, 26, 10, 22,
     20, 20, 20, 20, 20, 20, 20, 20, 20, 20, 10, 10, 24, 26, 24, 18, 27,
     18, 21, 21, 21, 19, 18, 21, 22, 8, 16, 21, 17, 24, 22, 22, 21, 22, 21, 20,
     16, 22, 18, 24, 20, 18, 20, 14, 14, 14, 16, 16, 10,
     19, 19, 18, 19, 18, 12, 19, 19, 8, 10, 17, 8, 30, 19, 19, 19, 19, 13, 17,
     12, 19, 16, 22, 17, 16, 17, 14, 8, 14, 24)))
_HERSHEY_SIMPLEX.update({"°": 14, "±": 26, "⌀": 22, "Ø": 22, "ø": 19})
_HERSHEY_PADRAO = 20
_FONTES_DE_TRACO = {"simplex": _HERSHEY_SIMPLEX, "simplex8": _HERSHEY_SIMPLEX,
                    "romans": _HERSHEY_SIMPLEX}


def fonte_de_traco(arquivo):
    """O nome de uma fonte de traco de larguras conhecidas, pelo arquivo do
    estilo de texto ("simplex", "ROMANS.shx", e tambem as copias TrueType que
    o AutoCAD instala, "romans__.ttf"), ou None."""
    import os
    nome = os.path.splitext(os.path.basename(str(arquivo or "")))[0].lower().rstrip("_")
    return nome if nome in _FONTES_DE_TRACO else None


def largura_shx(texto, altura_cad, fonte):
    """Largura, em unidades do desenho, de um texto numa fonte de traco (ver
    fonte_de_traco), com fator de largura 1: o avanco de cada letra, somado."""
    import unicodedata
    tabela = _FONTES_DE_TRACO[fonte]
    unidades = 0
    for ch in texto:
        avanco = tabela.get(ch)
        if avanco is None:       # letra acentuada: o avanco e o da letra base
            base = unicodedata.normalize("NFD", ch)[:1]
            avanco = tabela.get(base, _HERSHEY_PADRAO)
        unidades += avanco
    return unidades * float(altura_cad) / _UNIDADES_SHX


def quebrar(texto, largura_max, altura_cad, esticamento=100):
    """Quebra as linhas de um MTEXT na largura do quadro, como o AutoCAD faz.

    O GDAL devolve um MTEXT de largura fixa como uma linha so; no AutoCAD ele
    aparece em varias. As quebras sao calculadas com as larguras da Arial,
    que e a fonte que o QGIS vai usar -- assim nenhuma linha passa do quadro.
    Uma palavra maior que o quadro fica sozinha na linha, como no AutoCAD.
    """
    if not texto or not largura_max or largura_max <= 0:
        return texto
    saida = []
    for paragrafo in str(texto).split("\n"):
        palavras = paragrafo.split(" ")
        atual = ""
        for palavra in palavras:
            tentativa = palavra if not atual else atual + " " + palavra
            if atual and largura_texto(tentativa, altura_cad, esticamento) > largura_max:
                saida.append(atual)
                atual = palavra
            else:
                atual = tentativa
        saida.append(atual)
    return "\n".join(saida)


# ---------------------------------------------------------------------------
# Texto formatado (MTEXT com cor, fonte ou negrito no meio do texto)
# ---------------------------------------------------------------------------
#
# Um MTEXT pode trocar de cor, de fonte e de estilo no meio do texto -- o logo
# "Geosana" tem "Geo" em azul e "sana" em verde. O GDAL descarta essa
# formatacao; o QGIS so a mostra se o rotulo for em HTML. As funcoes abaixo
# recebem o texto ja separado em trechos (quem separa e cad_ezdxf.py) e montam
# as duas versoes: o texto puro, para a tabela de atributos, e o HTML, para o
# rotulo. As quebras de linha saem iguais nas duas.
#
# Um trecho e uma tupla:
#     ("palavra", texto, estilo)   ("espaco", estilo)   ("quebra",)
# e o estilo e um dict com as chaves opcionais
#     cor ("#rrggbb"), fonte, negrito, italico, sublinhado, riscado,
#     escala (altura relativa), largura (fator de largura do codigo barra-W)

import html as _html

_ESTILO_VAZIO = {}

# Separa as linhas no HTML que montar_texto devolve; quem o recebe separa as
# linhas de novo, e cada uma vira um rotulo (ver linhas_de_base). As linhas
# nunca chegam juntas ao QGIS -- e por isso nao se usa <br>: o QGIS so quebra
# no <br> que fica dentro de um trecho formatado; entre dois trechos
# (<span>..</span><br><span>..</span>) ele o descarta e cola a ultima palavra
# de uma linha na primeira da seguinte, como aconteceu no carimbo do mapa real.
QUEBRA_HTML = "¶"


def _css(estilo):
    partes = []
    if estilo.get("cor"):
        partes.append("color:%s" % estilo["cor"])
    if estilo.get("fonte"):
        partes.append("font-family:'%s'" % estilo["fonte"].replace("'", ""))
    if estilo.get("negrito"):
        partes.append("font-weight:bold")
    if estilo.get("italico"):
        partes.append("font-style:italic")
    decoracao = [n for n, chave in (("underline", "sublinhado"), ("line-through", "riscado"))
                 if estilo.get(chave)]
    if decoracao:
        partes.append("text-decoration:%s" % " ".join(decoracao))
    return ";".join(partes)


def montar_texto(trechos, altura_cad, largura_max=0.0, esticamento=100, medir=None):
    """Devolve (texto_puro, html, tem_formatacao).

    Com `largura_max` > 0 quebra as linhas na largura do quadro, como o
    AutoCAD faz com o MTEXT, medindo cada palavra na altura, na largura e na
    fonte do seu trecho. `medir(texto, altura, estilo, esticamento)` mede na
    fonte de verdade (ver cad_ezdxf.medir); quando devolve None, ou nao e
    dado, a medida e a da Arial. No texto puro as linhas sao separadas por
    quebra de linha; no HTML, por QUEBRA_HTML, e cada linha fecha os seus
    proprios trechos.
    """
    linhas = []          # cada linha e uma lista de (texto, estilo)
    atual = []
    largura_atual = 0.0
    espaco_pendente = None
    tem_formatacao = False

    def largura(texto, estilo):
        altura = altura_cad * float(estilo.get("escala") or 1.0)
        estica = 100.0 * float(estilo["largura"]) if estilo.get("largura") else esticamento
        w = medir(texto, altura, estilo, estica) if medir else None
        return w if w is not None else largura_texto(texto, altura, estica)

    for trecho in trechos:
        tipo = trecho[0]
        if tipo == "quebra":
            linhas.append(atual)
            atual, largura_atual, espaco_pendente = [], 0.0, None
            continue
        if tipo == "espaco":
            if atual:
                espaco_pendente = trecho[1]
            continue
        texto, estilo = trecho[1], trecho[2] or _ESTILO_VAZIO
        if _css(estilo):
            tem_formatacao = True
        w = largura(texto, estilo)
        w_espaco = largura(" ", espaco_pendente) if espaco_pendente is not None else 0.0
        if (largura_max and largura_max > 0 and atual
                and largura_atual + w_espaco + w > largura_max):
            linhas.append(atual)
            atual, largura_atual, espaco_pendente, w_espaco = [], 0.0, None, 0.0
        if espaco_pendente is not None:
            atual.append((" ", espaco_pendente))
            largura_atual += w_espaco
            espaco_pendente = None
        atual.append((texto, estilo))
        largura_atual += w
    linhas.append(atual)

    puro = "\n".join("".join(t for t, _ in linha) for linha in linhas)
    partes_html = []
    for linha in linhas:
        # junta os pedacos vizinhos de mesmo estilo num span so
        grupos = []
        for texto, estilo in linha:
            css = _css(estilo)
            if grupos and grupos[-1][1] == css:
                grupos[-1][0].append(texto)
            else:
                grupos.append(([texto], css))
        pedacos = []
        for textos, css in grupos:
            conteudo = _html.escape("".join(textos), quote=False).replace("  ", " &nbsp;")
            pedacos.append('<span style="%s">%s</span>' % (css, conteudo) if css else conteudo)
        partes_html.append("".join(pedacos))
    return puro, QUEBRA_HTML.join(partes_html), tem_formatacao


def html_simples(texto):
    """Versao HTML de um texto sem formatacao."""
    return _html.escape(str(texto or ""), quote=False).replace("\n", QUEBRA_HTML)
