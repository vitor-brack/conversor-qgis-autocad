# -*- coding: utf-8 -*-
"""
Leva para o QGIS as imagens raster de um desenho do AutoCAD.

O DXF nao guarda a imagem: guarda so onde ela fica (canto inferior esquerdo,
tamanho do pixel, rotacao) e o CAMINHO do arquivo. Este modulo acha o arquivo,
copia para junto dos dados convertidos e escreve dois arquivos ao lado dele:

  .pgw/.jgw/.tfw  "arquivo de mundo": diz ao QGIS onde cada pixel fica
  .aux.xml        o sistema de coordenadas, que o arquivo de mundo nao tem

Com isso o QGIS abre a imagem no lugar certo, sem georreferenciamento manual.

A figura COLADA no desenho (OLE2FRAME, como a tabela de areas do desenho real) e outra
coisa: ela mora dentro do desenho, nao ha arquivo para copiar. Ela e gravada como PNG --
dentro do GeoPackage, em pedacos (gravar_figura_no_gpkg), ou num arquivo com o de mundo
ao lado (gravar_figura_png).
"""

import datetime
import os
import shutil
import sqlite3
import struct
import zlib
from contextlib import closing

import numpy as np
import pyproj

_EXT_MUNDO = {".png": ".pgw", ".jpg": ".jgw", ".jpeg": ".jgw", ".tif": ".tfw",
              ".tiff": ".tfw", ".bmp": ".bpw", ".gif": ".gfw"}


# ---------------------------------------------------------------------------
# Tamanho em pixels, lido do cabecalho (sem biblioteca de imagem)
# ---------------------------------------------------------------------------

def dimensoes(caminho):
    """(largura, altura) em pixels, ou None se o formato nao for reconhecido.

    Serve para o caso de o arquivo ter sido trocado por outro de resolucao
    diferente: o AutoCAD estica a imagem nova para o mesmo quadro, e nos
    precisamos fazer o mesmo.
    """
    try:
        with open(caminho, "rb") as fp:
            cabeca = fp.read(64)
            if cabeca[:8] == b"\x89PNG\r\n\x1a\n":
                return struct.unpack(">II", cabeca[16:24])
            if cabeca[:6] in (b"GIF87a", b"GIF89a"):
                return struct.unpack("<HH", cabeca[6:10])
            if cabeca[:2] == b"BM":
                largura, altura = struct.unpack("<ii", cabeca[18:26])
                return largura, abs(altura)
            if cabeca[:2] == b"\xff\xd8":
                return _dimensoes_jpeg(fp)
            if cabeca[:4] in (b"II*\x00", b"MM\x00*"):
                return _dimensoes_tiff(fp, cabeca[:2] == b"II")
    except (OSError, struct.error):
        pass
    return None


def _dimensoes_jpeg(fp):
    fp.seek(2)
    while True:
        marcador = fp.read(2)
        if len(marcador) < 2 or marcador[0] != 0xFF:
            return None
        tipo = marcador[1]
        if tipo in (0xD8, 0x01) or 0xD0 <= tipo <= 0xD7:
            continue
        tamanho = struct.unpack(">H", fp.read(2))[0]
        if 0xC0 <= tipo <= 0xCF and tipo not in (0xC4, 0xC8, 0xCC):
            fp.read(1)
            altura, largura = struct.unpack(">HH", fp.read(4))
            return largura, altura
        fp.seek(tamanho - 2, 1)


def _dimensoes_tiff(fp, little):
    ordem = "<" if little else ">"
    fp.seek(4)
    fp.seek(struct.unpack(ordem + "I", fp.read(4))[0])
    n = struct.unpack(ordem + "H", fp.read(2))[0]
    achado = {}
    for _ in range(n):
        tag, tipo, _qtd, valor = struct.unpack(ordem + "HHI4s", fp.read(12))
        if tag in (256, 257):
            achado[tag] = struct.unpack(ordem + ("H" if tipo == 3 else "I"),
                                        valor[:2] if tipo == 3 else valor)[0]
    if 256 in achado and 257 in achado:
        return achado[256], achado[257]
    return None


# ---------------------------------------------------------------------------
# Localizacao do arquivo
# ---------------------------------------------------------------------------

def localizar(caminho_gravado, pastas):
    """Acha o arquivo da imagem, tentando os lugares em que ele costuma estar.

    O DXF pode guardar o caminho completo da maquina onde o desenho foi feito
    (E:\\PROJETO\\logo.jpg) ou um caminho relativo ao proprio desenho. Quando o
    desenho muda de pasta, so o nome do arquivo ainda serve.
    """
    if not caminho_gravado:
        return None
    caminho = caminho_gravado.strip().strip('"')
    candidatos = [caminho]
    nome = os.path.basename(caminho.replace("\\", "/"))
    for pasta in pastas:
        if not pasta:
            continue
        candidatos.append(os.path.join(pasta, caminho))
        candidatos.append(os.path.join(pasta, nome))
    for candidato in candidatos:
        candidato = os.path.normpath(candidato)
        if os.path.isfile(candidato):
            return candidato
    return None


# ---------------------------------------------------------------------------
# Georreferenciamento
# ---------------------------------------------------------------------------

def parametros_mundo(imagem, pixels_arquivo=None):
    """Os seis numeros do arquivo de mundo para uma entidade IMAGE.

    No DXF, `origem` e o canto inferior esquerdo da imagem, `u` e o vetor de
    UM pixel ao longo da base e `v` o de um pixel subindo pela lateral. O
    arquivo de mundo descreve o centro do pixel do canto SUPERIOR esquerdo,
    com as linhas crescendo para baixo -- dai o sinal trocado de `v`.
    """
    px, py = imagem["origem"]
    ux, uy = imagem["u"]
    vx, vy = imagem["v"]
    largura_dxf, altura_dxf = imagem["pixels"]
    largura, altura = largura_dxf, altura_dxf
    if pixels_arquivo and all(pixels_arquivo) and largura_dxf and altura_dxf:
        # arquivo com outra resolucao: o quadro no desenho continua o mesmo
        largura, altura = pixels_arquivo
        ux, uy = ux * largura_dxf / largura, uy * largura_dxf / largura
        vx, vy = vx * altura_dxf / altura, vy * altura_dxf / altura
    cx = px + altura * vx + 0.5 * ux - 0.5 * vx
    cy = py + altura * vy + 0.5 * uy - 0.5 * vy
    return (ux, uy, -vx, -vy, cx, cy), (largura, altura)


def extensao(imagem):
    """Caixa envolvente (xmin, ymin, xmax, ymax) do quadro da imagem."""
    px, py = imagem["origem"]
    ux, uy = imagem["u"]
    vx, vy = imagem["v"]
    w, h = imagem["pixels"]
    cantos = [(px, py), (px + w * ux, py + w * uy), (px + h * vx, py + h * vy),
              (px + w * ux + h * vx, py + w * uy + h * vy)]
    xs = [c[0] for c in cantos]
    ys = [c[1] for c in cantos]
    return min(xs), min(ys), max(xs), max(ys)


def exportar(imagem, arquivo, pasta_destino, epsg, nome_base):
    """Copia a imagem e escreve os arquivos que a georreferenciam.

    Devolve (caminho_copiado, extensao) ou levanta OSError.
    """
    os.makedirs(pasta_destino, exist_ok=True)
    ext = os.path.splitext(arquivo)[1].lower()
    destino = os.path.join(pasta_destino, nome_base + ext)
    shutil.copy2(arquivo, destino)

    mundo, _ = parametros_mundo(imagem, dimensoes(destino))
    base = os.path.splitext(destino)[0]
    with open(base + _EXT_MUNDO.get(ext, ".wld"), "w", encoding="ascii") as fp:
        fp.write("".join("%.12f\n" % n for n in mundo))
    _gravar_sistema(destino, epsg)
    return destino, extensao(imagem)


def _wkt(epsg):
    return pyproj.CRS.from_epsg(int(epsg)).to_wkt(pyproj.enums.WktVersion.WKT1_GDAL)


def _gravar_sistema(caminho_imagem, epsg):
    """O .aux.xml com o sistema de coordenadas, que o arquivo de mundo nao tem."""
    wkt = _wkt(epsg)
    with open(caminho_imagem + ".aux.xml", "w", encoding="utf-8") as fp:
        fp.write('<PAMDataset>\n  <SRS dataAxisToSRSAxisMapping="1,2">%s</SRS>\n</PAMDataset>\n'
                 % wkt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ---------------------------------------------------------------------------
# Figuras coladas no desenho (OLE2FRAME)
# ---------------------------------------------------------------------------

# O GeoPackage guarda imagem em pedacos quadrados; 256 pixels e o tamanho de costume.
LADO_DO_PEDACO = 256


def _bloco_png(tipo, dados):
    return (struct.pack(">I", len(dados)) + tipo + dados
            + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF))


def png(pixels):
    """Os bytes de um PNG de 8 bits a partir de HxWx3 (RGB) ou HxWx4 (RGBA) uint8. O zlib
    basta: o programa nao tem biblioteca de imagem."""
    pixels = np.ascontiguousarray(pixels, dtype=np.uint8)
    altura, largura, canais = pixels.shape
    linhas = np.zeros((altura, 1 + largura * canais), dtype=np.uint8)   # filtro 0 por linha
    linhas[:, 1:] = pixels.reshape(altura, largura * canais)
    cabeca = struct.pack(">IIBBBBB", largura, altura, 8, 6 if canais == 4 else 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _bloco_png(b"IHDR", cabeca)
            + _bloco_png(b"IDAT", zlib.compress(linhas.tobytes(), 6))
            + _bloco_png(b"IEND", b""))


def _tamanho_do_pixel(pixels, caixa):
    altura, largura = pixels.shape[:2]
    xmin, ymin, xmax, ymax = caixa
    return (xmax - xmin) / largura, (ymax - ymin) / altura


def gravar_figura_png(caminho_png, pixels, caixa, epsg):
    """Grava a figura (HxWx3) num PNG que ocupa `caixa` (xmin, ymin, xmax, ymax) no mapa,
    com o arquivo de mundo (.pgw) e o sistema (.aux.xml) ao lado. Devolve o caminho."""
    px, py = _tamanho_do_pixel(pixels, caixa)
    xmin, _ymin, _xmax, ymax = caixa
    os.makedirs(os.path.dirname(os.path.abspath(caminho_png)), exist_ok=True)
    with open(caminho_png, "wb") as fp:
        fp.write(png(pixels[..., :3]))
    # o arquivo de mundo descreve o CENTRO do pixel do canto superior esquerdo
    mundo = (px, 0.0, 0.0, -py, xmin + px / 2, ymax - py / 2)
    with open(os.path.splitext(caminho_png)[0] + ".pgw", "w", encoding="ascii") as fp:
        fp.write("".join("%.12f\n" % n for n in mundo))
    _gravar_sistema(caminho_png, epsg)
    return caminho_png


def gravar_figura_no_gpkg(caminho_gpkg, tabela, pixels, caixa, epsg):
    """Guarda a figura (HxWx3) DENTRO do GeoPackage, do jeito que o formato preve para
    imagens: uma tabela de "tiles", pedacos PNG de LADO_DO_PEDACO pixels, num nivel de
    zoom so (o da propria figura), ocupando `caixa` no sistema `epsg`.

    O QGIS (pelo GDAL) a abre como camada de imagem, no lugar certo; o GDAL nao a lista
    como camada de dados (fiona.listlayers), entao a aba QGIS -> AutoCAD nao a ve. A sobra
    dos pedacos da borda e transparente e a extensao do gpkg_contents e a da figura: o
    QGIS mostra so ela. Conferido no QGIS 3.44 e 4.2."""
    altura, largura = pixels.shape[:2]
    px, py = _tamanho_do_pixel(pixels, caixa)
    xmin, ymin, xmax, ymax = caixa
    lado = LADO_DO_PEDACO
    colunas, linhas = -(-largura // lado), -(-altura // lado)
    mosaico = np.zeros((linhas * lado, colunas * lado, 4), dtype=np.uint8)
    mosaico[:altura, :largura, :3] = pixels[..., :3]
    mosaico[:altura, :largura, 3] = 255
    agora = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    with closing(sqlite3.connect(caminho_gpkg)) as con:
        with con:                                 # tudo ou nada
            _garantir_tabelas_de_tiles(con)
            _garantir_sistema(con, epsg)
            con.execute('CREATE TABLE "%s" (id INTEGER PRIMARY KEY AUTOINCREMENT, '
                        "zoom_level INTEGER NOT NULL, tile_column INTEGER NOT NULL, "
                        "tile_row INTEGER NOT NULL, tile_data BLOB NOT NULL, "
                        "UNIQUE (zoom_level, tile_column, tile_row))" % tabela)
            con.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, "
                        "description, last_change, min_x, min_y, max_x, max_y, srs_id) "
                        "VALUES (?, 'tiles', ?, ?, ?, ?, ?, ?, ?, ?)",
                        (tabela, tabela, "Figura colada no desenho do AutoCAD", agora,
                         xmin, ymin, xmax, ymax, int(epsg)))
            con.execute("INSERT INTO gpkg_tile_matrix_set (table_name, srs_id, min_x, min_y, "
                        "max_x, max_y) VALUES (?, ?, ?, ?, ?, ?)",
                        (tabela, int(epsg), xmin, ymax - linhas * lado * py,
                         xmin + colunas * lado * px, ymax))
            con.execute("INSERT INTO gpkg_tile_matrix (table_name, zoom_level, matrix_width, "
                        "matrix_height, tile_width, tile_height, pixel_x_size, pixel_y_size) "
                        "VALUES (?, 0, ?, ?, ?, ?, ?, ?)",
                        (tabela, colunas, linhas, lado, lado, px, py))
            for linha in range(linhas):                # a linha 0 e a de cima
                for coluna in range(colunas):
                    pedaco = mosaico[linha * lado:(linha + 1) * lado,
                                     coluna * lado:(coluna + 1) * lado]
                    con.execute('INSERT INTO "%s" (zoom_level, tile_column, tile_row, '
                                "tile_data) VALUES (0, ?, ?, ?)" % tabela,
                                (coluna, linha, png(pedaco)))


def _garantir_tabelas_de_tiles(con):
    """As duas tabelas que o GeoPackage exige quando ha imagem (o GDAL ja as cria)."""
    con.execute("CREATE TABLE IF NOT EXISTS gpkg_tile_matrix_set (table_name TEXT NOT NULL "
                "PRIMARY KEY, srs_id INTEGER NOT NULL, min_x DOUBLE NOT NULL, min_y DOUBLE "
                "NOT NULL, max_x DOUBLE NOT NULL, max_y DOUBLE NOT NULL)")
    con.execute("CREATE TABLE IF NOT EXISTS gpkg_tile_matrix (table_name TEXT NOT NULL, "
                "zoom_level INTEGER NOT NULL, matrix_width INTEGER NOT NULL, matrix_height "
                "INTEGER NOT NULL, tile_width INTEGER NOT NULL, tile_height INTEGER NOT NULL, "
                "pixel_x_size DOUBLE NOT NULL, pixel_y_size DOUBLE NOT NULL, "
                "CONSTRAINT pk_ttm PRIMARY KEY (table_name, zoom_level))")


def _garantir_sistema(con, epsg):
    """Reprojetando, os dados vao para outro sistema e o do desenho (o da figura) pode nao
    estar no arquivo: sem ele, o QGIS nao saberia onde por a imagem."""
    if con.execute("SELECT 1 FROM gpkg_spatial_ref_sys WHERE srs_id = ?",
                   (int(epsg),)).fetchone():
        return
    crs = pyproj.CRS.from_epsg(int(epsg))
    con.execute("INSERT INTO gpkg_spatial_ref_sys (srs_name, srs_id, organization, "
                "organization_coordsys_id, definition, description) "
                "VALUES (?, ?, 'EPSG', ?, ?, '')",
                (crs.name, int(epsg), int(epsg), _wkt(epsg)))
