# -*- coding: utf-8 -*-
"""
Gera um arquivo de projeto do QGIS (.qgs) apontando para os dados convertidos.

Por que isto existe: .qgs e .qgz NAO sao formatos de dados. Sao projetos --
guardam quais camadas estao abertas, as cores e o layout, e apontam para os
arquivos de dados, que ficam fora deles. Quem procura os dados no menu
"Projeto > Abrir Projeto" nao acha, porque o lugar certo e
"Camada > Adicionar Camada Vetorial".

Alem de abrir com dois cliques, o projeto reproduz a aparencia do desenho:
    - a cor de cada ENTIDADE vem da style string do OGR (ver dxf_estilo.py),
      senao o QGIS sorteia uma paleta e o mapa fica irreconhecivel;
    - hachuras saem preenchidas, e nao so com o contorno;
    - cada texto fica ancorado, alinhado, girado e dimensionado como no
      AutoCAD (ver textos_cad.py);
    - imagens raster do desenho entram como camadas de imagem
      georreferenciadas (ver imagens_cad.py).

As propriedades de simbolo sao escritas no formato <prop k= v=>, e nao no
<Option> mais novo. Os dois sao aceitos por qualquer QGIS 3.x -- o antigo
porque o QGIS precisa continuar abrindo projetos velhos -- e o antigo tambem
funciona nas versoes mais antigas, entao cobre mais gente.
"""

import datetime
import os
from xml.sax.saxutils import escape, quoteattr

import pyproj

# O QGIS chama as geometrias assim no arquivo de projeto -- "Line", nao "LineString".
GEOMETRIA_QGIS = {"Point": "Point", "LineString": "Line", "Polygon": "Polygon",
                  "MultiPoint": "Point", "MultiLineString": "Line",
                  "MultiPolygon": "Polygon"}

COR_PADRAO = (0, 0, 0)


def hex_para_rgb(texto):
    texto = str(texto).lstrip("#")[:6]
    try:
        return tuple(int(texto[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return COR_PADRAO


def para_hex(rgb):
    return "#%02x%02x%02x" % tuple(rgb)


def _rgba(cor, alfa=255):
    r, g, b = cor
    return "%d,%d,%d,%d" % (r, g, b, alfa)


def _bloco_srs(epsg):
    """Bloco <spatialrefsys>. O QGIS resolve o resto sozinho a partir do authid."""
    crs = pyproj.CRS.from_epsg(int(epsg))
    try:
        proj4 = crs.to_proj4() or ""
    except Exception:
        proj4 = ""
    return (
        '<spatialrefsys nativeFormat="Wkt">'
        "<wkt>%s</wkt>"
        "<proj4>%s</proj4>"
        "<srsid>0</srsid>"
        "<srid>%d</srid>"
        "<authid>EPSG:%d</authid>"
        "<description>%s</description>"
        "<projectionacronym></projectionacronym>"
        "<ellipsoidacronym></ellipsoidacronym>"
        "<geographicflag>%s</geographicflag>"
        "</spatialrefsys>"
    ) % (escape(crs.to_wkt()), escape(proj4), int(epsg), int(epsg),
         escape(crs.name), "true" if crs.is_geographic else "false")


def _id_camada(nome, indice):
    carimbo = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    limpo = "".join(c if c.isalnum() else "_" for c in nome)
    return "%s_%s_%d" % (limpo, carimbo, indice)


def _simbolo(geometria, cor, nome="0", espessura=0.26, ponto=None):
    """Simbolo de cor unica reproduzindo a cor da camada no AutoCAD.

    Poligonos ficam so com contorno: no CAD um poligono fechado e uma
    polilinha, nao uma area pintada. Preencher mudaria o desenho. Pontos
    seguem o estilo de ponto do desenho, quando ele vem (`ponto`).
    """
    tipo = GEOMETRIA_QGIS.get(geometria, "Line")
    if tipo == "Point" and ponto is not None:
        return _simbolo_ponto(cor, ponto, nome)
    if tipo == "Point":
        return (
            '<symbol type="marker" name="%s" alpha="1" clip_to_extent="1" force_rhr="0">'
            '<layer class="SimpleMarker" enabled="1" locked="0" pass="0">'
            '<prop k="name" v="circle"/>'
            '<prop k="color" v="%s"/>'
            '<prop k="outline_color" v="%s"/>'
            '<prop k="outline_width" v="0.2"/>'
            '<prop k="outline_width_unit" v="MM"/>'
            '<prop k="size" v="1.6"/>'
            '<prop k="size_unit" v="MM"/>'
            '<prop k="angle" v="0"/>'
            '<prop k="offset" v="0,0"/>'
            '<prop k="horizontal_anchor_point" v="1"/>'
            '<prop k="vertical_anchor_point" v="1"/>'
            '</layer></symbol>' % (nome, _rgba(cor), _rgba(cor))
        )
    if tipo == "Polygon":
        return (
            '<symbol type="fill" name="%s" alpha="1" clip_to_extent="1" force_rhr="0">'
            '<layer class="SimpleFill" enabled="1" locked="0" pass="0">'
            '<prop k="style" v="no"/>'
            '<prop k="color" v="%s"/>'
            '<prop k="outline_style" v="solid"/>'
            '<prop k="outline_color" v="%s"/>'
            '<prop k="outline_width" v="0.26"/>'
            '<prop k="outline_width_unit" v="MM"/>'
            '<prop k="joinstyle" v="bevel"/>'
            '<prop k="offset" v="0,0"/>'
            '</layer></symbol>' % (nome, _rgba(cor, 0), _rgba(cor))
        )
    return (
        '<symbol type="line" name="%s" alpha="1" clip_to_extent="1" force_rhr="0">'
        '<layer class="SimpleLine" enabled="1" locked="0" pass="0">'
        '<prop k="line_color" v="%s"/>'
        '<prop k="line_style" v="solid"/>'
        '<prop k="line_width" v="%s"/>'
        '<prop k="line_width_unit" v="MM"/>'
        '<prop k="capstyle" v="round"/>'
        '<prop k="joinstyle" v="round"/>'
        '<prop k="offset" v="0"/>'
        '</layer></symbol>' % (nome, _rgba(cor), espessura)
    )


# Altura da area de desenho do AutoCAD na tela, em mm, para os pontos de
# tamanho relativo a tela ($PDSIZE zero ou negativo): uma janela de ~160 mm.
AREA_DE_DESENHO_MM = 160.0


def _simbolo_ponto(cor, ponto, nome="0"):
    """O marcador do jeito que o AutoCAD desenha os pontos do desenho.

    `ponto` e ($PDMODE, $PDSIZE). As medidas sao as do AutoCAD (as mesmas que
    o ezdxf reproduz): circulo e quadrado com PDSIZE de lado, cruz e xis com o
    dobro -- os bracos saem para fora do circulo -- e o tracinho, meio PDSIZE
    para cima. PDSIZE positivo e em unidades do desenho; zero ou negativo e
    uma fracao da altura da tela (5%, ou a porcentagem dada), em milimetros.
    O ponto simples (modo 0) e um pingo: no AutoCAD, um pixel.
    """
    modo, tamanho = int(ponto[0]), float(ponto[1])
    if tamanho > 0:
        unidade, s = "MapUnit", tamanho
    else:
        unidade = "MM"
        s = AREA_DE_DESENHO_MM * (abs(tamanho) if tamanho < 0 else 5.0) / 100.0
    camadas = []
    base = modo & 7
    if base == 0:
        camadas.append(_marcador("circle", cor, 0.5, "MM", preenchido=True))
    elif base == 2:
        camadas.append(_marcador("cross", cor, 2 * s, unidade))
    elif base == 3:
        camadas.append(_marcador("cross2", cor, 2 * s, unidade))
    elif base == 4:
        # no QGIS a linha fica centrada no ponto; o AutoCAD a desenha para cima
        camadas.append(_marcador("line", cor, s / 2, unidade, deslocamento=(0, -s / 4)))
    if modo & 32:
        camadas.append(_marcador("circle", cor, s, unidade))
    if modo & 64:
        camadas.append(_marcador("square", cor, s, unidade))
    if not camadas:            # modo 1: o AutoCAD nao desenha nada
        camadas.append(_marcador("circle", cor, 0.5, "MM", ativo=False))
    return ('<symbol type="marker" name="%s" alpha="1" clip_to_extent="1" force_rhr="0">'
            '%s</symbol>' % (nome, "".join(camadas)))


def _marcador(forma, cor, tamanho, unidade, preenchido=False, deslocamento=(0, 0), ativo=True):
    """Uma camada de simbolo de marcador simples, so contorno (ou so miolo)."""
    return (
        '<layer class="SimpleMarker" enabled="%d" locked="0" pass="0">'
        '<prop k="name" v="%s"/>'
        '<prop k="color" v="%s"/>'
        '<prop k="outline_color" v="%s"/>'
        '<prop k="outline_style" v="%s"/>'
        '<prop k="outline_width" v="0.25"/>'
        '<prop k="outline_width_unit" v="MM"/>'
        '<prop k="size" v="%r"/>'
        '<prop k="size_unit" v="%s"/>'
        '<prop k="angle" v="0"/>'
        '<prop k="offset" v="%r,%r"/>'
        '<prop k="offset_unit" v="%s"/>'
        '<prop k="horizontal_anchor_point" v="1"/>'
        '<prop k="vertical_anchor_point" v="1"/>'
        '</layer>'
        % (1 if ativo else 0, forma, _rgba(cor, 255 if preenchido else 0), _rgba(cor),
           "no" if preenchido else "solid", float(tamanho), unidade,
           float(deslocamento[0]), float(deslocamento[1]), unidade))


def _simbolo_hachura(cor, solida, nome="0"):
    """Preenchimento de uma hachura do AutoCAD.

    Solida: cor cheia. Com padrao (ANSI31, AR-CONC...): a mesma cor
    semitransparente -- reproduzir o desenho exato do padrao dependeria da
    escala e do angulo de cada hachura, e uma aproximacao errada confunde
    mais do que uma tinta clara que diz "esta area e desta cor".

    O contorno fino na mesma cor evita as frestas brancas que aparecem entre
    duas hachuras vizinhas quando a borda e suavizada.
    """
    alfa = 255 if solida else 90
    return (
        '<symbol type="fill" name="%s" alpha="1" clip_to_extent="1" force_rhr="0">'
        '<layer class="SimpleFill" enabled="1" locked="0" pass="0">'
        '<prop k="style" v="solid"/>'
        '<prop k="color" v="%s"/>'
        '<prop k="outline_style" v="solid"/>'
        '<prop k="outline_color" v="%s"/>'
        '<prop k="outline_width" v="0"/>'
        '<prop k="outline_width_unit" v="MM"/>'
        '<prop k="joinstyle" v="miter"/>'
        '<prop k="offset" v="0,0"/>'
        '</layer></symbol>' % (nome, _rgba(cor, alfa), _rgba(cor, alfa)))


def _renderizador_categorizado(atributo, categorias):
    """`categorias` e uma lista de (valor, rotulo, xml_do_simbolo)."""
    itens = "".join(
        '<category value=%s symbol="%d" label=%s render="true"/>'
        % (quoteattr(valor), i, quoteattr(rotulo))
        for i, (valor, rotulo, _s) in enumerate(categorias))
    simbolos = "".join(s for _v, _r, s in categorias)
    return ('<renderer-v2 type="categorizedSymbol" attr=%s symbollevels="0" '
            'forceraster="0" enableorderby="0">'
            "<categories>%s</categories><symbols>%s</symbols>"
            "</renderer-v2>" % (quoteattr(atributo), itens, simbolos))


def _renderizador(camada):
    """Como a camada e desenhada.

    Uma camada do AutoCAD raramente tem uma cor so: o desenhista pinta
    entidades individualmente, e num mapa geologico cada cor significa uma
    litologia. Por isso, quando ha mais de uma cor, a camada sai com um
    renderizador CATEGORIZADO pelo campo da cor -- cada tom vira uma categoria
    com o seu proprio simbolo e aparece separado na legenda do QGIS.

    Camadas de texto usam "nullSymbol": nao desenham simbolo nenhum, so o
    rotulo. Sem isso o ponto de insercao de cada texto viraria uma bolinha
    sobre o proprio texto.
    """
    if camada.get("texto"):
        return '<renderer-v2 type="nullSymbol" symbollevels="0" forceraster="0"/>'

    campo_cor = camada.get("campo_cor") or "cor_cad"
    cores = [c for c in (camada.get("cores") or []) if c] or [para_hex(COR_PADRAO)]

    if camada.get("hachura") is not None:
        # a categoria combina cor e tipo: a mesma cor pode vir solida numa
        # hachura e com padrao em outra
        campo_hach = camada.get("campo_hachura") or "hachura"
        expressao = ('"%s" || CASE WHEN "%s" = \'SOLID\' THEN \'\' ELSE \' padrao\' END'
                     % (campo_cor, campo_hach))
        pares = camada["hachura"] or [(c, True) for c in cores]
        categorias = []
        for i, (valor, solida) in enumerate(pares):
            chave = valor if solida else valor + " padrao"
            categorias.append((chave, chave,
                               _simbolo_hachura(hex_para_rgb(valor), solida, str(i))))
        return _renderizador_categorizado(expressao, categorias)

    # as linhas do padrao de uma hachura sao finas, como no AutoCAD
    espessura = 0.13 if camada.get("textura") else 0.26
    geometria = "LineString" if camada.get("textura") else camada["geometria"]
    ponto = camada.get("ponto")
    if len(cores) == 1:
        return ('<renderer-v2 type="singleSymbol" symbollevels="0" forceraster="0" '
                'enableorderby="0"><symbols>%s</symbols></renderer-v2>'
                % _simbolo(geometria, hex_para_rgb(cores[0]), "0", espessura, ponto))
    return _renderizador_categorizado(campo_cor, [
        (valor, valor, _simbolo(geometria, hex_para_rgb(valor), str(i), espessura, ponto))
        for i, valor in enumerate(cores)])


def _propriedades_definidas(propriedades):
    """Bloco <dd_properties>. `propriedades` e {nome: ('campo'|'expressao', valor)}.

    O formato foi copiado do que o proprio QGIS grava; a ordem interna
    (active, field|expression, type) e a mesma dele.
    """
    itens = []
    for nome in sorted(propriedades):
        tipo, valor = propriedades[nome]
        if tipo == "campo":
            corpo = ('<Option name="field" type="QString" value=%s/>'
                     '<Option name="type" type="int" value="2"/>' % quoteattr(valor))
        else:
            corpo = ('<Option name="expression" type="QString" value=%s/>'
                     '<Option name="type" type="int" value="3"/>' % quoteattr(valor))
        itens.append('<Option name=%s type="Map">'
                     '<Option name="active" type="bool" value="true"/>%s</Option>'
                     % (quoteattr(nome), corpo))
    return ('<dd_properties><Option type="Map">'
            '<Option name="name" type="QString" value=""/>'
            '<Option name="properties" type="Map">%s</Option>'
            '<Option name="type" type="QString" value="collection"/>'
            '</Option></dd_properties>' % "".join(itens))


# O que cada texto do AutoCAD precisa para aparecer onde e como estava. Os
# nomes dos campos sao os que convert.py grava nas camadas de texto.
PROPRIEDADES_TEXTO = {
    "Color": ("campo", "cor_cad"),
    "Size": ("campo", "txt_tam"),
    "PositionX": ("expressao", "$x"),
    "PositionY": ("expressao", "$y"),
    "Hali": ("campo", "txt_h"),
    "Vali": ("campo", "txt_v"),
    # o AutoCAD mede o angulo no sentido anti-horario; o QGIS, no horario
    "LabelRotation": ("expressao", '360 - "txt_ang"'),
    "MultiLineAlignment": ("campo", "txt_h"),
    # Sem altura de linha: o QGIS ignora a que vem de campo (3.44 e 4.2), e
    # nenhum rotulo tem mais de uma linha -- cada linha de um MTEXT e uma
    # feicao, apoiada na sua linha de base (ver textos_cad.linhas_de_base).
    # Sem fator de largura (FontStretchFactor): esticada ou comprimida, o
    # QGIS desenha a letra errado nas duas versoes (ver _preparar_texto).
}


def _rotulagem_texto(html=False):
    """Rotulos que se comportam como texto de CAD, e nao como rotulo de mapa.

    Posicao, alinhamento, tamanho, rotacao, largura e cor vem de campos da
    propria feicao. Assim cada texto fica ancorado exatamente onde estava,
    com o alinhamento que tinha -- sem isso um texto centralizado era
    desenhado a partir do centro para a direita e montava sobre o vizinho.

    Em camadas com texto formatado (cor, fonte ou negrito no meio do texto) o
    rotulo vem do campo txt_html, com a formatacao em HTML; nas demais, do
    texto puro.

    Sem contorno branco (o AutoCAD nao tem), rotulos de cabeca para baixo
    mantidos como estao (upsidedownLabels=2; o QGIS por padrao os desvira),
    e displayAll=1: o desenho ja posicionou cada texto, e deixar o QGIS
    esconder os "conflitantes" apagaria justamente o que se quer ver.
    """
    return (
        '<labeling type="simple"><settings calloutType="simple">'
        '<text-style fieldName=%s isExpression="0" fontFamily="Arial" '
        'namedStyle="Regular" fontSize="2.5" fontSizeUnit="MapUnit" '
        'fontWeight="50" fontItalic="0" fontUnderline="0" fontStrikeout="0" '
        'textColor="0,0,0,255" textOpacity="1" blendMode="0" multilineHeight="1" '
        'capitalization="0" allowHtml="%d">'
        '<text-buffer bufferDraw="0" bufferSize="0" bufferSizeUnits="MM" '
        'bufferColor="255,255,255,255" bufferOpacity="1" bufferJoinStyle="128" '
        'bufferNoFill="1"/>'
        '<background shapeDraw="0"/><shadow shadowDraw="0"/><substitutions/>'
        '</text-style>'
        '<text-format autoWrapLength="0" multilineAlign="0" wrapChar="" '
        'plussign="0" placeDirectionSymbol="0" reverseDirectionSymbol="0"/>'
        '<placement placement="1" quadOffset="4" xOffset="0" yOffset="0" '
        'offsetUnits="MM" rotationAngle="0" centroidWhole="0" '
        'preserveRotation="1"/>'
        '<rendering drawLabels="1" displayAll="1" scaleVisibility="0" '
        'obstacle="0" labelPerPart="0" upsidedownLabels="2" '
        'fontLimitPixelSize="0" limitNumLabels="0"/>'
        '%s<callout type="simple"/>'
        '</settings></labeling>'
    ) % (quoteattr("txt_html" if html else "Text"), 1 if html else 0,
         _propriedades_definidas(PROPRIEDADES_TEXTO))


def _camada_vetorial(camada, srs):
    texto = bool(camada.get("texto"))
    return (
        '<maplayer type="vector" geometry=%s hasScaleBasedVisibilityFlag="0" '
        'minScale="1e+08" maxScale="0" readOnly="0" labelsEnabled="%d" '
        'styleCategories="AllStyleCategories">'
        '<id>%s</id>'
        '<datasource>%s</datasource>'
        '<layername>%s</layername>'
        '<srs>%s</srs>'
        '<provider encoding="UTF-8">ogr</provider>'
        '<vectorjoins/><layerDependencies/><dataDependencies/>'
        '<legend type="default-vector"/>'
        '<expressionfields/>'
        '<map-layer-style-manager current="default">'
        '<map-layer-style name="default"/></map-layer-style-manager>'
        '%s%s'
        '<customproperties/>'
        '<blendMode>0</blendMode><featureBlendMode>0</featureBlendMode>'
        '<fieldConfiguration/><aliases/><defaults/><constraints/>'
        '<constraintExpressions/><attributeactions/>'
        '<attributetableconfig actionWidgetStyle="dropDown"/>'
        '<editable/><labelOnTop/><widgets/>'
        '<previewExpression></previewExpression><mapTip></mapTip>'
        '</maplayer>'
        % (quoteattr(GEOMETRIA_QGIS.get(camada["geometria"], "Unknown")),
           1 if texto else 0,
           escape(camada["id"]), escape(camada["fonte"]),
           escape(camada["nome"]), srs,
           _renderizador(camada),
           _rotulagem_texto(camada.get("html", False)) if texto else ""))


def _camada_raster(camada):
    """Imagem georreferenciada. O renderizador fica por conta do QGIS: para
    imagem de 8 bits ele usa as cores do arquivo sem realce de contraste,
    que e o que se quer para um logotipo ou uma foto."""
    return (
        '<maplayer type="raster" hasScaleBasedVisibilityFlag="0" minScale="1e+08" '
        'maxScale="0" styleCategories="AllStyleCategories">'
        '<id>%s</id>'
        '<datasource>%s</datasource>'
        '<layername>%s</layername>'
        '<srs>%s</srs>'
        '<provider>gdal</provider>'
        '<map-layer-style-manager current="default">'
        '<map-layer-style name="default"/></map-layer-style-manager>'
        '<customproperties/><blendMode>0</blendMode>'
        '</maplayer>'
        % (escape(camada["id"]), escape(camada["fonte"]), escape(camada["nome"]),
           _bloco_srs(camada["epsg"])))


def gerar_qgs(caminho_qgs, camadas, epsg, extensao=None, titulo=None):
    """Escreve o .qgs.

    `camadas` vem na ordem do painel do QGIS (a primeira e desenhada por
    cima). Cada item e um dict com:
        nome, fonte       nome exibido e caminho do dado, relativo ao .qgs
        geometria         'Point', 'LineString' ou 'Polygon' (vetores)
        cores, campo_cor  cores '#rrggbb' que ocorrem na camada e o campo delas
        texto             True: camada de textos do desenho
        hachura           lista de (cor, solida): camada de hachuras
        raster, epsg      True e o sistema da imagem: camada de imagem
    `extensao` e (xmin, ymin, xmax, ymax); se vier None o QGIS abre sem zoom.
    """
    if not camadas:
        return None

    titulo = titulo or os.path.splitext(os.path.basename(caminho_qgs))[0]
    srs = _bloco_srs(epsg)
    geografico = pyproj.CRS.from_epsg(int(epsg)).is_geographic

    for i, camada in enumerate(camadas):
        camada.setdefault("id", _id_camada(camada["nome"], i))

    # --- arvore de camadas (o painel da esquerda no QGIS). Camada desligada
    # ou congelada no AutoCAD vem desmarcada: esta la, mas nao aparece.
    arvore = []
    for camada in camadas:
        arvore.append(
            '<layer-tree-layer id=%s name=%s source=%s providerKey=%s '
            'checked="%s" expanded="1"><customproperties/>'
            '</layer-tree-layer>'
            % (quoteattr(camada["id"]), quoteattr(camada["nome"]),
               quoteattr(camada["fonte"]),
               quoteattr("gdal" if camada.get("raster") else "ogr"),
               "Qt::Unchecked" if camada.get("oculta") else "Qt::Checked"))
    ordem = "".join("<item>%s</item>" % escape(c["id"]) for c in camadas)

    # --- definicao de cada camada
    definicoes = [_camada_raster(c) if c.get("raster") else _camada_vetorial(c, srs)
                  for c in camadas]

    # Enquadramento inicial, com uma folga para nada encostar na borda.
    bloco_extensao = bloco_vista = ""
    if extensao:
        xmin, ymin, xmax, ymax = extensao
        folga_x = max(xmax - xmin, 1e-9) * 0.05
        folga_y = max(ymax - ymin, 1e-9) * 0.05
        xmin, ymin, xmax, ymax = (xmin - folga_x, ymin - folga_y,
                                  xmax + folga_x, ymax + folga_y)
        bloco_extensao = ("<extent><xmin>%.10f</xmin><ymin>%.10f</ymin>"
                          "<xmax>%.10f</xmax><ymax>%.10f</ymax></extent>"
                          % (xmin, ymin, xmax, ymax))
        bloco_vista = ('<DefaultViewExtent xmin="%.10f" ymin="%.10f" '
                       'xmax="%.10f" ymax="%.10f">%s</DefaultViewExtent>'
                       % (xmin, ymin, xmax, ymax, srs))

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>\n"
        '<qgis projectname=%s version="3.28.0">'
        '<homePath path=""/>'
        '<title>%s</title>'
        '<projectCrs>%s</projectCrs>'
        '<layer-tree-group><customproperties/>%s'
        '<custom-order enabled="0">%s</custom-order></layer-tree-group>'
        '<relations/>'
        '<mapcanvas name="theMapCanvas" annotationsVisible="1">'
        '<units>%s</units>%s<rotation>0</rotation>'
        '<destinationsrs>%s</destinationsrs>'
        '</mapcanvas>'
        '<ProjectViewSettings rotation="0" UseProjectScales="0">'
        '<Scales/>%s</ProjectViewSettings>'
        '<projectlayers>%s</projectlayers>'
        '<layerorder>%s</layerorder>'
        '<properties>'
        '<Paths><Absolute type="bool">false</Absolute></Paths>'
        # Sem esta chave o QGIS considera as projecoes desligadas e IGNORA o
        # <projectCrs> inteiro: o projeto abre sem sistema de coordenadas e a
        # escala na barra de status vira um numero sem sentido.
        '<SpatialRefSys><ProjectionsEnabled type="int">1</ProjectionsEnabled>'
        '</SpatialRefSys>'
        '<Measurement><AreaUnits type="QString">%s</AreaUnits>'
        '<DistanceUnits type="QString">%s</DistanceUnits></Measurement>'
        '</properties>'
        '<visibility-presets/>'
        '<projectMetadata><identifier></identifier><title>%s</title>'
        '<author>Conversor QGIS - AutoCAD</author></projectMetadata>'
        '</qgis>\n'
    ) % (quoteattr(titulo), escape(titulo), srs,
         "".join(arvore), ordem,
         "degrees" if geografico else "meters", bloco_extensao, srs,
         bloco_vista,
         "".join(definicoes),
         "".join('<layer id=%s/>' % quoteattr(c["id"]) for c in camadas),
         "degrees" if geografico else "m2",
         "degrees" if geografico else "meters",
         escape(titulo))

    with open(caminho_qgs, "w", encoding="utf-8") as fp:
        fp.write(xml)
    return caminho_qgs
