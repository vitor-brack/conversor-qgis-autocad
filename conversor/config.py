# -*- coding: utf-8 -*-
"""Guarda as ultimas escolhas do usuario, para nao reconfigurar tudo toda vez."""

import json
import os

PASTA = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "ConversorGeo")
ARQUIVO = os.path.join(PASTA, "config.json")

PADROES = {
    "epsg_cad": 31982,          # CRS gravado no DXF
    "formato_saida": "GPKG",
    "somente_ascii": True,       # transliterar acentos (ver dxfio.py)
    "salvar_atributos_csv": True,
    "separar_por_camada": True,
    "polilinha_fechada_vira_area": False,
    "sem_textos_e_hachuras": False,
    "gerar_projeto_qgis": True,
    "incluir_imagens": True,
    "ultima_pasta": "",
}


def carregar():
    dados = dict(PADROES)
    try:
        with open(ARQUIVO, "r", encoding="utf-8") as fp:
            salvos = json.load(fp)
        # so aceita chaves conhecidas, para um config antigo nao quebrar o programa
        for chave in PADROES:
            if chave in salvos:
                dados[chave] = salvos[chave]
    except Exception:
        pass
    return dados


def salvar(dados):
    try:
        os.makedirs(PASTA, exist_ok=True)
        gravar = {k: dados[k] for k in PADROES if k in dados}
        with open(ARQUIVO, "w", encoding="utf-8") as fp:
            json.dump(gravar, fp, indent=2, ensure_ascii=False)
    except Exception:
        pass   # preferencias sao um conforto, nunca motivo para falhar a conversao
