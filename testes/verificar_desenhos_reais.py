# -*- coding: utf-8 -*-
"""
Converte os desenhos de verdade da pasta "Arquivos de testes" (que fica fora
do repositorio: sao desenhos de clientes) e confere o que da para conferir
sem olhar, desenho por desenho:

  - a conversao termina;
  - nenhum traco do padrao de uma hachura sai da borda dela (foram os tracos
    soltos na escavacao do perfil futuro do PLOT.dwg);
  - toda entidade SOLID/TRACE (ponta de seta de cota, triangulo cheio) chega
    ao QGIS -- elas sumiam;
  - os pontos de definicao de cota (camada Defpoints) ficam de fora -- viravam
    bolinhas;
  - nenhum rotulo leva quebra de linha (cada linha de MTEXT e uma feicao);
  - camada desligada ou congelada no AutoCAD vem desmarcada no QGIS, e o
    projeto abre enquadrado so no que aparece na aba Model -- sem a folha de
    impressao (espaco de papel) e sem o que esta escondido. No
    Desm_Ext.Condominio abria enquadrando 3.700 km;
  - nenhum texto passa por cima de outro da mesma linha: no LOTEAMENTO, o
    "CENTRAL" de "MERIDIANO CENTRAL    %%d WGr" entrava no 45 que fica no vao.

Precisa do ODA File Converter para ler DWG. Uso:
    python testes/verificar_desenhos_reais.py ["Arquivos de testes"] [--oda PASTA_DO_ODA]
"""
import glob
import os
import shutil
import sys
import tempfile
import warnings

warnings.filterwarnings("ignore")
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(AQUI))

import ezdxf
import fiona

from conversor import cad_ezdxf, convert, dwg, dxf_estilo


def no_anel(x, y, aneis):
    """Par ou impar de cruzamentos com todas as bordas (buracos inclusive)."""
    dentro = False
    for anel in aneis:
        for a, b in zip(anel, anel[1:] + anel[:1]):
            if (a.y > y) != (b.y > y) and x < a.x + (y - a.y) * (b.x - a.x) / (b.y - a.y):
                dentro = not dentro
    return dentro


def _pontos(geometria):
    """Todos os vertices de uma geometria GeoJSON (2D)."""
    def andar(c):
        if c and isinstance(c[0], (int, float)):
            yield c[0], c[1]
        else:
            for item in c:
                yield from andar(item)
    yield from andar(geometria["coordinates"])


def hachuras_fora_da_borda(doc):
    """Quantos tracos de padrao tem o meio fora da borda da propria hachura."""
    fora = conferidas = 0
    for layout in [doc.modelspace()] + [b for b in doc.blocks if not b.is_any_layout]:
        for h in layout.query("HATCH"):
            if h.dxf.solid_fill or h.ocs().transform:
                continue          # a conta abaixo e no sistema do desenho
            try:
                tracos = cad_ezdxf._linhas_do_padrao(h)
            except Exception:
                continue          # padrao denso demais: vira tinta translucida
            aneis = cad_ezdxf._bordas(h)
            conferidas += 1
            fora += sum(1 for a, b in tracos
                        if not no_anel((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, aneis))
    return fora, conferidas


def textos_encavalados(saida):
    """Pares de TEXT da mesma linha cuja tinta se sobrepoe no QGIS (a largura
    medida na Arial, no tamanho que o rotulo tem)."""
    import math
    from conversor import textos_cad
    itens = []
    for camada in convert.listar_camadas(saida):
        if not camada.endswith("_Texto"):
            continue
        with fiona.open(saida, layer=camada) as c:
            for f in c:
                p = f["properties"]
                texto = p.get("Text") or ""
                if "MText" in (p.get("SubClasses") or "") or not texto.strip():
                    continue
                x, y = f["geometry"]["coordinates"][:2]
                angulo = math.radians(p.get("txt_ang") or 0.0)
                ux, uy = math.cos(angulo), math.sin(angulo)
                h = (p.get("txt_tam") or 0.0) * textos_cad.CAP_ARIAL
                w = textos_cad.largura_texto(texto, h)
                inicio = x * ux + y * uy + {"Center": -w / 2, "Right": -w}.get(p.get("txt_h"), 0.0)
                itens.append((round(p.get("txt_ang") or 0.0, 1), -x * uy + y * ux, h,
                              inicio + textos_cad.largura_texto(texto[:len(texto) - len(texto.lstrip())], h),
                              inicio + w - textos_cad.largura_texto(texto[len(texto.rstrip()):], h),
                              texto))
    itens.sort(key=lambda i: (i[0], i[1]))
    pares = []
    for i, a in enumerate(itens):
        for b in itens[i + 1:]:
            if b[0] != a[0] or b[1] - a[1] > 0.3 * max(a[2], b[2]):
                break
            if b[1] - a[1] <= 0.3 * min(a[2], b[2]) and \
                    min(a[4], b[4]) - max(a[3], b[3]) > 0.05 * min(a[2], b[2]):
                pares.append((a[5], b[5]))
    return pares


def main():
    args = sys.argv[1:]
    if "--oda" in args:
        i = args.index("--oda")
        os.environ["PATH"] = args[i + 1] + os.pathsep + os.environ.get("PATH", "")
        del args[i:i + 2]
    pasta = args[0] if args else os.path.join(os.path.dirname(AQUI), "Arquivos de testes")
    if not dwg.disponivel():
        print("ODA File Converter nao encontrado (use --oda PASTA).")
        return 2
    desenhos = sorted(glob.glob(os.path.join(pasta, "*.dwg")) + glob.glob(os.path.join(pasta, "*.dxf")))
    problemas = 0
    for caminho in desenhos:
        nome = os.path.basename(caminho)
        temp = tempfile.mkdtemp(prefix="reais_")
        try:
            dxf = dwg.dwg_para_dxf(caminho) if caminho.lower().endswith(".dwg") else caminho
            log = []
            saida = os.path.join(temp, "saida.gpkg")
            convert.cad_para_qgis(dxf, saida, 31982, registrar=log.append)
        except Exception as erro:
            print("[FALHA] %s: a conversao parou: %s" % (nome, erro))
            problemas += 1
            continue

        doc = ezdxf.readfile(dxf, encoding=dxf_estilo.detectar_codificacao(dxf)[0])
        fora, conferidas = hachuras_fora_da_borda(doc)

        solidos = 0
        caixa = [float("inf"), float("inf"), float("-inf"), float("-inf")]
        with dxf_estilo.abrir_entidades(dxf) as (origem, _):
            for f in origem:
                p = f["properties"]
                solidos += "AcDbTrace" in (p.get("SubClasses") or "")
                # o que aparece na aba Model: nem papel, nem camada escondida
                if (f["geometry"] and not p.get("PaperSpace")
                        and not dxf_estilo.analisar_estilo(p.get("estilo"))["oculta"]):
                    for x, y in _pontos(f["geometry"]):
                        caixa = [min(caixa[0], x), min(caixa[1], y),
                                 max(caixa[2], x), max(caixa[3], y)]
        projeto = saida[:-4] + "qgs"
        qgs = open(projeto, encoding="utf-8").read()
        import re
        vista = [float(v) for v in re.findall(
            r'<DefaultViewExtent xmin="([^"]+)" ymin="([^"]+)" xmax="([^"]+)" ymax="([^"]+)"',
            qgs)[0]]
        folga = 0.15 * max(caixa[2] - caixa[0], caixa[3] - caixa[1])
        enquadrado = (vista[0] >= caixa[0] - folga and vista[1] >= caixa[1] - folga
                      and vista[2] <= caixa[2] + folga and vista[3] <= caixa[3] + folga)
        escondidas_cad = dxf_estilo.camadas_ocultas(dxf)
        marcadas = dict(re.findall(r'<layer-tree-layer id="[^"]*" name="([^"]+)"[^>]*checked="([^"]+)"', qgs))
        camadas = convert.listar_camadas(saida)
        chegaram = 0
        com_quebra = []
        a_mostra = []
        for camada in camadas:
            with fiona.open(saida, layer=camada) as c:
                cad = {f["properties"].get("Layer") for f in c}
                if cad and cad <= escondidas_cad and marcadas.get(camada) == "Qt::Checked":
                    a_mostra.append(camada)
                for f in c:
                    p = f["properties"]
                    if camada.endswith("_Hachura") and "AcDbTrace" in (p.get("SubClasses") or ""):
                        chegaram += 1
                    if camada.endswith("_Texto"):
                        html = p.get("txt_html") or ""
                        if "<br" in html or "¶" in html or "\n" in (p.get("Text") or ""):
                            com_quebra.append(p.get("Text"))
        defpoints = [c for c in camadas if c.lower().startswith("defpoints") and c.endswith("_Point")]

        erros = []
        if fora:
            erros.append("%d tracos de hachura fora da borda" % fora)
        if chegaram != solidos:
            erros.append("SOLID: %d no desenho, %d no QGIS" % (solidos, chegaram))
        if defpoints:
            erros.append("camadas de pontos de definicao: %s" % defpoints)
        if com_quebra:
            erros.append("%d rotulos com quebra de linha, ex.: %r" % (len(com_quebra), com_quebra[0]))
        if a_mostra:
            erros.append("camadas escondidas no AutoCAD marcadas no QGIS: %s" % a_mostra)
        if not enquadrado:
            erros.append("enquadramento inicial %s maior que o desenho visivel %s"
                         % ([round(v) for v in vista], [round(v) for v in caixa]))
        encavalados = textos_encavalados(saida)
        if encavalados:
            erros.append("%d textos por cima de outro da mesma linha, ex.: %r"
                         % (len(encavalados), encavalados[0]))
        print("[%s] %s: %d camadas; %d hachuras com padrao conferidas; %d SOLID; %s"
              % ("FALHA" if erros else "OK", nome, len(camadas), conferidas, solidos,
                 "; ".join(erros) if erros else "tudo certo"))
        problemas += 1 if erros else 0
        shutil.rmtree(temp, ignore_errors=True)
    print("\n%d desenhos, %d com problema" % (len(desenhos), problemas))
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
