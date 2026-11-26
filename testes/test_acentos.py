"""O que a pessoa le (telas, avisos, log e o COMO USAR.txt) tem acento e cedilha.

Os textos eram escritos sem acento, por regra do projeto. Em 26/11 o usuario pediu
acento em tudo o que aparece para ele. Este teste varre as strings do programa e o
guia procurando as formas SEM acento que nao tem outra leitura em portugues, para a
regra antiga nao voltar sem querer.

Ficam de fora de proposito: "e/é", "esta/está", "tem/têm", "da/dá" (dependem do
sentido, o teste nao saberia dizer), as docstrings e os comentarios (so o
programador le) e as strings que parecem chave ou nome interno ('feicoes', 'vazio':
uma palavra so, minuscula, sem pontuacao no fim).
"""
import ast
import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parent.parent

# Formas sem acento que so existem como erro: "nao" nunca e uma palavra, "conversao"
# tambem nao. Se um dia o programa precisar de uma delas por outro motivo, tire da
# lista aqui e explique.
SEM_ACENTO = {
    "nao", "voce", "voces", "tambem", "alguem", "entao", "ate", "ja", "sao", "estao",
    "sera", "serao", "so", "tres", "util", "uteis", "unico", "unica",
    "conversao", "conversoes", "versao", "versoes", "opcao", "opcoes", "selecao",
    "informacao", "posicao", "rotacao", "definicao", "inclinacao", "impressao",
    "confusao", "escavacao", "observacoes", "situacoes", "fracoes", "atencao",
    "feicao", "feicoes", "botao", "padrao", "espaco", "espacamento", "endereco",
    "area", "areas", "angulos", "circulo", "poligono", "poligonos", "simbolo",
    "simbolos", "titulo", "titulos", "numero", "numeros", "codigo", "pagina",
    "previa", "peca", "pecas", "rotulos", "nivel", "diametro", "quilometros",
    "saida", "saidas", "possivel", "indisponiveis", "aproveitavel", "basicas",
    "cartograficas", "geograficas", "geologicos", "minusculo", "miudo", "pratico",
    "proprio", "propria", "proposito", "varias", "varios", "concluido", "concluida",
    "substituido", "substituidos", "mantem", "contem", "contrario", "calcario",
    "corrego",
}
PALAVRA = re.compile(r"[A-Za-zÀ-ÿ]+")

# Modulos cujo texto nao e lido pela pessoa: o XML do projeto do QGIS.
IGNORADOS = {"qgis_project.py"}


def _docstrings(arvore):
    """Ids das strings soltas (docstrings e comentarios de atributo): nao sao texto de tela."""
    soltas = set()
    for no in ast.walk(arvore):
        if (isinstance(no, ast.Expr) and isinstance(no.value, ast.Constant)
                and isinstance(no.value.value, str)):
            soltas.add(id(no.value))
    return soltas


def _eh_texto_de_gente(valor):
    """Tem espaco, comeca com maiuscula ou termina em pontuacao (um pedaco de frase como
    "substituido."). Chaves e nomes internos como 'feicoes' ou 'vazio' ficam de fora."""
    return " " in valor or valor[:1].isupper() or valor[-1:] in ".:;,!?)\"'"


def _achar_erros(texto):
    return sorted({p.lower() for p in PALAVRA.findall(texto)} & SEM_ACENTO)


def test_os_textos_do_programa_tem_acento():
    erros = []
    for caminho in sorted((RAIZ / "conversor").glob("*.py")):
        if caminho.name in IGNORADOS:
            continue
        arvore = ast.parse(caminho.read_text(encoding="utf-8"))
        soltas = _docstrings(arvore)
        for no in ast.walk(arvore):
            if not (isinstance(no, ast.Constant) and isinstance(no.value, str)):
                continue
            if id(no) in soltas or not _eh_texto_de_gente(no.value):
                continue
            achadas = _achar_erros(no.value)
            if achadas:
                erros.append("%s:%d %s -> %r" % (caminho.name, no.lineno, achadas,
                                                  no.value[:70]))
    assert not erros, "texto sem acento (%d):\n  %s" % (len(erros), "\n  ".join(erros))


def test_o_guia_tem_acento_e_abre_certo_no_bloco_de_notas():
    bruto = (RAIZ / "COMO USAR.txt").read_bytes()
    assert bruto.startswith(b"\xef\xbb\xbf"), \
        "com o BOM, ate um Bloco de Notas antigo abre em UTF-8 e nao mostra 'Ã§'"
    texto = bruto.decode("utf-8-sig")
    # "Ã" sozinho existe (NÃO, SÃO); estragado e "Ã" colado num simbolo, como em "Ã§".
    assert not re.search("Ã[\u0080-¿]", texto) and "�" not in texto, \
        "texto estragado na gravacao"
    soltos = re.findall(r"(?<!\r)\n", texto)
    assert not soltos, "o guia usa quebra de linha do Windows (CRLF) em todas as linhas"
    erros = []
    for numero, linha in enumerate(texto.splitlines(), 1):
        achadas = _achar_erros(linha)
        if achadas:
            erros.append("linha %d %s: %s" % (numero, achadas, linha.strip()[:70]))
    assert not erros, "guia sem acento (%d):\n  %s" % (len(erros), "\n  ".join(erros[:40]))


def test_a_contagem_da_lista_escreve_area_com_acento():
    """"3 linhas · 8 textos" (coluna "O que tem") e montada de palavras soltas, que o
    primeiro teste nao enxerga (nao tem espaco). A chave interna continua 'area'."""
    from conversor import previa

    class Soma(previa._Resumo):
        contagem = {"ponto": 1, "area": 1}

    assert Soma().resumo() == "1 ponto, 1 área"
    Soma.contagem = {"area": 3, "texto": 2}
    assert Soma().resumo(" · ") == "3 áreas · 2 textos"


def test_a_legenda_das_hachuras_com_padrao_diz_padrao_com_acento():
    """"#a52a2a padrão" aparece na legenda do QGIS. O texto da expressao e o da categoria
    tem de ser o mesmo: se um ficar sem acento e o outro com, o QGIS nao pinta a hachura."""
    import html
    import re
    from conversor import qgis_project

    camada = {"nome": "H", "geometria": "Polygon",
              "hachura": [("#ff0000", True), ("#00ff00", False)]}
    xml = qgis_project.estilo_qml(camada)
    expressao = html.unescape(re.search(r'attr="([^"]*)"', xml).group(1))
    categorias = re.findall(r'<category value="([^"]*)" symbol="\d+" label="([^"]*)"', xml)
    assert "' padrão'" in expressao, expressao
    assert categorias == [("#ff0000", "#ff0000"), ("#00ff00 padrão", "#00ff00 padrão")], categorias
