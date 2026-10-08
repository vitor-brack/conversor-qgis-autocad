# -*- coding: utf-8 -*-
"""
Leva para o QGIS as imagens raster de um desenho do AutoCAD.

O DXF nao guarda a imagem: guarda so onde ela fica (canto inferior esquerdo,
tamanho do pixel, rotacao) e o CAMINHO do arquivo. Este modulo acha o arquivo,
copia para junto dos dados convertidos e escreve dois arquivos ao lado dele:

  .pgw/.jgw/.tfw  "arquivo de mundo": diz ao QGIS onde cada pixel fica
  .aux.xml        o sistema de coordenadas, que o arquivo de mundo nao tem

Com isso o QGIS abre a imagem no lugar certo, sem georreferenciamento manual.
"""

import os
import shutil
import struct

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

    wkt = pyproj.CRS.from_epsg(int(epsg)).to_wkt(pyproj.enums.WktVersion.WKT1_GDAL)
    with open(destino + ".aux.xml", "w", encoding="utf-8") as fp:
        fp.write('<PAMDataset>\n  <SRS dataAxisToSRSAxisMapping="1,2">%s</SRS>\n</PAMDataset>\n'
                 % wkt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return destino, extensao(imagem)
