# -*- coding: utf-8 -*-
"""
Aparencia do desenho: cor de cada entidade, tamanho dos textos e codificacao.

A cor nao vem da tabela LAYER, e sim da "style string" que o GDAL calcula para
cada entidade. So ela resolve corretamente os quatro casos que aparecem num
desenho de verdade:

    ByLayer          a entidade herda a cor da camada
    cor propria      o desenhista pintou aquela linha de vermelho
    cor verdadeira   RGB de 24 bits (grupo 420), fora da paleta indexada
    dentro de bloco  a peca herda a cor do INSERT, ou tem a sua propria

Ler so a tabela LAYER acerta apenas o primeiro caso. Num mapa geologico, em
que cada cor significa uma litologia, errar os outros tres nao e detalhe
estetico: troca calcario por arenito.

O Fiona nao expoe a style string, mas o GDAL a entrega como coluna se a fonte
for consultada por SQL. Por isso `abrir_entidades` envolve o DXF num VRT --
um arquivo de definicao do proprio GDAL -- que faz
`SELECT *, OGR_STYLE FROM entities`.

A tabela ACI abaixo foi EXTRAIDA do driver DXF do GDAL, nao deduzida: uma
tentativa anterior de gera-la por formula (matiz x brilho x saturacao) errou
223 dos 255 indices. Ela e usada apenas como reserva, quando o VRT falha.
"""

import codecs
import os
import re
import tempfile
from contextlib import contextmanager

import fiona
import fiona.drvsupport

from . import dwg

# O Fiona mantem uma lista branca de drivers e o VRT nao entra nela por padrao.
# O driver existe no GDAL embutido; so precisa ser declarado.
fiona.drvsupport.supported_drivers.setdefault("OGR_VRT", "r")

_ACI_HEX = (
    "ff0000", "ffff00", "00ff00", "00ffff", "0000ff", "ff00ff", "000000", "7f7f7f",
    "bfbfbf", "ff0000", "ff7f7f", "a50000", "a55252", "7f0000", "7f3f3f", "4c0000",
    "4c2626", "260000", "261313", "ff3f00", "ff9f7f", "a52900", "a56752", "7f1f00",
    "7f4f3f", "4c1300", "4c2f26", "260900", "261713", "ff7f00", "ffbf7f", "a55200",
    "a57c52", "7f3f00", "7f5f3f", "4c2600", "4c3926", "261300", "261c13", "ffbf00",
    "ffdf7f", "a57c00", "a59152", "7f5f00", "7f6f3f", "4c3900", "4c4226", "261c00",
    "262113", "ffff00", "ffff7f", "a5a500", "a5a552", "7f7f00", "7f7f3f", "4c4c00",
    "4c4c26", "262600", "262613", "bfff00", "dfff7f", "7ca500", "91a552", "5f7f00",
    "6f7f3f", "394c00", "424c26", "1c2600", "212613", "7fff00", "bfff7f", "52a500",
    "7ca552", "3f7f00", "5f7f3f", "264c00", "394c26", "132600", "1c2613", "3fff00",
    "9fff7f", "29a500", "67a552", "1f7f00", "4f7f3f", "134c00", "2f4c26", "092600",
    "172613", "00ff00", "7fff7f", "00a500", "52a552", "007f00", "3f7f3f", "004c00",
    "264c26", "002600", "132613", "00ff3f", "7fff9f", "00a529", "52a567", "007f1f",
    "3f7f4f", "004c13", "264c2f", "002609", "132617", "00ff7f", "7fffbf", "00a552",
    "52a57c", "007f3f", "3f7f5f", "004c26", "264c39", "002613", "13261c", "00ffbf",
    "7fffdf", "00a57c", "52a591", "007f5f", "3f7f6f", "004c39", "264c42", "00261c",
    "132621", "00ffff", "7fffff", "00a5a5", "52a5a5", "007f7f", "3f7f7f", "004c4c",
    "264c4c", "002626", "132626", "00bfff", "7fdfff", "007ca5", "5291a5", "005f7f",
    "3f6f7f", "00394c", "26424c", "001c26", "132126", "007fff", "7fbfff", "0052a5",
    "527ca5", "003f7f", "3f5f7f", "00264c", "26394c", "001326", "131c26", "003fff",
    "7f9fff", "0029a5", "5267a5", "001f7f", "3f4f7f", "00134c", "262f4c", "000926",
    "131726", "0000ff", "7f7fff", "0000a5", "5252a5", "00007f", "3f3f7f", "00004c",
    "26264c", "000026", "131326", "3f00ff", "9f7fff", "2900a5", "6752a5", "1f007f",
    "4f3f7f", "13004c", "2f264c", "090026", "171326", "7f00ff", "bf7fff", "5200a5",
    "7c52a5", "3f007f", "5f3f7f", "26004c", "39264c", "130026", "1c1326", "bf00ff",
    "df7fff", "7c00a5", "9152a5", "5f007f", "6f3f7f", "39004c", "42264c", "1c0026",
    "211326", "ff00ff", "ff7fff", "a500a5", "a552a5", "7f007f", "7f3f7f", "4c004c",
    "4c264c", "260026", "261326", "ff00bf", "ff7fdf", "a5007c", "a55291", "7f005f",
    "7f3f6f", "4c0039", "4c2642", "26001c", "261321", "ff007f", "ff7fbf", "a50052",
    "a5527c", "7f003f", "7f3f5f", "4c0026", "4c2639", "260013", "26131c", "ff003f",
    "ff7f9f", "a50029", "a55267", "7f001f", "7f3f4f", "4c0013", "4c262f", "260009",
    "261317", "545454", "767676", "989898", "bababa", "dcdcdc", "ffffff",
)

PADRAO = (0, 0, 0)


def aci_para_rgb(indice):
    """Converte um indice de cor do AutoCAD em RGB (reserva; ver o cabecalho)."""
    try:
        indice = abs(int(indice))          # negativo = camada desligada
    except (TypeError, ValueError):
        return PADRAO
    if not (1 <= indice <= 255):
        return PADRAO
    return hex_para_rgb(_ACI_HEX[indice - 1])


def hex_para_rgb(texto):
    texto = str(texto).lstrip("#")[:6]
    try:
        return tuple(int(texto[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return PADRAO


def para_hex(rgb):
    return "#%02x%02x%02x" % tuple(rgb)


# As cores basicas do AutoCAD, pelo nome. O "branco" (cor 7) o programa guarda como
# preto, para fundo claro; as demais aparecem pelo codigo (#rrggbb).
_NOMES_DE_COR = {"#ff0000": "vermelho", "#ffff00": "amarelo", "#00ff00": "verde",
                 "#00ffff": "ciano", "#0000ff": "azul", "#ff00ff": "magenta",
                 "#000000": "branco/preto"}


def nome_da_cor(hex_cor):
    """Como a cor se escreve na lista de camadas e no nome do arquivo."""
    hex_cor = str(hex_cor).lower()
    return _NOMES_DE_COR.get(hex_cor, hex_cor)


# ---------------------------------------------------------------------------
# Style string do OGR
# ---------------------------------------------------------------------------

_COR = re.compile(r"(?<![a-z])c:#([0-9a-fA-F]{6})([0-9a-fA-F]{2})?")
_COR_PREENCHIMENTO = re.compile(r"fc:#([0-9a-fA-F]{6})([0-9a-fA-F]{2})?")
# O tracejado da linha: PEN(...,p:"4.5g 2.25g"), traco, vao, traco, vao... ja multiplicado
# pelo $LTSCALE do desenho. "g" e unidade do desenho; nao ha outra no DXF.
_TRACEJADO = re.compile(r'(?<![a-z])p:"([^"]*)"')
_MEDIDA = re.compile(r"(-?[0-9.]+(?:[eE][+-]?[0-9]+)?)\s*([a-z]*)")


def _tracejado(estilo):
    """(traco, vao, traco, vao...) em unidades do desenho, ou () para linha cheia."""
    if not estilo.lstrip().startswith("PEN("):
        return ()
    achado = _TRACEJADO.search(estilo)
    if not achado:
        return ()
    medidas = _MEDIDA.findall(achado.group(1))
    if not medidas or any(unidade not in ("g", "") for _v, unidade in medidas):
        return ()
    valores = tuple(abs(float(v)) for v, _u in medidas)
    return valores if len(valores) >= 2 and sum(valores) > 0 else ()


def _parametro(estilo, nome, padrao=None):
    """Valor numerico de um parametro de LABEL. Ignora o texto entre aspas,
    que pode conter qualquer coisa -- inclusive 'p:' ou 's:'."""
    m = re.search(r"(?:^|[,(])%s:(-?[0-9.eE+-]+)g?(?=[,)])" % nome, estilo)
    if not m:
        return padrao
    try:
        return float(m.group(1))
    except ValueError:
        return padrao


def analisar_estilo(estilo):
    """Extrai a aparencia de uma style string do OGR.

    Formatos vistos na pratica:
        PEN(c:#ff0000,w:0.5g)                          linhas e pontos
        BRUSH(fc:#000000)                              areas e hachuras
        LABEL(f:"Arial",t:"AM-01",p:5,s:2.5g,a:90,
              dx:50g,dy:10g,w:70,c:#0000ff)             textos

    Para textos: `p` e a posicao de ancoragem (1 a 12), `s` a altura em
    unidades do desenho, `a` a rotacao em graus anti-horarios, `dx`/`dy` o
    deslocamento ate o ponto de alinhamento real e `w` a largura em porcento.
    """
    vazio = {"cor": None, "tamanho": None, "rotulo": False, "hachura": False,
             "ancora": 1, "dx": 0.0, "dy": 0.0, "angulo": 0.0, "largura": 100.0,
             "oculta": False, "fonte": None, "tracejado": ()}
    if not estilo:
        return vazio
    achado = _COR.search(estilo) or _COR_PREENCHIMENTO.search(estilo)
    resultado = dict(vazio)
    resultado["tracejado"] = _tracejado(estilo)
    resultado["cor"] = hex_para_rgb(achado.group(1)) if achado else None
    # O GDAL marca o que esta em camada desligada ou congelada com cor
    # inteiramente transparente (#rrggbb00). A cor de verdade fica nos seis
    # primeiros digitos; a transparencia so diz que o AutoCAD nao mostra.
    resultado["oculta"] = bool(achado and (achado.group(2) or "").lower() == "00")
    resultado["rotulo"] = estilo.lstrip().startswith("LABEL(")
    resultado["hachura"] = "BRUSH(" in estilo and "PEN(" not in estilo

    if resultado["rotulo"]:
        # a fonte do estilo de texto ("Verdana", "romanc.shx"...)
        fonte = re.search(r'(?<![a-z])f:"((?:[^"\\]|\\.)*)"', estilo)
        resultado["fonte"] = fonte.group(1) if fonte else None
        # tira o texto entre aspas antes de procurar os parametros
        limpo = re.sub(r'(t|f):"(?:[^"\\]|\\.)*"', "", estilo, flags=re.S)
        resultado["tamanho"] = _parametro(limpo, "s")
        resultado["ancora"] = int(_parametro(limpo, "p", 1))
        resultado["dx"] = _parametro(limpo, "dx", 0.0)
        resultado["dy"] = _parametro(limpo, "dy", 0.0)
        resultado["angulo"] = _parametro(limpo, "a", 0.0)
        resultado["largura"] = _parametro(limpo, "w", 100.0)
    return resultado


# ---------------------------------------------------------------------------
# Codificacao
# ---------------------------------------------------------------------------

_CODEPAGES = {
    "ANSI_874": "cp874", "ANSI_932": "cp932", "ANSI_936": "cp936",
    "ANSI_949": "cp949", "ANSI_950": "cp950", "ANSI_1250": "cp1250",
    "ANSI_1251": "cp1251", "ANSI_1252": "cp1252", "ANSI_1253": "cp1253",
    "ANSI_1254": "cp1254", "ANSI_1255": "cp1255", "ANSI_1256": "cp1256",
    "ANSI_1257": "cp1257", "ANSI_1258": "cp1258",
    "UTF8": "utf-8", "UTF-8": "utf-8",
}


def _codepage_do_cabecalho(caminho):
    try:
        with open(caminho, "rb") as fp:
            inicio = fp.read(8192)
        pos = inicio.find(b"$DWGCODEPAGE")
        if pos == -1:
            return "cp1252"
        trecho = inicio[pos:pos + 120].split(b"\n")
        for i, linha in enumerate(trecho):
            if linha.strip() == b"3" and i + 1 < len(trecho):
                nome = trecho[i + 1].strip().decode("ascii", "replace").upper()
                return _CODEPAGES.get(nome, "cp1252")
    except Exception:
        pass
    return "cp1252"


def _eh_utf8(caminho):
    """True se o arquivo inteiro decodifica como UTF-8 e tem algum byte alto.

    Usa um decodificador incremental: cortar o arquivo em blocos de tamanho
    fixo partiria caracteres de varios bytes ao meio e daria falso negativo.
    """
    decodificador = codecs.getincrementaldecoder("utf-8")()
    tem_byte_alto = False
    try:
        with open(caminho, "rb") as fp:
            while True:
                bloco = fp.read(1 << 20)
                if not bloco:
                    break
                if not tem_byte_alto and any(b > 127 for b in bloco):
                    tem_byte_alto = True
                decodificador.decode(bloco)
            decodificador.decode(b"", True)
    except (UnicodeDecodeError, OSError):
        return False
    return tem_byte_alto


def detectar_codificacao(caminho):
    """Devolve (codec_python, valor_para_DXF_ENCODING_ou_None).

    O cabecalho do DXF declara a codificacao em $DWGCODEPAGE, e o GDAL obedece.
    O problema e que nem todo programa cumpre o que declara: o ODA File
    Converter grava o texto em UTF-8 mantendo ANSI_1252 no cabecalho. O GDAL
    entao le os bytes como cp1252 e 'PIEZOMETROS' vira 'PIEZAMETROS'.

    Por isso o conteudo manda sobre a declaracao: se o arquivo inteiro e UTF-8
    valido e tem acento, e UTF-8, e avisamos o GDAL com DXF_ENCODING. Um
    arquivo ANSI de verdade dificilmente passa por UTF-8 valido por acidente.
    """
    if _eh_utf8(caminho):
        return "utf-8", "UTF-8"
    return _codepage_do_cabecalho(caminho), None


# ---------------------------------------------------------------------------
# Leitura das entidades com a cor ja resolvida
# ---------------------------------------------------------------------------

def id_da_feicao(feicao, posicao):
    """O id que o GDAL da a uma feicao do DXF: um numero, o mesmo em toda leitura do mesmo
    arquivo (o EntityHandle nao serve: repete nas feicoes de um bloco inserido varias vezes).
    Sem id, vale a posicao da feicao na leitura."""
    try:
        return int(feicao.get("id"))
    except (TypeError, ValueError):
        return posicao


@contextmanager
def abrir_entidades(caminho_dxf, fundir_blocos=False, opcoes_extra=None):
    """Abre o DXF entregando, em cada feicao, o campo 'estilo' do OGR.

    Devolve (colecao, tem_estilo). `tem_estilo` False significa que o VRT nao
    pode ser usado e as cores terao de vir da tabela LAYER.

    `fundir_blocos=False` faz o GDAL devolver cada peca de um bloco
    separadamente. Com a fusao ligada (o padrao do GDAL) as pecas viram uma
    geometria so e todas herdam UMA cor -- uma seta verde com ponta magenta
    chega inteiramente verde.
    """
    _codec, encoding_gdal = detectar_codificacao(caminho_dxf)
    opcoes = {"DXF_MERGE_BLOCK_GEOMETRIES": "TRUE" if fundir_blocos else "FALSE"}
    if encoding_gdal:
        opcoes["DXF_ENCODING"] = encoding_gdal
    opcoes.update(opcoes_extra or {})

    vrt = copia = None
    try:
        copia = _copia_que_o_gdal_entende(caminho_dxf)
        fonte = copia or caminho_dxf
        try:
            vrt = _escrever_vrt(fonte)
            with fiona.Env(**opcoes):
                with fiona.open(vrt) as origem:
                    yield origem, True
        except Exception:
            # Sem o VRT ainda da para converter; so as cores ficam por camada.
            with fiona.Env(**opcoes):
                with fiona.open(fonte) as origem:
                    yield origem, False
    finally:
        for temporario in (vrt, copia):
            if temporario and os.path.exists(temporario):
                try:
                    os.remove(temporario)
                except OSError:
                    pass


# Ate o DXF 2007, a borda de hachura em spline termina nos pontos de controle (e nos pesos);
# o numero de pontos de ajuste (grupo 97) so aparece no 2010. O GDAL le esse 97 em qualquer
# versao: pega o 97 seguinte, o dos objetos de origem da borda, se perde e junta a hachura
# com as entidades depois dela numa feicao so (geometria da hachura, handle da ultima). No
# DWG do pai, convertido pelo ODA para o 2004, sumiam assim uma linha de chamada e uma
# spline. A copia ganha um "97 0" (nenhum ponto de ajuste) onde ele falta.
_HATCH = re.compile(rb"\n[ \t]*0[ \t]*\r?\nHATCH[ \t]*\r?\n")
_CORPO_DA_SPLINE = frozenset((94, 73, 74, 95, 96, 40, 10, 20, 42))


def _pares_da_entidade(dados, inicio):
    """[(codigo, valor, posicao do codigo)] de uma entidade, a partir do primeiro codigo
    depois do "0 / TIPO", ate o proximo codigo 0."""
    pares = []
    pos, fim = inicio, len(dados)
    while pos < fim:
        quebra = dados.find(b"\n", pos)
        if quebra < 0:
            break
        quebra_valor = dados.find(b"\n", quebra + 1)
        if quebra_valor < 0:
            quebra_valor = fim
        try:
            codigo = int(dados[pos:quebra])
        except ValueError:
            break
        if codigo == 0:
            break
        pares.append((codigo, dados[quebra + 1:quebra_valor].strip(), pos))
        pos = quebra_valor + 1
    return pares


def _sem_ajuste(pares, k):
    """True se a spline que terminou antes de pares[k] nao trouxe o 97 dos pontos de
    ajuste: o que vem ali e outra aresta (72) ou o 97 dos objetos de origem da borda."""
    if k >= len(pares) or pares[k][0] != 97:
        return True
    try:
        n = int(pares[k][1])
    except ValueError:
        return True
    depois = pares[k + 1][0] if k + 1 < len(pares) else 0
    if n > 0:
        return depois != 11              # ajuste: 11/21; objetos de origem: 330
    return depois not in (12, 13, 72, 97)    # sem objetos de origem vem 92 ou 75


def _onde_falta_o_97(dados):
    """Posicoes (em bytes) em que falta o "97 0" das bordas em spline das hachuras."""
    posicoes = []
    for achado in _HATCH.finditer(dados):
        pares = _pares_da_entidade(dados, achado.end())
        for i, (codigo, valor, _pos) in enumerate(pares):
            if codigo != 72 or valor != b"4":     # 72 = 4: aresta em spline
                continue
            k = i + 1
            while k < len(pares) and pares[k][0] in _CORPO_DA_SPLINE:
                k += 1
            if _sem_ajuste(pares, k):
                posicoes.append(pares[k][2] if k < len(pares) else None)
    return [p for p in posicoes if p is not None]


def _copia_que_o_gdal_entende(caminho_dxf):
    """Caminho de uma copia temporaria do DXF com o 97 que o GDAL espera nas bordas em
    spline das hachuras, ou None se o arquivo ja serve como esta."""
    try:
        with open(caminho_dxf, "rb") as fp:
            dados = fp.read()
    except OSError:
        return None
    if b"HATCH" not in dados:
        return None
    posicoes = _onde_falta_o_97(dados)
    if not posicoes:
        return None
    quebra = b"\r\n" if b"\r\n" in dados[:200] else b"\n"
    falta = b"97" + quebra + b"0" + quebra
    descritor, caminho = tempfile.mkstemp(suffix=".dxf", prefix="conversor_")
    dwg.anotar_temporario(caminho)             # se o programa fechar no meio da leitura
    try:
        with os.fdopen(descritor, "wb") as fp:
            anterior = 0
            for pos in posicoes:
                fp.write(dados[anterior:pos])
                fp.write(falta)
                anterior = pos
            fp.write(dados[anterior:])
    except OSError:
        try:
            os.remove(caminho)
        except OSError:
            pass
        return None
    return caminho


def _escrever_vrt(caminho_dxf):
    from xml.sax.saxutils import escape
    descritor, caminho = tempfile.mkstemp(suffix=".vrt", prefix="conversor_")
    os.close(descritor)
    dwg.anotar_temporario(caminho)             # se o programa fechar no meio da leitura
    with open(caminho, "w", encoding="utf-8") as fp:
        fp.write('<OGRVRTDataSource><OGRVRTLayer name="entities">'
                 "<SrcDataSource>%s</SrcDataSource>"
                 '<SrcSQL dialect="OGRSQL">'
                 "SELECT *, OGR_STYLE AS estilo FROM entities"
                 "</SrcSQL></OGRVRTLayer></OGRVRTDataSource>"
                 % escape(os.path.abspath(caminho_dxf)))
    return caminho


# ---------------------------------------------------------------------------
# Reserva: cores pela tabela LAYER (so entra em acao se o VRT falhar)
# ---------------------------------------------------------------------------

def _pares(caminho, codec):
    """Percorre o DXF como pares (codigo de grupo, valor), que e como ele e escrito."""
    with open(caminho, "r", encoding=codec, errors="replace") as fp:
        while True:
            linha_codigo = fp.readline()
            if not linha_codigo:
                return
            linha_valor = fp.readline()
            if not linha_valor:
                return
            try:
                codigo = int(linha_codigo.strip())
            except ValueError:
                continue
            yield codigo, linha_valor.rstrip("\r\n")


def camadas_ocultas(caminho_dxf):
    """Nomes das camadas que o AutoCAD nao mostra: desligadas (cor negativa
    na tabela LAYER) ou congeladas (bit 1 do grupo 70). Vazio se algo der
    errado.

    Serve para o que o GDAL nao marca sozinho: as imagens e as hachuras, que
    sao lidas por fora dele.
    """
    ocultas = set()
    codec, _ = detectar_codificacao(caminho_dxf)
    try:
        secao = None
        proximo_e_secao = False
        registro = None
        for codigo, valor in _pares(caminho_dxf, codec):
            if codigo == 0:
                if registro and registro.get("nome"):
                    try:
                        desligada = int(registro.get("cor", "7")) < 0
                        congelada = bool(int(registro.get("flags", "0")) & 1)
                    except ValueError:
                        desligada = congelada = False
                    if desligada or congelada:
                        ocultas.add(registro["nome"])
                proximo_e_secao = valor == "SECTION"
                registro = {} if (valor == "LAYER" and secao == "TABLES") else None
                continue
            if proximo_e_secao and codigo == 2:
                secao, proximo_e_secao = valor, False
                continue
            if registro is None:
                continue
            if codigo == 2:
                registro["nome"] = valor
            elif codigo == 62:
                registro["cor"] = valor
            elif codigo == 70:
                registro["flags"] = valor
    except Exception:
        return set()
    return ocultas


def cotas_das_splines(caminho_dxf):
    """{handle: [Z de cada ponto de controle]} de cada SPLINE do desenho.

    O GDAL le a spline mas entrega os vertices sem Z, e e como curva de nivel
    que ela costuma aparecer: a cota esta nos pontos de controle (grupo 30).
    Vazio se algo der errado -- as splines saem sem cota, como antes.
    """
    cotas = {}
    codec, _ = detectar_codificacao(caminho_dxf)
    try:
        em_spline, handle, zs = False, None, []
        for codigo, valor in _pares(caminho_dxf, codec):
            if codigo == 0:
                if em_spline and handle and zs:
                    cotas[handle] = zs
                em_spline, handle, zs = valor == "SPLINE", None, []
            elif not em_spline:
                continue
            elif codigo == 5:
                handle = valor.strip().upper()
            elif codigo == 30:           # Z de um ponto de controle
                try:
                    zs.append(float(valor))
                except ValueError:
                    pass
    except Exception:
        return {}
    return cotas


def ordem_de_desenho(caminho_dxf):
    """{handle: chave} com a ordem em que o AutoCAD desenha cada entidade.

    O AutoCAD desenha na ordem das "chaves de ordenacao": a chave de uma
    entidade e o proprio handle, a nao ser que o "trazer para frente/mandar
    para tras" (DRAWORDER) a tenha mudado -- ai a nova chave fica na tabela
    SORTENTSTABLE (pares 331 = entidade, 5 = chave). Devolve so o que a
    tabela muda, ja como numero; para as outras, a chave e int(handle, 16).
    """
    chaves = {}
    codec, _ = detectar_codificacao(caminho_dxf)
    try:
        na_tabela = False
        entidade = None
        for codigo, valor in _pares(caminho_dxf, codec):
            if codigo == 0:
                na_tabela = valor == "SORTENTSTABLE"
                entidade = None
            elif not na_tabela:
                continue
            elif codigo == 100:
                entidade = None
            elif codigo == 331:
                entidade = valor.upper()
            elif codigo == 5 and entidade:
                chaves[entidade] = int(valor, 16)
                entidade = None
    except Exception:
        return {}
    return chaves


def estilo_de_ponto(caminho_dxf):
    """($PDMODE, $PDSIZE) do cabecalho: como o AutoCAD desenha os pontos.

    PDMODE: 0 ponto, 1 nada, 2 cruz (+), 3 xis, 4 tracinho; somado a 32
    ganha um circulo em volta, a 64 um quadrado. PDSIZE acima de zero e o
    tamanho em unidades do desenho; zero e 5% da altura da area de desenho,
    e negativo, essa porcentagem -- tamanhos de tela. Sem cabecalho: (0, 0).
    """
    codec, _ = detectar_codificacao(caminho_dxf)
    modo, tamanho = 0, 0.0
    try:
        variavel = None
        for codigo, valor in _pares(caminho_dxf, codec):
            if codigo == 9:
                variavel = valor
            elif variavel == "$PDMODE" and codigo == 70:
                modo = int(valor)
            elif variavel == "$PDSIZE" and codigo == 40:
                tamanho = float(valor)
            elif codigo == 0 and valor == "ENDSEC":
                break
    except Exception:
        return 0, 0.0
    return modo, tamanho


# ---------------------------------------------------------------------------
# Fonte de cada texto
# ---------------------------------------------------------------------------
#
# O GDAL so poe na style string a fonte TrueType de um estilo de texto (a do
# xdata ACAD); para estilo de fonte de traco (.shx) ele escreve "Arial". Mas
# a simplex do AutoCAD e bem mais estreita que a Arial e tem o espaco duas
# vezes e meia mais largo -- sem saber que o texto e simplex, nao da para
# saber onde ele termina no desenho. O estilo de cada texto vem daqui.

_CODIGOS_TEXTO = re.compile(r"%%([dDpPcC%uUoOkK]|\d{3})|\\U\+([0-9A-Fa-f]{4})")
_SIMBOLOS = {"d": "°", "p": "±", "c": "⌀", "%": "%"}


def _decodificar_texto(texto):
    """O texto de um TEXT como o GDAL o entrega (%%d -> grau, \\U+00B0...)."""
    def troca(m):
        if m.group(2):
            return chr(int(m.group(2), 16))
        codigo = m.group(1)
        if codigo.isdigit():
            return chr(int(codigo))
        return _SIMBOLOS.get(codigo.lower(), "")
    return _CODIGOS_TEXTO.sub(troca, texto or "")


def _chave_texto(texto):
    """So letras e numeros: casa o texto mesmo com simbolos escritos diferente."""
    return re.sub(r"\W+", "", texto or "").lower()


class FontesDosTextos:
    """Estilo de texto de cada TEXT e atributo do desenho, achado pelo que o
    GDAL entrega: o handle da entidade -- ou, para texto de dentro de bloco,
    o do INSERT, e ai o estilo vem do texto igual no bloco."""

    def __init__(self):
        self.estilos = {}        # NOME DO ESTILO -> {"arquivo", "familia"}
        self.por_handle = {}     # handle -> (estilo, alinhamento horizontal)
        self.insert_bloco = {}   # handle do INSERT -> nome do bloco
        self.blocos = {}         # bloco -> ([(texto, chave, estilo, alinh.)], [blocos])
        self._cache = {}

    def achar(self, handle, texto):
        """{"arquivo", "familia", "halign"} do estilo do texto, ou None."""
        h = str(handle or "").upper()
        info = self.por_handle.get(h)
        if info is None and h in self.insert_bloco:
            chave = (self.insert_bloco[h], texto)
            if chave not in self._cache:
                self._cache[chave] = self._no_bloco(*chave)
            info = self._cache[chave]
        if info is None:
            return None
        estilo, halign = info
        fonte = self.estilos.get(estilo, {})
        return {"arquivo": fonte.get("arquivo", ""), "familia": fonte.get("familia"),
                "halign": halign}

    def _no_bloco(self, nome, texto):
        alvo = texto or ""
        chave = _chave_texto(alvo)
        vistos, fila, parecidos = [], [nome], []
        while fila and len(vistos) < 64:
            bloco = fila.pop(0)
            if bloco in vistos:
                continue
            vistos.append(bloco)
            textos, inserts = self.blocos.get(bloco, ([], []))
            for t, k, estilo, halign in textos:
                if t == alvo:
                    return estilo, halign
                if k == chave:
                    parecidos.append((estilo, halign))
            fila.extend(inserts)
        if parecidos:
            return parecidos[0]
        todos = {(e, a) for b in vistos for (_t, _k, e, a) in self.blocos.get(b, ([], []))[0]}
        return todos.pop() if len(todos) == 1 else None


def fontes_dos_textos(caminho_dxf):
    """Le os estilos de texto e o estilo de cada TEXT, ATTRIB e ATTDEF (ver
    FontesDosTextos). Se algo der errado, devolve um indice vazio: os textos
    ficam como o GDAL os descreve."""
    indice = FontesDosTextos()
    codec, _ = detectar_codificacao(caminho_dxf)
    interesse = {1, 2, 3, 5, 7, 72}
    try:
        secao = None
        proximo_e_secao = False
        bloco = None
        tipo, registro, app = None, None, None
        for codigo, valor in _pares(caminho_dxf, codec):
            if codigo == 0:
                if registro is not None:
                    bloco = _guardar(indice, tipo, registro, bloco)
                proximo_e_secao = valor == "SECTION"
                tipo, app = valor, None
                if valor == "ENDBLK":
                    bloco = None
                registro = {} if (
                    (secao == "TABLES" and valor == "STYLE")
                    or (secao in ("BLOCKS", "ENTITIES")
                        and valor in ("TEXT", "ATTRIB", "ATTDEF", "INSERT", "BLOCK"))
                ) else None
                continue
            if proximo_e_secao and codigo == 2:
                secao, proximo_e_secao = valor, False
                continue
            if registro is None:
                continue
            if codigo == 101:          # objeto embutido (atributo de varias linhas)
                registro["fim"] = True
            elif registro.get("fim"):
                continue
            elif codigo == 1001:
                app = valor
            elif codigo == 1000 and app == "ACAD":
                registro.setdefault(1000, valor)
            elif codigo in interesse and app is None:
                registro.setdefault(codigo, valor)
        if registro is not None:
            _guardar(indice, tipo, registro, bloco)
    except Exception:
        return FontesDosTextos()
    return indice


def _guardar(indice, tipo, registro, bloco):
    """Guarda um registro lido; devolve o bloco em leitura depois dele."""
    if tipo == "BLOCK":
        return registro.get(2) or bloco
    if tipo == "STYLE":
        if registro.get(2):
            indice.estilos[registro[2].upper()] = {"arquivo": registro.get(3, ""),
                                                   "familia": registro.get(1000)}
        return bloco
    if tipo == "INSERT":
        if registro.get(2):
            if registro.get(5):
                indice.insert_bloco[registro[5].upper()] = registro[2]
            if bloco is not None:
                indice.blocos.setdefault(bloco, ([], []))[1].append(registro[2])
        return bloco
    estilo = (registro.get(7) or "STANDARD").upper()
    try:
        halign = int(registro.get(72) or 0)
    except ValueError:
        halign = 0
    if registro.get(5):
        indice.por_handle[registro[5].upper()] = (estilo, halign)
    if bloco is not None:
        texto = _decodificar_texto(registro.get(1, ""))
        indice.blocos.setdefault(bloco, ([], []))[0].append(
            (texto, _chave_texto(texto), estilo, halign))
    return bloco


def ler_cores_das_camadas(caminho_dxf):
    """{nome_da_camada: (r,g,b)} lido da tabela LAYER. Vazio se algo der errado."""
    cores = {}
    codec, _ = detectar_codificacao(caminho_dxf)
    try:
        secao = None
        proximo_e_secao = False
        registro = None
        for codigo, valor in _pares(caminho_dxf, codec):
            if codigo == 0:
                if registro and registro.get("nome"):
                    rgb = None
                    if "cor_verdadeira" in registro:
                        try:
                            v = int(registro["cor_verdadeira"])
                            rgb = ((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF)
                        except ValueError:
                            rgb = None
                    if rgb is None and "aci" in registro:
                        rgb = aci_para_rgb(registro["aci"])
                    if rgb:
                        cores[registro["nome"]] = rgb
                proximo_e_secao = valor == "SECTION"
                registro = {} if (valor == "LAYER" and secao == "TABLES") else None
                continue
            if proximo_e_secao and codigo == 2:
                secao, proximo_e_secao = valor, False
                continue
            if registro is None:
                continue
            if codigo == 2:
                registro["nome"] = valor
            elif codigo == 62:
                registro["aci"] = valor
            elif codigo == 420:
                registro["cor_verdadeira"] = valor
    except Exception:
        return cores
    return cores
