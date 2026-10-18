"""Largura de coluna pelo TEXTO que a tela mostra. Casca pura: so'
le texto pronto; nenhum dinheiro passa por aqui.

A grade do Streamlit (glide) desenha em canvas e corta com reticencias o que
nao cabe -- e a largura e' fixa em pixels (as duas grades, tabela e
TOTAL, tem que ter as mesmas larguras pra alinhar). Em vez de um numero
chutado por coluna, a largura sai do maior texto visivel, medido com a
tabela abaixo.

A tabela foi MEDIDA no navegador (canvas measureText) na fonte que a grade
usa -- "Source Sans", 14px --, o MAIOR valor entre os pesos 400 (celula) e
600, por caractere. Somar caractere a caractere ignora kerning, que so'
encurta: o erro e' pra mais, o lado seguro. Caractere fora da tabela vale o
mais largo dela.
"""
from __future__ import annotations

import math

_PX = {
    " ": 2.8, "!": 4.41, "\"": 6.75, "#": 7.18, "$": 7.18, "%": 11.78,
    "&": 8.94, "'": 3.85, "(": 4.54, ")": 4.54, "*": 6.13, "+": 7.18,
    ",": 3.85, "-": 4.5, ".": 3.85, "/": 4.91, "0": 7.18, "1": 7.18,
    "2": 7.18, "3": 7.18, "4": 7.18, "5": 7.18, "6": 7.18, "7": 7.18,
    "8": 7.18, "9": 7.18, ":": 3.85, ";": 3.85, "<": 7.18, "=": 7.18,
    ">": 7.18, "?": 6.22, "@": 12.25, "A": 7.81, "B": 8.36, "C": 8.06,
    "D": 8.75, "E": 7.53, "F": 7.13, "G": 8.79, "H": 9.28, "I": 3.95,
    "J": 6.92, "K": 8.36, "L": 7.03, "M": 10.43, "N": 9.2, "O": 9.44,
    "P": 8.14, "Q": 9.44, "R": 8.28, "S": 7.63, "T": 7.64, "U": 9.17,
    "V": 7.5, "W": 11.2, "X": 7.57, "Y": 7.01, "Z": 7.57, "[": 4.54,
    "\\": 4.91, "]": 4.54, "^": 7.18, "_": 7, "`": 7.68, "a": 7.22,
    "b": 7.88, "c": 6.47, "d": 7.9, "e": 7.1, "f": 4.44, "g": 7.27,
    "h": 7.81, "i": 3.66, "j": 3.68, "k": 7.3, "l": 3.79, "m": 11.8,
    "n": 7.83, "o": 7.68, "p": 7.9, "q": 7.9, "r": 5.22, "s": 6.04,
    "t": 5.05, "u": 7.78, "v": 6.93, "w": 10.47, "x": 6.73, "y": 6.93,
    "z": 6.2, "{": 4.54, "|": 3.57, "}": 4.54, "~": 7.18, "ª": 4.93,
    "º": 5.16, "À": 7.82, "Á": 7.82, "Â": 7.82, "Ã": 7.82, "Ç": 8.07,
    "É": 7.53, "Ê": 7.53, "Í": 3.95, "Ó": 9.44, "Ô": 9.44, "Õ": 9.44,
    "Ú": 9.17, "à": 7.22, "á": 7.22, "â": 7.22, "ã": 7.22, "ç": 6.46,
    "é": 7.1, "ê": 7.1, "í": 3.66, "ó": 7.68, "ô": 7.68, "õ": 7.68,
    "ú": 7.79, "–": 6.72, "—": 11.2, "…": 13.49,
}
_PX_DESCONHECIDO = max(_PX.values())

# padding horizontal da celula da grade (8px de cada lado) + folga de 4px pra
# icone de ordenacao/arredondamento do canvas
_ACRESCIMO = 16 + 4


def largura_texto(texto: str) -> float:
    """Pixels que `texto` ocupa na fonte da grade (sem padding)."""
    return sum(_PX.get(c, _PX_DESCONHECIDO) for c in texto)


def largura_coluna(textos) -> int:
    """A largura minima da coluna pra NENHUM dos textos sair cortado:
    o maior deles + padding da celula. `textos` inclui o cabecalho."""
    return math.ceil(max((largura_texto(t) for t in textos), default=0)
                     + _ACRESCIMO)
