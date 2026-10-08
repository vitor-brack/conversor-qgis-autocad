# -*- coding: utf-8 -*-
"""
Detalhes de baixo nivel do formato DXF.

Tres problemas reais do DXF gerado pelo GDAL que este modulo resolve:

1. ACENTOS. O GDAL grava o arquivo em UTF-8 mas declara no cabecalho
   $DWGCODEPAGE = ANSI_1252. O AutoCAD respeita o codepage declarado e o
   GDAL/QGIS ignora ele, entao os dois leem os mesmos bytes de formas
   diferentes e "Secao" vira lixo em um dos lados. Nao existe codificacao que
   agrade aos dois, entao o padrao aqui e transliterar para ASCII, que os dois
   leem igual. Ver `texto_seguro`.

2. TEXTO. O driver DXF do GDAL simplesmente descarta o campo `Text` na escrita
   -- o texto nem chega ao arquivo. Para rotular pontos (ex.: "AM-01") e
   preciso escrever as entidades TEXT na mao. Ver `injetar_textos`.

3. CRS. O DXF nao tem onde guardar o sistema de coordenadas, e o driver do GDAL
   nao le um .prj ao lado. Gravamos um .prj (que o QGIS reconhece) e um
   .crs.txt legivel por humanos. Ver `gravar_crs_acompanhante`.
"""

import json
import os
import re
import unicodedata

# Caracteres proibidos em nome de camada do AutoCAD.
_PROIBIDOS = re.compile(r'[<>/\\":;?*|=`,\x00-\x1f]')


def sem_acento(texto):
    """'Secao Geologica' a partir de 'Secao Geologica' com acentos."""
    decomposto = unicodedata.normalize("NFKD", texto)
    limpo = "".join(c for c in decomposto if not unicodedata.combining(c))
    # simbolos que a decomposicao NFKD nao resolve
    for de, para in (("Ø", "O"), ("ø", "o"), ("Æ", "AE"),
                     ("æ", "ae"), ("Đ", "D"), ("đ", "d"),
                     ("’", "'"), ("‘", "'"), ("“", '"'),
                     ("”", '"'), ("–", "-"), ("—", "-"),
                     ("º", "o"), ("ª", "a")):
        limpo = limpo.replace(de, para)
    return limpo


# Simbolos que o AutoCAD escreve como sequencia de escape em ASCII e desenha
# como simbolo. O GDAL faz o caminho de volta na leitura, entao usa-los mantem
# o arquivo em ASCII puro sem perder o simbolo em nenhum dos dois programas.
# So valem dentro de texto: em nome de camada seriam mostrados literalmente.
_ESCAPES_CAD = {"°": "%%d", "±": "%%p", "⌀": "%%c"}


def texto_seguro(texto, somente_ascii=True, escapes_cad=False):
    """Prepara um texto para entrar no DXF.

    Com somente_ascii=True (padrao) transliteramos: o resultado aparece igual no
    AutoCAD 2007 e no QGIS. Com False os acentos sao preservados; quem cuida de
    gravar os bytes certos e `finalizar_codificacao`.

    `escapes_cad` troca grau, mais-ou-menos e diametro pelas sequencias do
    AutoCAD, em vez de perde-los na transliteracao ('45%%d' e nao '45?').
    """
    if texto is None:
        return ""
    texto = str(texto)
    if somente_ascii:
        if escapes_cad:
            for simbolo, escape in _ESCAPES_CAD.items():
                texto = texto.replace(simbolo, escape)
        texto = sem_acento(texto)
        texto = texto.encode("ascii", "replace").decode("ascii")
    return texto


def nome_camada(nome, somente_ascii=True, reserva="0"):
    """Normaliza um valor qualquer para um nome de camada valido do AutoCAD."""
    nome = texto_seguro(nome, somente_ascii).strip()
    nome = _PROIBIDOS.sub("_", nome)
    nome = re.sub(r"\s+", "_", nome)
    nome = re.sub(r"_+", "_", nome)        # 'A / B' nao vira 'A___B'
    nome = nome.strip("_")
    if not nome:
        return reserva
    return nome[:255]          # limite do AutoCAD


# ---------------------------------------------------------------------------
# Entidades TEXT
# ---------------------------------------------------------------------------

def _entidade_text(handle, camada, x, y, z, texto, altura, rotacao=0.0):
    """Monta uma entidade TEXT em DXF R2004 (AC1018).

    Os marcadores de subclasse AcDbEntity/AcDbText sao obrigatorios a partir do
    R2000; sem eles o AutoCAD recusa a entidade. O grupo 7 (estilo de texto) e
    omitido de proposito: o cabecalho do GDAL define o estilo como "Standard"
    e deixar o AutoCAD usar o padrao do desenho evita referencia quebrada.
    """
    return (
        "  0\nTEXT\n"
        "  5\n%X\n"
        "100\nAcDbEntity\n"
        "  8\n%s\n"
        "100\nAcDbText\n"
        " 10\n%.12g\n 20\n%.12g\n 30\n%.12g\n"
        " 40\n%.12g\n"
        "  1\n%s\n"
        " 50\n%.12g\n"
        "100\nAcDbText\n"
    ) % (handle, camada, x, y, z, altura, texto, rotacao)


def injetar_textos(caminho_dxf, itens, altura=2.5, somente_ascii=True,
                   handle_inicial=0xF00000):
    """Acrescenta entidades TEXT a um DXF ja escrito pelo GDAL.

    `itens` e uma lista de dicts: {'x','y','z','texto','camada'}.

    Os handles comecam em 0xF00000, bem acima dos que o GDAL emite, para nao
    colidir com as entidades ja existentes.
    """
    if not itens:
        return 0

    with open(caminho_dxf, "r", encoding="utf-8", errors="replace") as fp:
        corpo = fp.read()

    # Localiza o fim da secao ENTITIES (o ENDSEC que vem depois dela).
    inicio = corpo.find("\nENTITIES\n")
    if inicio == -1:
        return 0
    fim = corpo.find("\n  0\nENDSEC", inicio)
    if fim == -1:
        return 0
    fim += 1                      # mantem a quebra de linha antes do ENDSEC

    blocos = []
    for i, item in enumerate(itens):
        texto = texto_seguro(item.get("texto", ""), somente_ascii, escapes_cad=True)
        if not texto:
            continue
        blocos.append(_entidade_text(
            handle_inicial + i,
            nome_camada(item.get("camada", "TEXTO"), somente_ascii),
            float(item["x"]), float(item["y"]), float(item.get("z") or 0.0),
            texto, altura,
        ))

    if not blocos:
        return 0

    with open(caminho_dxf, "w", encoding="utf-8", errors="replace") as fp:
        fp.write(corpo[:fim] + "".join(blocos) + corpo[fim:])
    return len(blocos)


# ---------------------------------------------------------------------------
# Codificacao final do arquivo
# ---------------------------------------------------------------------------

def finalizar_codificacao(caminho_dxf, somente_ascii=True):
    """Deixa os bytes do arquivo coerentes com o cabecalho $DWGCODEPAGE.

    O GDAL grava o conteudo em UTF-8 mas declara $DWGCODEPAGE = ANSI_1252 no
    cabecalho. Quem le o arquivo -- AutoCAD e o proprio GDAL -- obedece o
    codepage declarado, entao os bytes UTF-8 sao lidos como cp1252 e qualquer
    acento vira lixo. Nas duas opcoes abaixo o que se faz e o mesmo: deixar os
    bytes de acordo com o que o cabecalho promete.

      somente_ascii=True  (padrao) -- transliterar. 'Secao' no lugar de
        'Seção'. Nao depende de codepage nenhum, entao e imune ao problema.

      somente_ascii=False -- gravar em cp1252 de verdade, que e o que o
        cabecalho declara. Preserva os acentos e e lido certo pelo AutoCAD e
        pelo QGIS. E assim que o proprio AutoCAD grava seus DXF.
    """
    with open(caminho_dxf, "r", encoding="utf-8", errors="replace") as fp:
        corpo = fp.read()

    if somente_ascii:
        limpo = sem_acento(corpo).encode("ascii", "replace").decode("ascii")
        if limpo != corpo:
            with open(caminho_dxf, "w", encoding="ascii", errors="replace") as fp:
                fp.write(limpo)
        return

    # Portugues cabe inteiro no cp1252. O que nao couber (grego, cirilico) e
    # transliterado, porque um nome de camada nao aceita sequencia de escape.
    seguro = []
    for ch in corpo:
        try:
            ch.encode("cp1252")
            seguro.append(ch)
        except UnicodeEncodeError:
            seguro.append(sem_acento(ch).encode("ascii", "replace").decode("ascii"))
    with open(caminho_dxf, "wb") as fp:
        fp.write("".join(seguro).encode("cp1252", "replace"))


# ---------------------------------------------------------------------------
# CRS acompanhante
# ---------------------------------------------------------------------------

def gravar_crs_acompanhante(caminho_dxf, epsg, extras=None):
    """Grava o CRS ao lado do DXF, ja que o proprio DXF nao tem onde guardar.

    Sao tres arquivos, cada um para um leitor diferente:
      .prj      -> WKT, formato que o QGIS reconhece
      .crs.txt  -> uma linha legivel, para a pessoa que abrir a pasta
      .conversor.json -> metadados que este programa le na volta
    """
    import pyproj
    base = os.path.splitext(caminho_dxf)[0]
    try:
        crs = pyproj.CRS.from_epsg(int(epsg))
        with open(base + ".prj", "w", encoding="utf-8") as fp:
            fp.write(crs.to_wkt())
        with open(base + ".crs.txt", "w", encoding="utf-8") as fp:
            fp.write("EPSG:%s\n%s\n" % (epsg, crs.name))
    except Exception:
        pass

    meta = {"epsg": int(epsg), "gerado_por": "Conversor QGIS <-> AutoCAD"}
    if extras:
        meta.update(extras)
    try:
        with open(base + ".conversor.json", "w", encoding="utf-8") as fp:
            json.dump(meta, fp, indent=2, ensure_ascii=False)
    except Exception:
        pass


def ler_crs_acompanhante(caminho):
    """Tenta descobrir o EPSG de um DXF/DWG por arquivos ao lado. None se nao achar."""
    base = os.path.splitext(caminho)[0]

    try:
        with open(base + ".conversor.json", "r", encoding="utf-8") as fp:
            epsg = json.load(fp).get("epsg")
        if epsg:
            return int(epsg)
    except Exception:
        pass

    # .prj deixado pelo QGIS ou por uma exportacao anterior
    try:
        import pyproj
        with open(base + ".prj", "r", encoding="utf-8", errors="replace") as fp:
            codigo = pyproj.CRS.from_wkt(fp.read()).to_epsg()
        if codigo:
            return int(codigo)
    except Exception:
        pass

    return None
