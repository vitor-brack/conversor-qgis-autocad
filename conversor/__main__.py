# -*- coding: utf-8 -*-
"""Ponto de entrada. Sem argumentos abre a janela; com argumentos roda pela linha de comando."""

import argparse
import sys


def main():
    if len(sys.argv) == 1:
        from .gui import main as abrir_janela
        abrir_janela()
        return 0

    from . import convert, crs_presets

    ap = argparse.ArgumentParser(
        prog="conversor", description="Converte entre formatos do QGIS e do AutoCAD.")
    sub = ap.add_subparsers(dest="comando", required=True)

    p1 = sub.add_parser("paracad", help="QGIS -> AutoCAD (.dxf/.dwg)")
    p1.add_argument("entrada")
    p1.add_argument("saida")
    p1.add_argument("--camada", action="append", default=None,
                    help="camada a converter (repita para varias)")
    p1.add_argument("--epsg", type=int, default=crs_presets.PADRAO)
    p1.add_argument("--epsg-origem", type=int, default=None)
    p1.add_argument("--campo-camada", default=None)
    p1.add_argument("--campo-rotulo", default=None)
    p1.add_argument("--manter-acentos", action="store_true")
    p1.add_argument("--sem-csv", action="store_true")

    p2 = sub.add_parser("paraqgis", help="AutoCAD (.dxf/.dwg) -> QGIS")
    p2.add_argument("entrada")
    p2.add_argument("saida")
    p2.add_argument("--epsg", type=int, default=crs_presets.PADRAO,
                    help="sistema em que o desenho esta")
    p2.add_argument("--epsg-destino", type=int, default=None)
    p2.add_argument("--formato", default="GPKG",
                    choices=["GPKG", "ESRI Shapefile", "GeoJSON"])
    p2.add_argument("--juntar-camadas", action="store_true",
                    help="nao separar uma camada do QGIS por camada do AutoCAD")
    p2.add_argument("--sem-projeto", action="store_true",
                    help="nao gerar o arquivo de projeto .qgs")
    p2.add_argument("--sem-imagens", action="store_true",
                    help="nao trazer as imagens raster do desenho")
    p2.add_argument("--areas", action="store_true",
                    help="transformar polilinhas fechadas em poligonos")

    args = ap.parse_args()
    try:
        if args.comando == "paracad":
            camadas = args.camada or convert.listar_camadas(args.entrada)
            resultado = convert.qgis_para_cad(
                entradas=[{"caminho": args.entrada, "camada": c} for c in camadas],
                saida=args.saida, epsg_destino=args.epsg,
                epsg_origem_forcado=args.epsg_origem,
                campo_camada=args.campo_camada, campo_rotulo=args.campo_rotulo,
                somente_ascii=not args.manter_acentos, salvar_csv=not args.sem_csv)
        else:
            resultado = convert.cad_para_qgis(
                entrada=args.entrada, saida=args.saida, epsg_origem=args.epsg,
                formato=args.formato, epsg_destino=args.epsg_destino,
                separar_por_camada=not args.juntar_camadas,
                gerar_projeto=not args.sem_projeto,
                incluir_imagens=not args.sem_imagens,
                poli_fechada_como_poligono=args.areas)
    except convert.ErroConversao as erro:
        print("ERRO:", erro, file=sys.stderr)
        return 1

    print("Concluido: %d feicoes" % resultado["feicoes"])
    for caminho in resultado["arquivos"]:
        print("  ->", caminho)
    return 0


if __name__ == "__main__":
    sys.exit(main())
