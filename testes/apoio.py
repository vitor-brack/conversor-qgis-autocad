# -*- coding: utf-8 -*-
"""Apoio dos testes: o que depende da maquina onde eles rodam."""
import pytest

from conversor import cad_ezdxf


def tem_fonte(familia):
    """True se a fonte TrueType esta instalada, do jeito que o conversor a enxerga."""
    return familia.lower() in cad_ezdxf._indice_fontes()[0]


def requer_fonte(familia):
    """Pula o teste onde a fonte nao existe.

    O Bookman Old Style e o Arial Rounded MT Bold vem com o Office, nao com o
    Windows, e sao as fontes do desenho real que motivou estes testes. Sem elas
    o conversor cai na Arial, de proposito, e o que o teste mede deixa de existir.
    """
    return pytest.mark.skipif(not tem_fonte(familia),
                              reason="fonte '%s' nao esta instalada" % familia)
