# -*- coding: utf-8 -*-
"""Motor de conversao: le, reprojeta e grava. Sem nenhuma dependencia de interface."""

import bisect
import csv
import math
import os
import re
import warnings

import fiona
import pyproj
from fiona.crs import CRS

from . import (cad_ezdxf, crs_presets, dwg, dxf_estilo, dxf_extras, dxfio,
               fora_da_area, imagens_cad, qgis_project, textos_cad)

warnings.filterwarnings("ignore")

# Campos que o driver DXF do GDAL entrega na leitura. Sao os unicos que existem:
# o DXF nao tem tabela de atributos como um shapefile.
CAMPOS_DXF = ["Layer", "SubClasses", "Linetype", "EntityHandle", "Text"]

# Campo acrescentado por nos: a cor da entidade no desenho, em #rrggbb. E o
# que o projeto do QGIS usa para pintar cada feicao com a cor que ela tinha no
# AutoCAD. Sem underscore inicial porque o shapefile implica com isso.
CAMPO_COR = "cor_cad"
CAMPOS_SAIDA = CAMPOS_DXF + [CAMPO_COR]

# O shapefile limita nomes de campo a 10 caracteres.
ABREVIACOES_SHP = {"EntityHandle": "Handle", "SubClasses": "SubClass"}

EXTENSOES_VETOR = {
    ".shp": "ESRI Shapefile", ".gpkg": "GPKG", ".geojson": "GeoJSON",
    ".json": "GeoJSON", ".gml": "GML", ".tab": "MapInfo File",
}
EXTENSOES_CAD = {".dxf", ".dwg"}


class ErroConversao(Exception):
    pass


# ---------------------------------------------------------------------------
# Inspecao de arquivos (a interface usa para preencher os menus)
# ---------------------------------------------------------------------------

def listar_camadas(caminho):
    """Nomes das camadas de um arquivo. Um GPKG pode ter varias; um SHP tem uma.

    A tabela de estilos do QGIS (layer_styles), que vai dentro dos GPKG que este programa
    grava e dos que o QGIS salva com estilo, nao e dado do desenho e fica de fora."""
    try:
        return [nome for nome in fiona.listlayers(caminho)
                if nome != qgis_project.TABELA_ESTILOS]
    except Exception as erro:
        raise ErroConversao("Nao foi possivel abrir '%s':\n%s"
                            % (os.path.basename(caminho), erro))


def inspecionar(caminho, camada=None):
    """Devolve (epsg, campos, n_feicoes_aprox, tipo_geometria) de uma camada."""
    with fiona.open(caminho, layer=camada) as origem:
        epsg = None
        if origem.crs:
            try:
                epsg = CRS(origem.crs).to_epsg()
            except Exception:
                epsg = None
        campos = list(origem.schema.get("properties", {}).keys())
        tipo = origem.schema.get("geometry", "Unknown")
        try:
            total = len(origem)
        except Exception:
            total = None
    return epsg, campos, total, tipo


def eh_cad(caminho):
    return os.path.splitext(caminho)[1].lower() in EXTENSOES_CAD


# ---------------------------------------------------------------------------
# Reprojecao
# ---------------------------------------------------------------------------

def _transformador(epsg_origem, epsg_destino):
    if not epsg_origem or not epsg_destino or int(epsg_origem) == int(epsg_destino):
        return None
    return pyproj.Transformer.from_crs(
        "EPSG:%d" % int(epsg_origem), "EPSG:%d" % int(epsg_destino), always_xy=True)


def _reprojetar(coords, transformador):
    """Aplica a transformacao mantendo a estrutura aninhada e preservando o Z."""
    if not coords:
        return coords
    if isinstance(coords[0], (int, float)):
        x, y = transformador.transform(coords[0], coords[1])
        return (x, y, coords[2]) if len(coords) > 2 else (x, y)
    return [_reprojetar(parte, transformador) for parte in coords]


def _geometria_reprojetada(geom, transformador):
    if geom is None or transformador is None:
        return geom
    return {"type": geom["type"],
            "coordinates": _reprojetar(geom["coordinates"], transformador)}


def _primeiro_ponto(geom):
    """Um ponto representativo da geometria, para ancorar o rotulo de texto."""
    coords = geom["coordinates"]
    while coords and not isinstance(coords[0], (int, float)):
        coords = coords[0]
    if not coords:
        return None
    return (coords[0], coords[1], coords[2] if len(coords) > 2 else 0.0)


def _explodir(geom):
    """Quebra multi-geometrias e colecoes em partes simples."""
    if geom is None:
        return []
    tipo = geom["type"]
    if tipo == "GeometryCollection":
        partes = []
        for sub in geom.get("geometries", []):
            partes.extend(_explodir(sub))
        return partes
    if tipo.startswith("Multi"):
        simples = tipo[5:]
        return [{"type": simples, "coordinates": parte} for parte in geom["coordinates"]]
    return [geom]


def _tipo_base(geom):
    tipo = geom["type"]
    if tipo.startswith("Multi"):
        tipo = tipo[5:]
    return tipo


def _tem_cota(coords):
    """True se algum vertice tem Z diferente de zero (curva de nivel, ponto cotado)."""
    if not coords:
        return False
    if isinstance(coords[0], (int, float)):
        return len(coords) > 2 and abs(coords[2]) > 1e-9
    return any(_tem_cota(parte) for parte in coords)


def _com_cota_da_spline(geom, cotas):
    """Poe o Z nos vertices de uma spline que o GDAL entregou sem cota.

    Curva de nivel tem a mesma cota em todos os pontos de controle e ela vale
    para a linha toda. Se a cota varia, ela e interpolada ao longo da linha.
    """
    if geom["type"] != "LineString" or not cotas:
        return geom
    coords, n = geom["coordinates"], len(geom["coordinates"])
    if max(cotas) - min(cotas) < 1e-9 or len(cotas) == 1 or n < 2:
        zs = [cotas[0]] * n
    else:
        zs = []
        for i in range(n):
            pos = i / (n - 1) * (len(cotas) - 1)
            k = min(int(pos), len(cotas) - 2)
            zs.append(cotas[k] + (cotas[k + 1] - cotas[k]) * (pos - k))
    return {"type": "LineString",
            "coordinates": [(c[0], c[1], z) for c, z in zip(coords, zs)]}


def _fechada(coords):
    """Polilinha que termina onde comeca (o GDAL repete o primeiro vertice)."""
    if not coords or len(coords) < 4:
        return False
    a, b = coords[0], coords[-1]
    return abs(a[0] - b[0]) < 1e-9 and abs(a[1] - b[1]) < 1e-9


def _mediana(valores):
    if not valores:
        return None
    ordenados = sorted(valores)
    meio = len(ordenados) // 2
    if len(ordenados) % 2:
        return ordenados[meio]
    return (ordenados[meio - 1] + ordenados[meio]) / 2.0


def _estender(caixa, coords):
    """Amplia a caixa envolvente [xmin, ymin, xmax, ymax] com estas coordenadas."""
    if not coords:
        return
    if isinstance(coords[0], (int, float)):
        x, y = coords[0], coords[1]
        caixa[0] = min(caixa[0], x)
        caixa[1] = min(caixa[1], y)
        caixa[2] = max(caixa[2], x)
        caixa[3] = max(caixa[3], y)
        return
    for parte in coords:
        _estender(caixa, parte)


# ---------------------------------------------------------------------------
# QGIS  ->  AutoCAD
# ---------------------------------------------------------------------------

def qgis_para_cad(entradas, saida, epsg_destino, campo_camada=None,
                  campo_rotulo=None, epsg_origem_forcado=None,
                  somente_ascii=True, salvar_csv=True, altura_texto=2.5,
                  registrar=print):
    """Converte uma ou mais camadas vetoriais em um unico DXF (ou DWG).

    `entradas` e uma lista de dicts {'caminho': ..., 'camada': ... ou None}.
    O nome da camada no AutoCAD vem de `campo_camada`; se for None, usa o nome
    da camada de origem.
    """
    if not entradas:
        raise ErroConversao("Nenhum arquivo de entrada selecionado.")

    quer_dwg = os.path.splitext(saida)[1].lower() == ".dwg"
    if quer_dwg and not dwg.disponivel():
        raise ErroConversao(dwg.MENSAGEM_AUSENTE)

    destino_dxf = os.path.splitext(saida)[0] + ".dxf" if quer_dwg else saida

    if not crs_presets.eh_projetado(epsg_destino):
        registrar("AVISO: EPSG:%s usa graus, nao metros. O desenho vai sair "
                  "com fracoes de unidade de tamanho e nao serve para medir. "
                  "Prefira um UTM." % epsg_destino)

    feicoes = []
    rotulos = []
    linhas_csv = []
    camadas_criadas = set()
    ignoradas = 0

    for entrada in entradas:
        caminho = entrada["caminho"]
        camada = entrada.get("camada")
        nome_exibicao = camada or os.path.splitext(os.path.basename(caminho))[0]

        with fiona.open(caminho, layer=camada) as origem:
            epsg_origem = epsg_origem_forcado
            if not epsg_origem and origem.crs:
                try:
                    epsg_origem = CRS(origem.crs).to_epsg()
                except Exception:
                    pass
            if not epsg_origem:
                raise ErroConversao(
                    "A camada '%s' nao diz em que sistema de coordenadas esta "
                    "(falta o arquivo .prj).\nEscolha o sistema de origem na "
                    "tela antes de converter." % nome_exibicao)

            transformador = _transformador(epsg_origem, epsg_destino)
            if transformador:
                registrar("  %s: reprojetando de EPSG:%s para EPSG:%s"
                          % (nome_exibicao, epsg_origem, epsg_destino))
            else:
                registrar("  %s: ja esta em EPSG:%s" % (nome_exibicao, epsg_destino))

            for feicao in origem:
                geom = feicao.get("geometry")
                if geom is None:
                    ignoradas += 1
                    continue
                props = dict(feicao.get("properties") or {})

                if campo_camada and campo_camada in props:
                    bruto = props.get(campo_camada)
                    bruto = nome_exibicao if bruto in (None, "") else bruto
                else:
                    bruto = nome_exibicao
                camada_cad = dxfio.nome_camada(bruto, somente_ascii)
                camadas_criadas.add(camada_cad)

                geom = _geometria_reprojetada(geom, transformador)
                feicoes.append({"type": "Feature", "geometry": geom,
                                "properties": {"Layer": camada_cad}})

                if campo_rotulo and campo_rotulo in props:
                    texto = props.get(campo_rotulo)
                    if texto not in (None, ""):
                        ponto = _primeiro_ponto(geom)
                        if ponto:
                            rotulos.append({"x": ponto[0], "y": ponto[1], "z": ponto[2],
                                            "texto": texto, "camada": camada_cad})

                if salvar_csv:
                    linha = dict(props)
                    linha["_camada_autocad"] = camada_cad
                    linha["_geometria"] = geom["type"]
                    linha["_origem"] = nome_exibicao
                    linhas_csv.append(linha)

    if not feicoes:
        raise ErroConversao("Nenhuma feicao com geometria foi encontrada nos "
                            "arquivos selecionados.")

    registrar("Gravando %d feicoes em %d camadas..." % (len(feicoes), len(camadas_criadas)))

    esquema = {"geometry": "Unknown", "properties": {"Layer": "str"}}
    # Por padrao o GDAL grava poligono como HATCH solida: no AutoCAD cada
    # unidade vira uma mancha preenchida que esconde tudo o que esta embaixo.
    # Em CAD, o limite de uma area e uma polilinha fechada.
    with fiona.Env(DXF_WRITE_HATCH="FALSE"):
        with fiona.open(destino_dxf, "w", driver="DXF", schema=esquema,
                        crs=CRS.from_epsg(int(epsg_destino))) as destino:
            destino.writerecords(feicoes)

    if rotulos:
        escritos = dxfio.injetar_textos(destino_dxf, rotulos, altura=altura_texto,
                                        somente_ascii=somente_ascii)
        registrar("%d rotulos de texto inseridos (campo '%s')." % (escritos, campo_rotulo))

    dxfio.finalizar_codificacao(destino_dxf, somente_ascii)
    dxfio.gravar_crs_acompanhante(destino_dxf, epsg_destino,
                                  {"camadas": sorted(camadas_criadas)})

    gerados = [destino_dxf]

    if salvar_csv and linhas_csv:
        caminho_csv = os.path.splitext(destino_dxf)[0] + "_atributos.csv"
        colunas = []
        for linha in linhas_csv:
            for chave in linha:
                if chave not in colunas:
                    colunas.append(chave)
        # utf-8-sig e ';' para o Excel em portugues abrir direito com dois cliques
        with open(caminho_csv, "w", newline="", encoding="utf-8-sig") as fp:
            escritor = csv.DictWriter(fp, fieldnames=colunas, delimiter=";")
            escritor.writeheader()
            escritor.writerows(linhas_csv)
        gerados.append(caminho_csv)
        registrar("Atributos salvos em %s (o DXF nao guarda tabela de atributos)."
                  % os.path.basename(caminho_csv))

    if quer_dwg:
        registrar("Gerando o .dwg...")
        dwg.dxf_para_dwg(destino_dxf, saida, registrar)
        gerados = [saida] + gerados[1:]
        registrar("DWG gravado no formato %s (abre no AutoCAD 2007)."
                  % dwg.VERSAO_SAIDA_DWG)

    if ignoradas:
        registrar("%d feicoes sem geometria foram ignoradas." % ignoradas)

    return {"arquivos": gerados, "feicoes": len(feicoes),
            "camadas": sorted(camadas_criadas), "rotulos": len(rotulos)}


# ---------------------------------------------------------------------------
# AutoCAD  ->  QGIS
# ---------------------------------------------------------------------------

# Campos acrescentados so nas camadas de texto: o que o QGIS precisa para
# desenhar cada texto onde e como ele estava no AutoCAD. Ver textos_cad.py.
CAMPOS_TEXTO = {"txt_tam": "float", "txt_ang": "float", "txt_h": "str",
                "txt_v": "str", "txt_larg": "float", "txt_html": "str"}

# Campo acrescentado so nas hachuras: o nome do padrao (SOLID, ANSI31...).
CAMPO_HACHURA = "hachura"

# Ordem no painel de camadas do QGIS. O que fica mais acima e desenhado por
# ultimo, por cima dos demais: texto sobre tudo; as linhas do padrao das
# hachuras (Textura) abaixo das linhas do desenho; as hachuras solidas no
# fundo. E a convencao do AutoCAD, que manda a hachura para tras do contorno.
ORDEM = {"Texto": 0, "Point": 1, "LineString": 2, "Textura": 3, "Polygon": 4,
         "Hachura": 5}


def _preparar_texto(geom, props, aparencia, mtexts, indice_mtext=None, fonte_cad=None):
    """Ajusta o ponto e preenche os campos que posicionam o texto no QGIS.

    Devolve (feicoes, formatado, ajuste). `feicoes` e uma lista de (geometria,
    propriedades): UMA POR LINHA para MTEXT, cada linha apoiada na sua linha
    de base, pela regra do AutoCAD (ver textos_cad.linhas_de_base); para
    TEXT, uma por trecho (ver _pecas_do_texto). `formatado` diz se o texto
    tem cor, fonte ou negrito proprios em algum trecho -- nesse caso a camada
    precisa de rotulo em HTML para mostra-los. `ajuste` (so TEXT) e o que
    _ajustar_textos precisa para acertar o tamanho da letra olhando os
    vizinhos; `fonte_cad` e o estilo do texto (dxf_estilo.FontesDosTextos).
    """
    coords = geom["coordinates"]
    x0, y0 = coords[0], coords[1]
    x, y = x0, y0
    ancora = aparencia["ancora"]
    if textos_cad.usa_deslocamento(ancora):
        x += aparencia["dx"]
        y += aparencia["dy"]

    eh_mtext = "MText" in (props.get("SubClasses") or "")
    horizontal, vertical = textos_cad.alinhamento(ancora, eh_mtext)
    altura = aparencia["tamanho"] or 2.5
    largura = aparencia["largura"] or 100.0
    angulo = float(aparencia["angulo"] or 0.0)
    texto = props.get("Text") or ""
    html = None
    formatado = False
    espacamento = 1.0
    if eh_mtext:
        # O ezdxf le a formatacao de dentro do MTEXT e a largura do quadro,
        # inclusive de MTEXT dentro de bloco. Sem ele, so a largura, e so
        # dos MTEXT soltos no desenho.
        achado = indice_mtext.achar(x0, y0, texto) if indice_mtext else None
        if achado:
            texto, html, formatado = textos_cad.montar_texto(
                achado["trechos"], altura, achado["largura"], largura, medir=cad_ezdxf.medir)
            espacamento = achado["espacamento"]
        else:
            info = mtexts.get((props.get("EntityHandle") or "").upper())
            if info:
                texto = textos_cad.quebrar(texto, info["largura"], altura, largura)
                espacamento = info["espacamento"]

    props["txt_tam"] = round(textos_cad.tamanho_qgis(altura), 6)
    props["txt_ang"] = angulo
    props["txt_h"] = horizontal
    # Fator de largura do estilo, so como informacao: o QGIS nao sabe
    # desenhar letra esticada nem comprimida. Esticada, o 4 afasta as letras
    # sem estica-las ("E m p r e e n d e d o r") e o 3 estica sem afastar;
    # comprimida, o 4 encavala as letras e some com os espacos
    # ("PLANTAESQUEMATICA...", nos titulos do mapa real) e o 3 as espalha.
    # A letra sai sempre na forma normal; a comprimida e encolhida ate a
    # largura que tem no AutoCAD (ver _encolher). As quebras de linha de
    # MTEXT continuam calculadas com a largura do desenho.
    props["txt_larg"] = float(largura)
    fonte_estilo = aparencia.get("fonte")

    seno = math.sin(math.radians(angulo))
    cosseno = math.cos(math.radians(angulo))

    def ponto(subir):
        """O ponto de insercao, subido (ou descido) na direcao do texto."""
        px, py = x - seno * subir, y + cosseno * subir
        return {"type": "Point",
                "coordinates": (px, py, coords[2]) if len(coords) > 2 else (px, py)}

    if not eh_mtext:
        props["txt_v"] = vertical
        medida = _medida_cad(fonte_cad)
        ajuste = {"x": x, "y": y, "z": coords[2] if len(coords) > 2 else None,
                  "angulo": angulo, "altura": altura, "vertical": vertical,
                  "horizontal": horizontal, "ajustavel": False, "exato": None,
                  "grupo": None, "fator": _encolher(texto, altura, largura, fonte_estilo)}
        ajuste["pecas"] = _pecas_do_texto(texto, horizontal, altura, largura, medida, props)
        exatos = [p["exato"] for p in ajuste["pecas"] if p["exato"]]
        if medida is not None and exatos:
            ajuste["ajustavel"] = True
            ajuste["exato"] = min(exatos)
            ajuste["fator"] = min(1.0, FOLGA_LARGURA * ajuste["exato"])
            ajuste["grupo"] = (medida.chave, round(largura, 1), round(altura, 2))
        return _colocar(ajuste), False, ajuste

    linhas = texto.split("\n")
    linhas_html = (html.split(textos_cad.QUEBRA_HTML) if html is not None
                   else [textos_cad.html_simples(linha) for linha in linhas])
    feicoes = []
    for linha, linha_html, base in zip(linhas, linhas_html, textos_cad.linhas_de_base(
            vertical, len(linhas), altura, espacamento)):
        if not linha.strip():
            continue           # linha em branco so ocupa o lugar
        p = dict(props)
        p["Text"] = linha
        p["txt_html"] = linha_html
        p["txt_v"] = "Base"
        if "font-family" not in linha_html:     # linha desenhada na Arial
            p["txt_tam"] = round(textos_cad.tamanho_qgis(
                altura * _encolher(linha, altura, largura, fonte_estilo)), 6)
        feicoes.append((ponto(base), p))
    return feicoes, formatado, None


def _encolher(texto, altura, largura, fonte_estilo):
    """Quanto encolher (1 = nada) um texto de letra COMPRIMIDA para ele caber
    na largura que tem no AutoCAD.

    O QGIS nao comprime letra (ver _preparar_texto), e na largura normal um
    texto comprimido invade o vizinho: no carimbo do INCRA do LOTEAMENTO, os
    rotulos a 57% ("Matriculas/Transcricoes:", "Escala:", "Resp. Tec:")
    atropelavam os valores ao lado. Encolhida, a letra fica mais baixa que
    no AutoCAD, mas ocupa a mesma largura e nada se sobrepoe.

    A largura no AutoCAD e medida na fonte que o GDAL informa quando ela e
    uma fonte do Windows; as de traco do AutoCAD (.shx), o GDAL informa como
    Arial. Ate FOLGA_LARGURA a mais nao se mexe: a fonte do QGIS nunca e
    exatamente a do AutoCAD, e diferencas desse tamanho acontecem com
    qualquer texto. Assim os titulos do mapa real (Verdana a 85%, 16% mais
    largos na Arial) e os numeros das curvas (90%) ficam como estavam.

    Vale para as linhas de MTEXT e para os TEXT de fonte que nao se sabe
    medir; os de fonte conhecida (TrueType instalada, simplex, romans) sao
    acertados depois, olhando os vizinhos (ver _ajustar_textos).
    """
    if not largura or largura >= 100.0 or not texto.strip():
        return 1.0
    natural = textos_cad.largura_texto(texto, altura)        # como o QGIS desenha
    if natural <= 0:
        return 1.0
    no_cad = None
    if fonte_estilo:
        familia = cad_ezdxf.resolver_fonte(fonte_estilo)[0] if cad_ezdxf.DISPONIVEL else None
        if familia:
            no_cad = cad_ezdxf.medir(texto, altura, {"fonte": familia}, 100)
    if no_cad is None:
        no_cad = natural
    return min(1.0, FOLGA_LARGURA * no_cad * largura / 100.0 / natural)


# Quanto um texto de letra comprimida pode sair mais largo que no AutoCAD
# antes de ser encolhido (ver _encolher).
FOLGA_LARGURA = 1.15

# Quanto do vao ate o texto vizinho um texto pode ocupar no QGIS, se a letra
# dele sai mais larga que no AutoCAD (ver _ajustar_textos). Menos da metade:
# o vizinho tambem pode crescer na direcao dele.
FRACAO_DO_VAO = 0.45

# Onde fica a linha de base de um TEXT em relacao a ancora, em alturas.
_BASE_CAD = {"Base": 0.0, "Top": -1.0, "Half": -0.5, "Bottom": textos_cad.DESCIDA_CAD}

# Trechos de um texto separados por dois ou mais espacos.
_TRECHO = re.compile(r"[^ ]+(?: [^ ]+)*")


class _Medida:
    """Mede um trecho de texto como o AutoCAD o desenha (fator de largura 1).
    `chave` identifica a fonte nos grupos de _ajustar_textos."""

    def __init__(self, chave, funcao):
        self.chave = chave
        self._funcao = funcao

    def __call__(self, texto, altura):
        if not texto:
            return 0.0
        largura = self._funcao(texto, altura)
        return largura if largura is not None else textos_cad.largura_texto(texto, altura)


def _medida_cad(fonte_cad):
    """_Medida da fonte do estilo de um TEXT, ou None quando nao se sabe
    medir: fonte de traco sem tabela (txt, romanc, isocp...), TrueType que
    nao esta instalada, ou texto "alinhado"/"ajustado", cuja largura quem
    decide sao os dois pontos e nao a fonte."""
    if not fonte_cad or fonte_cad.get("halign") in (3, 5):
        return None
    arquivo = fonte_cad.get("arquivo") or ""
    familia = fonte_cad.get("familia")
    traco = textos_cad.fonte_de_traco(arquivo) or textos_cad.fonte_de_traco(familia)
    if traco:
        return _Medida(traco, lambda texto, altura: textos_cad.largura_shx(texto, altura, traco))
    eh_ttf = arquivo.lower().endswith((".ttf", ".ttc", ".otf"))
    if not (familia or eh_ttf) or not cad_ezdxf.DISPONIVEL:
        return None
    resolvida = cad_ezdxf.resolver_fonte(familia or os.path.splitext(os.path.basename(arquivo))[0])[0]
    if not resolvida:
        return None
    if resolvida.lower() == "arial":         # a fonte do QGIS: a medida e a dele
        return _Medida("arial", textos_cad.largura_texto)
    estilo = {"fonte": resolvida}
    if cad_ezdxf.medir("A", 1.0, estilo) is None:
        return None
    return _Medida(resolvida.lower(), lambda texto, altura: cad_ezdxf.medir(texto, altura, estilo))


def _pecas_do_texto(texto, horizontal, altura, largura, medida, props):
    """Os pedacos em que um TEXT e desenhado no QGIS, e onde fica cada um.

    Dois ou mais espacos seguidos, num texto alinhado a esquerda, abrem lugar
    para outro texto: no carimbo do LOTEAMENTO, "MERIDIANO CENTRAL    %%d WGr"
    tem o atributo 45 nos quatro espacos. O espaco da simplex e duas vezes e
    meia o da Arial, e as letras tem outra largura: desenhado inteiro, o texto
    poe o "grau WGr" em outro lugar, e o "CENTRAL" passava por cima do 45.
    Entao cada trecho vira um rotulo, comecando onde comeca no AutoCAD. Sem
    saber medir a fonte do AutoCAD (`medida` None), o texto fica inteiro.

    Cada peca tem as propriedades do rotulo, o deslocamento ao longo da
    linha (None: o texto inteiro, na ancora), onde a tinta comeca e termina
    no AutoCAD e no QGIS -- este como (base, c0, c1), a tinta indo de base +
    c0 * fator a base + c1 * fator --, tudo relativo a ancora, e o fator
    "exato": quanto a Arial precisa encolher para o trecho ter a largura que
    tem no AutoCAD.
    """
    fator_largura = (largura or 100.0) / 100.0

    def natural(trecho):
        return textos_cad.largura_texto(trecho, altura)

    def no_cad(trecho):
        return medida(trecho, altura) * fator_largura

    trechos = list(_TRECHO.finditer(texto))
    if medida is not None and horizontal == "Left" and "  " in texto and trechos:
        pecas = []
        for m in trechos:
            trecho = m.group(0)
            inicio, w_cad, w_qgis = no_cad(texto[:m.start()]), no_cad(trecho), natural(trecho)
            p = dict(props)
            p["Text"] = trecho
            p["txt_html"] = textos_cad.html_simples(trecho)
            p["txt_h"] = "Left"
            pecas.append({"props": p, "deslocamento": inicio, "qgis": (inicio, 0.0, w_qgis),
                          "tinta_cad": (inicio, inicio + w_cad),
                          "exato": w_cad / w_qgis if w_qgis > 0 else None})
        return pecas

    props["Text"] = texto
    props["txt_html"] = textos_cad.html_simples(texto)
    limpo = texto.strip(" ")
    antes = texto[:len(texto) - len(texto.lstrip(" "))]
    depois = texto[len(texto.rstrip(" ")):] if limpo else ""
    n_antes, n_limpo, n_depois, n_tudo = natural(antes), natural(limpo), natural(depois), natural(texto)
    if horizontal == "Center":
        c0, c1 = n_antes - n_tudo / 2.0, n_tudo / 2.0 - n_depois
    elif horizontal == "Right":
        c0, c1 = n_antes - n_tudo, -n_depois
    else:
        c0, c1 = n_antes, n_antes + n_limpo
    peca = {"props": props, "deslocamento": None, "qgis": (0.0, c0, c1),
            "tinta_cad": None, "exato": None}
    if medida is not None and n_limpo > 0:
        w_antes, w_limpo, w_depois, w_tudo = no_cad(antes), no_cad(limpo), no_cad(depois), no_cad(texto)
        if horizontal == "Center":
            peca["tinta_cad"] = (w_antes - w_tudo / 2.0, w_tudo / 2.0 - w_depois)
        elif horizontal == "Right":
            peca["tinta_cad"] = (w_antes - w_tudo, -w_depois)
        else:
            peca["tinta_cad"] = (w_antes, w_antes + w_limpo)
        peca["exato"] = w_limpo / n_limpo
    return [peca]


def _colocar(ajuste):
    """(geometria, propriedades) de cada peca de um TEXT, com o fator de
    ajuste: o tamanho da letra e o ponto, ja corrigido para o QGIS pintar o
    texto na altura em que o AutoCAD pinta (ver textos_cad.correcao_vertical)."""
    altura_qgis = ajuste["altura"] * ajuste["fator"]
    angulo = math.radians(ajuste["angulo"])
    ux, uy = math.cos(angulo), math.sin(angulo)
    subir = textos_cad.correcao_vertical(ajuste["vertical"], False, altura_qgis)
    saida = []
    for peca in ajuste["pecas"]:
        d = peca["deslocamento"] or 0.0
        px, py = ajuste["x"] + ux * d - uy * subir, ajuste["y"] + uy * d + ux * subir
        peca["props"]["txt_tam"] = round(textos_cad.tamanho_qgis(altura_qgis), 6)
        saida.append(({"type": "Point",
                       "coordinates": (px, py) if ajuste["z"] is None else (px, py, ajuste["z"])},
                      peca["props"]))
    return saida


def _ajustar_textos(ajustes, transformador):
    """Acerta o tamanho da letra dos TEXT de fonte conhecida. Devolve quantos.

    O QGIS nao comprime letra, e a Arial raramente tem a largura da fonte do
    AutoCAD. Para cada texto:

      1. Quanto ele pode crescer: ate FOLGA_LARGURA alem da largura que tem
         no AutoCAD, como os demais (ver _encolher) -- mas agora medida na
         fonte de verdade, inclusive na simplex e na romans.
      2. Se houver outro texto logo adiante na mesma linha, nao passa de
         FRACAO_DO_VAO do vao entre os dois. Foi o que faltou no carimbo do
         LOTEAMENTO: o "MERIDIANO CENTRAL" (simplex a 83%) saia 14% mais
         largo que no AutoCAD e entrava no 45, que ocupa o meio do vao.
      3. Textos da mesma fonte, fator de largura e altura saem todos com a
         letra do mais apertado deles: no AutoCAD as linhas de um carimbo tem
         a mesma altura, e no QGIS tambem.

    Os textos de fonte desconhecida ficam com o tamanho que ja tinham e
    contam so como vizinhos. Os pontos sao recalculados e reprojetados.
    """
    if not any(a["ajustavel"] for a in ajustes):
        return 0
    linhas = {}
    for a in ajustes:
        angulo = math.radians(a["angulo"])
        ux, uy = math.cos(angulo), math.sin(angulo)
        h = a["altura"]
        a["_u"] = a["x"] * ux + a["y"] * uy
        base = -a["x"] * uy + a["y"] * ux + _BASE_CAD.get(a["vertical"], 0.0) * h
        chave = int(round((a["angulo"] % 360.0) * 2.0))      # meio grau
        for peca in a["pecas"]:
            if peca["tinta_cad"] is not None:
                t0, t1 = peca["tinta_cad"]
            else:
                b, c0, c1 = peca["qgis"]
                t0, t1 = b + c0 * a["fator"], b + c1 * a["fator"]
            linhas.setdefault(chave, []).append((base, h, a["_u"] + t0, a["_u"] + t1, a, peca))

    for itens in linhas.values():
        itens.sort(key=lambda item: item[0])
        bases = [item[0] for item in itens]
        h_max = max(item[1] for item in itens)
        for base, h, t0, t1, a, peca in itens:
            if not a["ajustavel"]:
                continue
            direita = esquerda = None
            perto = 0.05 * h
            for base2, h2, s0, s1, _a2, peca2 in itens[bisect.bisect_left(bases, base - h_max):
                                                       bisect.bisect_right(bases, base + h_max)]:
                if peca2 is peca or min(base + h, base2 + h2) - max(base, base2) < 0.5 * min(h, h2):
                    continue                          # ele mesmo, ou outra linha
                if s0 >= t1 - perto:
                    direita = s0 if direita is None else min(direita, s0)
                elif s1 <= t0 + perto:
                    esquerda = s1 if esquerda is None else max(esquerda, s1)
            b, c0, c1 = peca["qgis"]
            if direita is not None and c1 > 0:
                limite = t1 + FRACAO_DO_VAO * max(0.0, direita - t1)
                a["fator"] = min(a["fator"], (limite - a["_u"] - b) / c1)
            if esquerda is not None and c0 < 0:
                limite = t0 - FRACAO_DO_VAO * max(0.0, t0 - esquerda)
                a["fator"] = min(a["fator"], (a["_u"] + b - limite) / -c0)

    grupos = {}
    for a in ajustes:
        if a["ajustavel"]:
            a["fator"] = max(a["fator"], 0.5 * min(1.0, a["exato"]))
            grupos[a["grupo"]] = min(grupos.get(a["grupo"], 1.0), a["fator"])
    for a in ajustes:
        if not a["ajustavel"]:
            continue
        a["fator"] = grupos[a["grupo"]]
        for (geom, _props), peca in zip(_colocar(a), a["pecas"]):
            if peca.get("feicao") is not None:
                peca["feicao"]["geometry"] = _geometria_reprojetada(geom, transformador)
    return sum(1 for a in ajustes if a["ajustavel"])


def _acrescentar_hachuras(grupos, hachuras, transformador, separar_por_camada, ocultas,
                          saida_de=None):
    """Poe nos grupos as hachuras lidas pelo ezdxf. Devolve quantas tem padrao.

    Solida vira poligono preenchido (camada _Hachura). Com padrao, vira as
    linhas do padrao (camada _Textura), uma feicao por hachura. A que tem
    padrao fino demais para desenhar sai como poligono translucido. As de
    camada desligada ou congelada entram em `ocultas`, como as do GDAL.
    """
    com_padrao = 0
    for h in hachuras:
        camada_cad = h["camada"] if separar_por_camada else ""
        if camada_cad and saida_de:
            camada_cad = saida_de(camada_cad, dxf_estilo.para_hex(h["cor"]))
        props = {"Layer": h["camada"], "SubClasses": "AcDbEntity:AcDbHatch",
                 "Linetype": None, "EntityHandle": h["handle"], "Text": None,
                 CAMPO_COR: dxf_estilo.para_hex(h["cor"]), CAMPO_HACHURA: h["padrao"]}
        if h["tipo"] == "padrao":
            geom = {"type": "MultiLineString", "coordinates": h["linhas"]}
            pecas = [((camada_cad, "MultiLineString", "Textura"), geom, props)]
            com_padrao += 1
        else:
            pecas = [((camada_cad, "Polygon", "Hachura"),
                      {"type": "Polygon", "coordinates": aneis}, dict(props))
                     for aneis in h["poligonos"]]
        for chave, geom, p in pecas:
            feicao = {"type": "Feature", "properties": p,
                      "geometry": _geometria_reprojetada(geom, transformador)}
            grupos.setdefault(chave, []).append(feicao)
            if h.get("oculta"):
                ocultas.add(id(feicao))
    return com_padrao


def _caixa_do_texto(feicao):
    """Cantos do retangulo que o texto ocupa, ja girado, para o enquadramento."""
    import math
    props = feicao["properties"]
    x, y = feicao["geometry"]["coordinates"][:2]
    tamanho = props.get("txt_tam") or 0.0
    if not tamanho:
        return [(x, y)]
    altura_cad = tamanho * textos_cad.CAP_ARIAL
    linhas = str(props.get("Text") or "").split("\n")
    largura = max(textos_cad.largura_texto(l, altura_cad) for l in linhas)
    altura = tamanho * textos_cad.LINHA_ARIAL * len(linhas)
    x0 = {"Left": 0.0, "Center": -largura / 2, "Right": -largura}[props.get("txt_h") or "Left"]
    y0 = {"Top": -altura, "Half": -altura / 2, "Bottom": 0.0,
          "Base": -tamanho * 0.21}[props.get("txt_v") or "Base"]
    ang = math.radians(props.get("txt_ang") or 0.0)
    cos, sen = math.cos(ang), math.sin(ang)
    return [(x + dx * cos - dy * sen, y + dx * sen + dy * cos)
            for dx, dy in ((x0, y0), (x0 + largura, y0), (x0, y0 + altura),
                           (x0 + largura, y0 + altura))]


def cad_para_qgis(entrada, saida, epsg_origem, formato="GPKG", epsg_destino=None,
                  separar_por_camada=True, poli_fechada_como_poligono=False,
                  gerar_projeto=True, incluir_imagens=True, camadas=None,
                  descartar_fora_da_caixa=None, dxf_pronto=None, cores=None,
                  separar_por_cor=None, sem_textos_e_hachuras=False,
                  feicoes_escolhidas=None, registrar=print):
    """Converte um DXF/DWG em GPKG, Shapefile ou GeoJSON.

    A saida e separada por camada do AutoCAD (opcional) e por tipo: pontos,
    linhas, poligonos, hachuras e textos viram camadas diferentes no QGIS.

    Com `gerar_projeto`, grava tambem um .qgs ao lado, ja apontando para os
    dados e reproduzindo a aparencia do desenho -- ver qgis_project.py.

    `camadas` e o conjunto de camadas do AutoCAD a converter (None = todas):
    o que esta em outra camada nao entra, seja linha, ponto, texto, hachura ou
    imagem. `descartar_fora_da_caixa` e uma caixa (xmin, ymin, xmax, ymax) nas
    coordenadas do desenho: a feicao com todos os vertices fora dela fica de
    fora (ver fora_da_area.py). `dxf_pronto` e um DXF ja convertido do .dwg, que
    evita chamar o ODA de novo (e e de quem o passou: nao e apagado aqui). Sem ele,
    o .dwg passa pelo ODA numa pasta do TEMP, apagada no fim, de certo ou nao.

    `cores` filtra por cor DENTRO das camadas: {camada: {"#rrggbb", ...}} deixa em cada
    camada listada so as feicoes dessas cores (camada que nao esta no dicionario leva
    todas). `separar_por_cor` e o conjunto das camadas cuja saida se divide por cor: cada
    cor vira uma camada de saida, de nome "<camada>_<cor>".

    `sem_textos_e_hachuras` deixa de fora os textos e as hachuras: juntando por tipo, o
    resultado fica so com pontos, linhas e areas (textos e hachuras viriam como arquivos
    extras).

    `feicoes_escolhidas` sao ids de feicao do GDAL (dxf_estilo.id_da_feicao) escolhidas uma a
    uma, como as linhas e os textos que se clica no desenho. Elas entram alem das `camadas` e
    passam por cima do filtro de camadas e do de cor (as hachuras so entram pela camada). Os
    ids so servem para o mesmo DXF que a previa leu.
    """
    separar_por_cor = set(separar_por_cor or ())
    escolhidas = {int(f) for f in (feicoes_escolhidas or ())}
    if cores is not None:
        cores = {camada: set(lista) for camada, lista in cores.items()}
    if camadas is not None:
        camadas = set(camadas)
        if not camadas and not escolhidas:
            raise ErroConversao("Nenhuma camada foi escolhida. Marque ao menos uma "
                                "camada para converter.")
    copia_do_dwg = None
    if not dxf_pronto and os.path.splitext(entrada)[1].lower() == ".dwg":
        copia_do_dwg = dwg.dwg_para_dxf(entrada, registrar)
    try:
        return _converter_dxf(
            entrada, copia_do_dwg or dxf_pronto or entrada, saida, epsg_origem, formato,
            epsg_destino, separar_por_camada, poli_fechada_como_poligono, gerar_projeto,
            incluir_imagens, camadas, descartar_fora_da_caixa, cores, separar_por_cor,
            sem_textos_e_hachuras, escolhidas, registrar)
    finally:
        # a copia do desenho do cliente que o ODA fez no TEMP (a do painel, nao: e dele)
        if copia_do_dwg:
            dwg.apagar_temporario(copia_do_dwg)


def _converter_dxf(entrada, caminho_dxf, saida, epsg_origem, formato, epsg_destino,
                   separar_por_camada, poli_fechada_como_poligono, gerar_projeto,
                   incluir_imagens, camadas, descartar_fora_da_caixa, cores, separar_por_cor,
                   sem_textos_e_hachuras, escolhidas, registrar):
    """O resto de cad_para_qgis, com o DXF na mao (`caminho_dxf`). `entrada` e o arquivo que a
    pessoa escolheu (.dxf ou .dwg): as imagens do desenho se procuram junto dele."""
    epsg_destino = int(epsg_destino or epsg_origem)
    transformador = _transformador(epsg_origem, epsg_destino)
    if transformador:
        registrar("Reprojetando de EPSG:%s para EPSG:%s" % (epsg_origem, epsg_destino))

    # o que o GDAL nao entrega: largura dos quadros de MTEXT e as imagens
    extras = dxf_extras.ler(caminho_dxf)
    if camadas is not None:
        extras["imagens"] = [i for i in extras["imagens"] if i.get("camada") in camadas]
    fora_da_caixa = 0
    sem_texto_hachura = 0            # textos e hachuras deixados de fora a pedido

    def saida_de(camada, hex_cor):
        """O nome da camada de saida: com a cor, se a camada foi separada por cor."""
        if camada in separar_por_cor:
            return "%s_%s" % (camada, dxf_estilo.nome_da_cor(hex_cor).lstrip("#"))
        return camada
    # e o que ele entrega errado: hachuras e texto formatado (ver cad_ezdxf.py)
    desenho = cad_ezdxf.ler(caminho_dxf, registrar)
    indice_mtext = cad_ezdxf.IndiceMtext(desenho["mtexts"]) if desenho else None
    # A cor de cada hachura vem do ezdxf (que le as hachuras do jeito certo): o GDAL erra
    # a de algumas, e a lista de camadas agrupa por cor.
    cor_da_hachura = {str(h["handle"]).upper(): dxf_estilo.para_hex(h["cor"])
                      for h in (desenho["hachuras"] if desenho else ())}

    grupos = {}
    grupos_papel = {}     # o que esta no espaco de papel (a folha de impressao)
    com_html = set()      # camadas de texto que precisam de rotulo em HTML
    ignoradas = 0
    defpoints = 0
    # Feicoes de camada desligada ou congelada no AutoCAD (pelo id): vao para
    # o QGIS, mas em camadas desmarcadas, e nao contam no enquadramento.
    ocultas = set()

    opcoes = {"DXF_CLOSED_LINE_AS_POLYGON": "TRUE" if poli_fechada_como_poligono else "FALSE"}
    # Cor de cada camada na tabela LAYER. Serve de reserva quando o GDAL nao
    # da a cor -- e para as camadas desligadas, que o AutoCAD grava com a cor
    # negativa: o GDAL nao a resolve e entrega preto transparente.
    cores_tabela = dxf_estilo.ler_cores_das_camadas(caminho_dxf)
    # Em que ordem o AutoCAD desenha cada entidade (pelo id da feicao): quem
    # vem depois fica por cima. Ver _ordem_das_linhas.
    chaves_desenho = dxf_estilo.ordem_de_desenho(caminho_dxf)
    posicoes = {}
    # Cota das splines (curvas de nivel): o GDAL as entrega sem Z.
    cotas_splines = dxf_estilo.cotas_das_splines(caminho_dxf)
    # A fonte de cada TEXT (o GDAL diz "Arial" para as de traco) e o que e
    # preciso para acertar o tamanho da letra deles no fim (_ajustar_textos).
    fontes_textos = dxf_estilo.fontes_dos_textos(caminho_dxf)
    ajustes = []
    with dxf_estilo.abrir_entidades(caminho_dxf, opcoes_extra=opcoes) as (origem, tem_estilo):
        cores_camada = {}
        if not tem_estilo:
            # Reserva: sem a style string do OGR so da para saber a cor da
            # camada, entao entidades pintadas a mao saem com a cor errada.
            cores_camada = cores_tabela
            registrar("Aviso: nao consegui ler a cor entidade a entidade; "
                      "usando a cor de cada camada.")

        for n_feicao, feicao in enumerate(origem):
            bruta = feicao.get("geometry")
            if bruta is None:
                ignoradas += 1
                continue
            props = {campo: feicao["properties"].get(campo) for campo in CAMPOS_DXF}
            camada_cad = props.get("Layer") or "0"
            escolhida = bool(escolhidas) and (
                dxf_estilo.id_da_feicao(feicao, n_feicao) in escolhidas)
            if camadas is not None and camada_cad not in camadas and not escolhida:
                continue
            if "AcDbSpline" in (props.get("SubClasses") or ""):
                bruta = _com_cota_da_spline(
                    bruta, cotas_splines.get((props.get("EntityHandle") or "").upper()))
            # O que esta no espaco de papel (a folha da aba Layout) vai para
            # um monte separado; decide-se no fim se entra (ver mais abaixo).
            destino = grupos_papel if feicao["properties"].get("PaperSpace") else grupos

            # A cor sai da style string, que o GDAL ja resolveu: ByLayer, cor
            # propria da entidade, RGB de 24 bits ou heranca de bloco.
            aparencia = dxf_estilo.analisar_estilo(feicao["properties"].get("estilo"))
            cor = aparencia["cor"] or cores_camada.get(camada_cad) or (0, 0, 0)
            if aparencia["oculta"] and cor == (0, 0, 0):
                cor = cores_tabela.get(camada_cad) or cor
            props[CAMPO_COR] = dxf_estilo.para_hex(cor)
            # Pintado vem de dois tipos de entidade: HATCH e SOLID/TRACE (o
            # triangulo cheio das pontas de seta de cota, por exemplo). O ezdxf
            # cuida so das HATCH; um SOLID descartado aqui sumia do desenho --
            # foi assim que as cotas perderam as pontas de seta.
            eh_hatch = "AcDbHatch" in (props.get("SubClasses") or "")
            eh_hachura = eh_hatch or aparencia["hachura"]
            if eh_hatch:
                props[CAMPO_COR] = cor_da_hachura.get(
                    (props.get("EntityHandle") or "").upper(), props[CAMPO_COR])
            if (not escolhida and cores is not None and camada_cad in cores
                    and props[CAMPO_COR] not in cores[camada_cad]):
                continue
            if (eh_hatch and desenho is not None
                    and (props.get("EntityHandle") or "").upper() not in desenho["falhas"]):
                continue      # quem cuida das hachuras e o ezdxf
            if sem_textos_e_hachuras and eh_hachura:
                sem_texto_hachura += 1
                continue
            if camada_cad.lower() == "defpoints" and _tipo_base(bruta) == "Point":
                # Pontos de definicao de cota: o AutoCAD os poe na camada
                # Defpoints para montar a cota e nunca os imprime. No QGIS
                # viravam bolinhas nos cantos das cotas.
                defpoints += 1
                continue

            for geom in _explodir(bruta):
                if not geom.get("coordinates"):
                    ignoradas += 1
                    continue
                if (descartar_fora_da_caixa
                        and fora_da_area.todos_fora(geom["coordinates"], descartar_fora_da_caixa)):
                    fora_da_caixa += 1
                    continue
                tipo = _tipo_base(geom)
                p = dict(props)
                if tipo == "Point" and (aparencia["rotulo"] or p.get("Text")):
                    if sem_textos_e_hachuras:
                        sem_texto_hachura += 1
                        continue
                    # Texto do desenho. O ponto que o GDAL entrega nem sempre e
                    # onde o texto se ancora; _preparar_texto corrige, e separa
                    # as linhas de um MTEXT.
                    fonte_cad = (None if "MText" in (p.get("SubClasses") or "") else
                                 fontes_textos.achar(p.get("EntityHandle"), p.get("Text")))
                    linhas, formatado, ajuste = _preparar_texto(
                        geom, p, aparencia, extras["mtext"], indice_mtext, fonte_cad)
                    if formatado:
                        com_html.add(saida_de(camada_cad, props[CAMPO_COR])
                                     if separar_por_camada else "")
                    chave = (saida_de(camada_cad, props[CAMPO_COR]) if separar_por_camada else "",
                             "Point", "Texto")
                    for indice, (geom_linha, p_linha) in enumerate(linhas):
                        feicao = {"type": "Feature", "properties": p_linha,
                                  "geometry": _geometria_reprojetada(geom_linha, transformador)}
                        destino.setdefault(chave, []).append(feicao)
                        if aparencia["oculta"]:
                            ocultas.add(id(feicao))
                        if ajuste is not None:
                            ajuste["pecas"][indice]["feicao"] = feicao
                    if ajuste is not None:
                        ajustes.append(ajuste)
                    continue
                elif (poli_fechada_como_poligono and tipo == "LineString"
                      and "Polyline" in (p.get("SubClasses") or "")
                      and _fechada(geom["coordinates"])):
                    # O GDAL embutido (3.9) ignora DXF_CLOSED_LINE_AS_POLYGON,
                    # entao a conversao e feita aqui. Serve para calcular area.
                    geom = {"type": "Polygon", "coordinates": [geom["coordinates"]]}
                    tipo = subtipo = "Polygon"
                elif tipo == "Polygon" and eh_hachura:
                    # O GDAL poe o nome do padrao da hachura no campo Text.
                    # Nao e texto do desenho: vai para um campo proprio.
                    p[CAMPO_HACHURA] = (p.get("Text") or "SOLID").upper()
                    p["Text"] = None
                    subtipo = "Hachura"
                else:
                    subtipo = tipo
                geom = _geometria_reprojetada(geom, transformador)
                chave = (saida_de(camada_cad, props[CAMPO_COR]) if separar_por_camada else "",
                         tipo, subtipo)
                feicao = {"type": "Feature", "geometry": geom, "properties": p}
                destino.setdefault(chave, []).append(feicao)
                if aparencia["oculta"]:
                    ocultas.add(id(feicao))
                posicoes[id(feicao)] = _chave_de_desenho(p.get("EntityHandle"), chaves_desenho)

    try:
        _ajustar_textos(ajustes, transformador)
    except Exception as erro:          # os textos ficam como ja estavam
        registrar("Aviso: nao consegui acertar o tamanho de alguns textos (%s)." % erro)

    if desenho is not None:
        hachuras = desenho["hachuras"]
        if camadas is not None:
            hachuras = [h for h in hachuras if h["camada"] in camadas]
        if sem_textos_e_hachuras:
            sem_texto_hachura += len(hachuras)
            hachuras = []
        if cores is not None:
            hachuras = [h for h in hachuras if h["camada"] not in cores
                        or dxf_estilo.para_hex(h["cor"]) in cores[h["camada"]]]
        if descartar_fora_da_caixa:
            dentro = [h for h in hachuras if not fora_da_area.todos_fora(
                h.get("linhas") or h.get("poligonos"), descartar_fora_da_caixa)]
            fora_da_caixa += len(hachuras) - len(dentro)
            hachuras = dentro
        texturas = _acrescentar_hachuras(grupos, hachuras, transformador,
                                         separar_por_camada, ocultas,
                                         saida_de=saida_de)
        if texturas:
            registrar("%d hachuras com padrao desenhadas linha a linha." % texturas)

    # O espaco de papel e a folha de impressao (a aba Layout): moldura,
    # carimbo, logotipo, com coordenadas de papel que nada tem a ver com as do
    # mapa. Na aba Model, que e o desenho, ele nao aparece. O GDAL o mistura
    # com o resto: no Desm_Ext.Condominio a folha ia parar perto da origem, a
    # 7.000 km do mapa, e o projeto abria enquadrando as duas coisas. Fica de
    # fora -- a nao ser que o desenho so tenha espaco de papel.
    if grupos_papel:
        if grupos:
            registrar("%d entidades da folha de impressao (espaco de papel, a aba Layout "
                      "do AutoCAD) ficaram de fora: na aba Model, que e o desenho, elas "
                      "nao aparecem." % sum(len(v) for v in grupos_papel.values()))
        else:
            for chave, feicoes in grupos_papel.items():
                grupos.setdefault(chave, []).extend(feicoes)

    if not grupos and not extras["imagens"]:
        raise ErroConversao(
            "Nenhuma geometria foi encontrada em '%s'.\n\n"
            "Causas comuns: o desenho esta vazio, so tem objetos que o "
            "programa nao le, ou o DXF foi salvo em um formato muito antigo."
            % os.path.basename(entrada))

    # Camada desligada ou congelada no AutoCAD vem para o QGIS desmarcada: os
    # dados estao la, mas o desenho fica como o AutoCAD mostra. Sem isso, os
    # 1.038 pontos escondidos do Desm_Ext.Condominio apareciam, e o mapa
    # abria enquadrando 3.700 km por causa das coordenadas absurdas deles.
    # Escondidas misturadas com visiveis no mesmo grupo (entidade de um bloco
    # inserido em camada congelada) ganham um grupo proprio.
    for chave in list(grupos):
        feicoes = grupos[chave]
        escondidas = [f for f in feicoes if id(f) in ocultas]
        # Juntando por tipo (um arquivo de pontos, um de linhas...), as desligadas ficam
        # nos mesmos arquivos: separar viraria arquivos "oculto_*" a mais.
        if separar_por_camada and escondidas and len(escondidas) < len(feicoes):
            grupos[chave] = [f for f in feicoes if id(f) not in ocultas]
            _c, _t, _s = chave
            grupos.setdefault(((_c + "_" if _c else "") + "oculto", _t, _s), []).extend(escondidas)
    grupos_ocultos = {chave for chave, feicoes in grupos.items()
                      if all(id(f) in ocultas for f in feicoes)}

    total = sum(len(v) for v in grupos.values())
    distintas = {f["properties"][CAMPO_COR] for g in grupos.values() for f in g}
    registrar("%d feicoes em %d camadas, %d cores distintas."
              % (total, len(grupos), len(distintas)))
    if grupos_ocultos:
        registrar("%d camadas estavam desligadas ou congeladas no AutoCAD: no QGIS vem "
                  "desmarcadas (marque a caixinha para ver)." % len(grupos_ocultos))

    # O enquadramento inicial so conta o que aparece (se tudo estiver
    # escondido, conta tudo).
    so_visiveis = len(grupos_ocultos) < len(grupos)
    caixa = [float("inf"), float("inf"), float("-inf"), float("-inf")]
    for chave, feicoes in grupos.items():
        if so_visiveis and chave in grupos_ocultos:
            continue
        subtipo = chave[2]
        for feicao in feicoes:
            if subtipo == "Texto":
                # O texto ocupa mais que o ponto que o ancora; sem contar isso,
                # um quadro de legenda abre cortado.
                _estender(caixa, _caixa_do_texto(feicao))
            else:
                _estender(caixa, feicao["geometry"]["coordinates"])

    caminho_qgs = _caminho_projeto(saida, formato)
    # Quem o AutoCAD desenha depois fica por cima: entre as camadas de linha
    # (ver _ordem_das_linhas) e, dentro de cada camada, entre as feicoes -- o
    # QGIS as desenha na ordem em que estao gravadas.
    ordem_linhas = _ordem_das_linhas(grupos, posicoes)
    for feicoes in grupos.values():
        feicoes.sort(key=lambda f: posicoes.get(id(f), 0))
    gerados, camadas_projeto = _gravar_grupos(grupos, saida, formato,
                                              epsg_destino, registrar, ordem_linhas)

    # ---- imagens
    camadas_imagem = []
    if incluir_imagens and extras["imagens"]:
        camadas_imagem = _exportar_imagens(extras, entrada, caminho_dxf, caminho_qgs,
                                           epsg_origem, transformador, caixa, registrar,
                                           dxf_estilo.camadas_ocultas(caminho_dxf))
        gerados.extend(c["arquivo"] for c in camadas_imagem)

    extensao = tuple(caixa) if caixa[0] < caixa[2] else None

    projeto = None
    # Sem estilo, quem abre so os dados no QGIS ve uma cor sorteada. Shapefile e GeoJSON
    # sao um arquivo por camada e nenhum guarda estilo: cada um ganha um .qml ao lado,
    # que o QGIS aplica sozinho ao abrir o arquivo. No GPKG o estilo vai dentro, na
    # tabela layer_styles (qgis_project.gravar_estilos_no_gpkg). Os dois valem com ou
    # sem o .qgs, entao as cores de cada camada sao preparadas sempre.
    escreve_qml = formato != "GPKG"
    if camadas_projeto:
        com_texto = 0
        estilo_ponto = dxf_estilo.estilo_de_ponto(caminho_dxf)
        for camada in camadas_projeto:
            chave = camada.pop("chave")
            _c, _t, subtipo = chave
            # Cada camada leva a lista das cores que realmente ocorrem nela; o
            # projeto vira um renderizador categorizado, em vez de uma cor
            # unica que apagaria as diferencas dentro da camada.
            cores = []
            solidas = {}
            for feicao in grupos[chave]:
                valor = feicao["properties"][CAMPO_COR]
                if valor not in cores:
                    cores.append(valor)
                if subtipo == "Hachura":
                    solida = feicao["properties"].get(CAMPO_HACHURA) == "SOLID"
                    solidas.setdefault((valor, solida), None)
            camada["cores"] = cores
            camada["campo_cor"] = CAMPO_COR
            camada["oculta"] = chave in grupos_ocultos
            if subtipo == "Point":
                # como o AutoCAD desenha os pontos ($PDMODE, $PDSIZE)
                camada["ponto"] = estilo_ponto
            if subtipo == "Texto":
                camada["texto"] = True
                # rotulo em HTML so onde algum texto tem formatacao propria;
                # nas demais camadas o texto puro, que e mais simples e seguro
                camada["html"] = _c in com_html
                com_texto += 1
            elif subtipo == "Textura":
                camada["textura"] = True
            elif subtipo == "Hachura":
                camada["hachura"] = list(solidas)
                camada["campo_hachura"] = CAMPO_HACHURA
        if com_texto:
            registrar("Textos em %d camadas, na posicao, tamanho e rotacao do desenho."
                      % com_texto)

    if escreve_qml:
        pasta_dados = os.path.splitext(saida)[0]
        try:
            for camada in camadas_projeto:
                qgis_project.gerar_qml(os.path.join(pasta_dados, camada["nome"] + ".qml"), camada)
        except Exception as erro:
            # Como o projeto, o estilo e uma conveniencia: os dados ja estao salvos.
            registrar("Aviso: nao consegui gravar o estilo (.qml) ao lado dos dados (%s). "
                      "Os dados foram convertidos normalmente, mas o QGIS vai sortear as cores."
                      % erro)
    elif camadas_projeto:
        try:
            qgis_project.gravar_estilos_no_gpkg(saida, camadas_projeto)
            registrar("Cores do AutoCAD gravadas dentro do .gpkg: o QGIS as aplica ao abrir.")
        except Exception as erro:
            registrar("Aviso: nao consegui gravar as cores dentro do .gpkg (%s). "
                      "Os dados foram convertidos normalmente, mas o QGIS vai sortear as cores."
                      % erro)

    if gerar_projeto and (camadas_projeto or camadas_imagem):
        try:
            projeto = qgis_project.gerar_qgs(
                caminho_qgs, camadas_projeto + camadas_imagem, epsg_destino, extensao)
        except Exception as erro:
            # O projeto e uma conveniencia. Se falhar, os dados ja estao salvos
            # e o usuario ainda pode abri-los por Camada > Adicionar Camada.
            registrar("Aviso: nao consegui gerar o projeto .qgs (%s). "
                      "Os dados foram convertidos normalmente." % erro)
        if projeto:
            gerados.append(projeto)
            registrar("Projeto do QGIS criado: %s" % os.path.basename(projeto))
            registrar("  -> de dois cliques nesse arquivo para abrir tudo pronto.")

    if ignoradas:
        registrar("%d entidades sem geometria aproveitavel foram ignoradas."
                  % ignoradas)
    if defpoints:
        registrar("%d pontos de definicao de cota (camada Defpoints) ficaram de fora: "
                  "o AutoCAD tambem nao os imprime." % defpoints)
    if fora_da_caixa:
        registrar("%d feicoes longe do desenho (fora da area principal) ficaram de fora."
                  % fora_da_caixa)
    if sem_texto_hachura:
        registrar("%d textos e hachuras ficaram de fora, como pedido." % sem_texto_hachura)

    return {"arquivos": gerados, "feicoes": total, "projeto": projeto,
            "imagens": len(camadas_imagem),
            "grupos": sorted(_nome_grupo(k) for k in grupos)}


def _exportar_imagens(extras, entrada, caminho_dxf, caminho_qgs, epsg_origem,
                      transformador, caixa, registrar, escondidas=frozenset()):
    """Copia e georreferencia as imagens do desenho. Devolve as camadas raster.

    Imagem em camada desligada ou congelada (`escondidas`) vem desmarcada e
    nao entra no enquadramento."""
    pasta_qgs = os.path.dirname(os.path.abspath(caminho_qgs))
    base = os.path.splitext(os.path.basename(caminho_qgs))[0]
    pasta_img = os.path.join(pasta_qgs, base + "_imagens")
    # onde procurar: junto do desenho ORIGINAL (o .dwg), nao do DXF temporario
    pastas = [os.path.dirname(os.path.abspath(entrada)),
              os.path.dirname(os.path.abspath(caminho_dxf))]

    camadas = []
    faltando = []
    usados = set()
    for indice, imagem in enumerate(extras["imagens"], 1):
        gravado = extras["arquivos"].get(imagem["definicao"])
        arquivo = imagens_cad.localizar(gravado, pastas)
        if not arquivo:
            faltando.append(gravado or "(o desenho nao informa o arquivo)")
            continue
        nome = _nome_seguro(os.path.splitext(os.path.basename(arquivo))[0])
        if nome in usados:
            nome = "%s_%d" % (nome, indice)
        usados.add(nome)
        try:
            copia, ext_img = imagens_cad.exportar(imagem, arquivo, pasta_img,
                                                  epsg_origem, nome)
        except (OSError, ValueError) as erro:
            registrar("Aviso: nao consegui copiar a imagem %s (%s)."
                      % (os.path.basename(arquivo), erro))
            continue
        cantos = [(ext_img[0], ext_img[1]), (ext_img[2], ext_img[3])]
        if transformador:
            cantos = _reprojetar(cantos, transformador)
        oculta = imagem.get("camada") in escondidas
        if not oculta:
            _estender(caixa, cantos)
        camadas.append({
            "raster": True, "nome": "Imagem_%s" % nome, "epsg": int(epsg_origem),
            "fonte": "./" + os.path.relpath(copia, pasta_qgs).replace("\\", "/"),
            "arquivo": copia, "oculta": oculta})
        registrar("Imagem incluida: %s" % os.path.basename(arquivo))

    for gravado in faltando:
        registrar("Imagem NAO encontrada: %s\n"
                  "  -> ela ficou de fora. Coloque o arquivo na mesma pasta do "
                  "desenho e converta de novo." % gravado)
    return camadas


def _caminho_projeto(saida, formato):
    """Onde o .qgs fica: ao lado do GPKG, ou dentro da pasta de SHP/GeoJSON."""
    if formato == "GPKG":
        return os.path.splitext(saida)[0] + ".qgs"
    pasta = os.path.splitext(saida)[0]
    return os.path.join(pasta, os.path.basename(pasta) + ".qgs")


def _nome_seguro(texto):
    seguro = dxfio.sem_acento(str(texto))
    seguro = "".join(c if (c.isalnum() or c == "_") else "_" for c in seguro)
    return seguro.strip("_")[:50] or "camada"


def _nome_grupo(chave):
    """Nome da camada de saida: <camada do AutoCAD>_<tipo>."""
    camada_cad, _tipo, subtipo = chave
    return _nome_seguro("%s_%s" % (camada_cad, subtipo) if camada_cad else subtipo)


def _esquema(chave):
    """Campos de cada camada de saida. Texto e hachura tem campos a mais."""
    _c, tipo, subtipo = chave
    campos = {campo: "str" for campo in CAMPOS_SAIDA}
    if subtipo == "Texto":
        campos.update(CAMPOS_TEXTO)
    elif subtipo in ("Hachura", "Textura"):
        campos[CAMPO_HACHURA] = "str"
    return {"geometry": tipo, "properties": campos}


def _ordenados(grupos, ordem=None):
    """Os grupos na ordem do painel do QGIS (o primeiro fica por cima): por
    tipo -- texto, pontos, linhas, texturas, areas -- e, dentro do tipo, pela
    `ordem` dada (a das linhas, ver _ordem_das_linhas) ou pelo nome."""
    ordem = ordem or {}
    return sorted(grupos.items(),
                  key=lambda item: (ORDEM.get(item[0][2], 9), ordem.get(item[0], 0),
                                    _nome_grupo(item[0])))


def _chave_de_desenho(handle, chaves_desenho):
    """Posicao de uma entidade na ordem de desenho do AutoCAD (ver
    dxf_estilo.ordem_de_desenho). Sem handle: zero, desenhada primeiro."""
    if not handle:
        return 0
    handle = str(handle).upper()
    try:
        return chaves_desenho.get(handle, int(handle, 16))
    except ValueError:
        return 0


def _ordem_das_linhas(grupos, posicoes, limite=2000000):
    """Ordem das camadas de linha no QGIS: {chave do grupo: posicao, 0 = por cima}.

    No QGIS cada camada do AutoCAD vira uma camada, e a de cima no painel
    cobre as de baixo; no AutoCAD cobre quem e desenhado depois. Quando duas
    linhas de cores diferentes passam uma por cima da outra, isso decide a
    cor que se ve: no Desm_Ext.Condominio o contorno dos lotes existe em roxo
    na camada "0" e em verde na "terreno", desenhada depois. O AutoCAD mostra
    verde; o QGIS, com as camadas em ordem alfabetica, mostrava roxo (e uma
    linha azul virava roxa do mesmo jeito).

    Cada trecho em que duas camadas se sobrepoem com cores diferentes vale um
    voto, do tamanho do trecho, para a que o AutoCAD desenha por cima; as
    camadas seguem os votos (o mais forte decide quando eles se contradizem).
    Camada que nao disputa trecho nenhum fica na ordem alfabetica.
    """
    import heapq

    chaves = sorted((c for c in grupos if c[2] == "LineString"), key=_nome_grupo)
    padrao = {c: i for i, c in enumerate(chaves)}
    if len(chaves) < 2:
        return padrao
    trechos = []          # (grupo, cor, posicao no desenho, x1, y1, x2, y2)
    for g, chave in enumerate(chaves):
        for f in grupos[chave]:
            cor = f["properties"].get(CAMPO_COR)
            pos = posicoes.get(id(f), 0)
            geom = f["geometry"]
            partes = ([geom["coordinates"]] if geom["type"] == "LineString"
                      else geom["coordinates"])
            for parte in partes:
                for a, b in zip(parte, parte[1:]):
                    if a[0] != b[0] or a[1] != b[1]:
                        trechos.append((g, cor, pos, a[0], a[1], b[0], b[1]))
    if len(trechos) > limite:
        return padrao                          # desenho enorme: fica como estava
    xs = [t[3] for t in trechos] + [t[5] for t in trechos]
    ys = [t[4] for t in trechos] + [t[6] for t in trechos]
    diagonal = math.hypot(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    tol = max(diagonal * 2e-5, 1e-9)           # duas linhas "juntas"
    lado = max(diagonal / 512.0, tol * 20)     # celulas da grade de busca
    x0, y0 = min(xs), min(ys)

    celulas = {}
    for i, (_g, _c, _p, ax, ay, bx, by) in enumerate(trechos):
        for cx in range(int((min(ax, bx) - tol - x0) // lado), int((max(ax, bx) + tol - x0) // lado) + 1):
            for cy in range(int((min(ay, by) - tol - y0) // lado),
                            int((max(ay, by) + tol - y0) // lado) + 1):
                celulas.setdefault((cx, cy), []).append(i)

    votos = {}
    vistos = set()
    for indices in celulas.values():
        if len(indices) < 2:
            continue
        for n, i in enumerate(indices):
            gi, ci, pi, ax, ay, bx, by = trechos[i]
            comp = math.hypot(bx - ax, by - ay)
            ux, uy = (bx - ax) / comp, (by - ay) / comp
            for j in indices[n + 1:]:
                gj, cj, pj, cx_, cy_, dx_, dy_ = trechos[j]
                if gi == gj or ci == cj or pi == pj or (i, j) in vistos:
                    continue
                vistos.add((i, j))
                # as duas pontas do outro trecho em cima da reta deste?
                d1 = abs(-(cx_ - ax) * uy + (cy_ - ay) * ux)
                d2 = abs(-(dx_ - ax) * uy + (dy_ - ay) * ux)
                if d1 > tol or d2 > tol:
                    continue
                t1 = (cx_ - ax) * ux + (cy_ - ay) * uy
                t2 = (dx_ - ax) * ux + (dy_ - ay) * uy
                junto = min(comp, max(t1, t2)) - max(0.0, min(t1, t2))
                if junto > tol:
                    cima, baixo = (gi, gj) if pi > pj else (gj, gi)
                    votos[(cima, baixo)] = votos.get((cima, baixo), 0.0) + junto

    # saldo de cada par; os mais fortes entram primeiro, sem criar ciclo
    acima = {g: set() for g in range(len(chaves))}

    def alcanca(origem, destino):
        pilha, visto = [origem], {origem}
        while pilha:
            g = pilha.pop()
            if g == destino:
                return True
            for h in acima[g] - visto:
                visto.add(h)
                pilha.append(h)
        return False

    saldos = sorted(((w - votos.get((b, a), 0.0), a, b) for (a, b), w in votos.items()),
                    reverse=True)
    for saldo, a, b in saldos:
        if saldo > 0 and not alcanca(b, a):
            acima[a].add(b)
    entrada = {g: 0 for g in acima}
    for g in acima:
        for h in acima[g]:
            entrada[h] += 1
    fila = [g for g in acima if entrada[g] == 0]
    heapq.heapify(fila)
    ordem = []
    while fila:
        g = heapq.heappop(fila)
        ordem.append(g)
        for h in acima[g]:
            entrada[h] -= 1
            if entrada[h] == 0:
                heapq.heappush(fila, h)
    return {chaves[g]: i for i, g in enumerate(ordem)}


def _gravar_grupos(grupos, saida, formato, epsg, registrar, ordem=None):
    """Grava as camadas e devolve (arquivos_gerados, camadas_para_o_projeto).

    As camadas saem na ordem de desenho (texto primeiro, hachura por ultimo),
    que e a ordem em que o projeto as coloca no painel do QGIS. Todas apontam
    para os dados por caminho relativo, entao a pasta inteira pode ser copiada
    para outro computador sem quebrar.
    """
    crs = CRS.from_epsg(int(epsg))
    gerados = []
    camadas_projeto = []

    if formato == "GPKG":
        # Um unico .gpkg com uma camada por grupo. Removemos antes para nao
        # misturar com o resultado de uma conversao anterior.
        os.makedirs(os.path.dirname(os.path.abspath(saida)), exist_ok=True)
        if os.path.exists(saida):
            os.remove(saida)
        for chave, feicoes in _ordenados(grupos, ordem):
            nome = _nome_grupo(chave)
            with fiona.open(saida, "w", driver="GPKG", layer=nome, crs=crs,
                            schema=_esquema(chave)) as destino:
                destino.writerecords(feicoes)
            registrar("  camada '%s': %d feicoes" % (nome, len(feicoes)))
            camadas_projeto.append(
                {"nome": nome, "geometria": chave[1], "chave": chave,
                 "fonte": "./%s|layername=%s" % (os.path.basename(saida), nome)})
        gerados.append(saida)

    elif formato == "ESRI Shapefile":
        # Um shapefile por grupo, dentro de uma pasta. O formato nao aceita
        # geometrias misturadas nem nomes de campo com mais de 10 caracteres.
        pasta = os.path.splitext(saida)[0]
        os.makedirs(pasta, exist_ok=True)
        for chave, feicoes in _ordenados(grupos, ordem):
            nome = _nome_grupo(chave)
            esquema = _esquema(chave)
            # texto no DBF tem no maximo 254 caracteres (o padrao do Fiona e 80)
            esquema["properties"] = {ABREVIACOES_SHP.get(k, k): ("str:254" if v == "str" else v)
                                     for k, v in esquema["properties"].items()}
            # A camada declarada 2D faz o driver jogar o Z fora: era assim que a
            # cota das curvas de nivel e dos pontos altimetricos se perdia. So
            # vira 3D onde alguma feicao tem cota (simbolo e texto ficam 2D).
            if any(_tem_cota(f["geometry"]["coordinates"]) for f in feicoes):
                esquema["geometry"] = "3D " + esquema["geometry"]
            destino_shp = os.path.join(pasta, nome + ".shp")
            with fiona.open(destino_shp, "w", driver="ESRI Shapefile", crs=crs,
                            encoding="utf-8", schema=esquema) as destino:
                for feicao in feicoes:
                    props = {ABREVIACOES_SHP.get(k, k): v
                             for k, v in feicao["properties"].items()}
                    if len(props.get("txt_html") or "") > 254:
                        # HTML cortado no meio quebraria o rotulo; sem a
                        # formatacao, pelo menos o texto aparece
                        props["txt_html"] = textos_cad.html_simples(props.get("Text"))[:254]
                    destino.write({"type": "Feature", "geometry": feicao["geometry"],
                                   "properties": props})
            gerados.append(destino_shp)
            camadas_projeto.append({"nome": nome, "geometria": chave[1],
                                    "chave": chave, "fonte": "./%s.shp" % nome})
            registrar("  %s.shp: %d feicoes" % (nome, len(feicoes)))

    else:   # GeoJSON
        pasta = os.path.splitext(saida)[0]
        os.makedirs(pasta, exist_ok=True)
        for chave, feicoes in _ordenados(grupos, ordem):
            nome = _nome_grupo(chave)
            destino_json = os.path.join(pasta, nome + ".geojson")
            with fiona.open(destino_json, "w", driver="GeoJSON", crs=crs,
                            schema=_esquema(chave)) as destino:
                destino.writerecords(feicoes)
            gerados.append(destino_json)
            camadas_projeto.append({"nome": nome, "geometria": chave[1],
                                    "chave": chave, "fonte": "./%s.geojson" % nome})
            registrar("  %s.geojson: %d feicoes" % (nome, len(feicoes)))

    return gerados, camadas_projeto
