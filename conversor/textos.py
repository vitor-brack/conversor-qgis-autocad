# -*- coding: utf-8 -*-
"""Pedaços de texto que a pessoa lê e que dependem de um número."""


def quantos(n, singular, plural):
    """'1 feição', '3 feições'. Aceita "?" (a lista de camadas usa quando não sabe)."""
    return "%s %s" % (n, singular if n == 1 else plural)


def feicoes(n):
    """'1 feição', '3 feições': a contagem que mais aparece nas mensagens."""
    return quantos(n, "feição", "feições")
