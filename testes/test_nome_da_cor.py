# -*- coding: utf-8 -*-
"""Como a cor do CAD aparece escrita: na lista de camadas e no nome do arquivo."""
from conversor import dxf_estilo


def test_cores_basicas_do_autocad_tem_nome_e_as_outras_aparecem_em_hexadecimal():
    nomes = {"#ff0000": "vermelho", "#ffff00": "amarelo", "#00ff00": "verde",
             "#00ffff": "ciano", "#0000ff": "azul", "#ff00ff": "magenta"}
    for cor, nome in nomes.items():
        assert dxf_estilo.nome_da_cor(cor) == nome, cor
    assert dxf_estilo.nome_da_cor("#ff7f7f") == "#ff7f7f", "as outras, pelo codigo"


def test_o_preto_do_programa_e_o_branco_do_autocad():
    # o AutoCAD tem a cor 7, que e branca no fundo preto; o programa a guarda como preto
    assert dxf_estilo.nome_da_cor("#000000") == "branco/preto"


def test_maiuscula_ou_minuscula_e_a_mesma_cor():
    assert dxf_estilo.nome_da_cor("#FF0000") == "vermelho"


def test_na_lista_toda_cor_tem_um_nome_que_se_entende():
    # "#a55252" e "#ffbf00" nao dizem nada a quem olha a lista; o nome do arquivo de saida
    # continua com o codigo (nome_da_cor), para duas cores nunca darem o mesmo nome
    nomes = {"#a55252": "marrom", "#ffbf00": "laranja", "#ff7f00": "laranja",
             "#7f7f7f": "cinza", "#007f00": "verde-escuro", "#0000ff": "azul",
             "#ff00ff": "magenta", "#ffffff": "branco", "#001326": "azul-escuro",
             "#1f007f": "roxo-escuro", "#ff7f7f": "vermelho-claro"}
    for cor, nome in nomes.items():
        assert dxf_estilo.nome_para_ler(cor) == nome, "%s -> %s" % (cor, dxf_estilo.nome_para_ler(cor))


def test_na_lista_a_cor_7_e_preta_como_na_previa():
    # a previa tem o fundo branco do AutoCAD do pai: a cor 7 aparece preta
    assert dxf_estilo.nome_para_ler("#000000") == "preto"
