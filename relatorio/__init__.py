"""Relatorio da conferencia: render pra EXCEL, 1 arquivo por razao processada.

Casca de RENDERIZACAO, irma de app/: recebe os MESMOS objetos que a tela
recebe do core e devolve bytes — quem salva/oferece download e' o app.
Zero logica de negocio, zero regex de firma, zero money math.

A saida e' .xlsx (duas abas: a razao original fiel + a conferencia), nao
mais PDF. O conferente trabalha EM CIMA do arquivo — marca, anota, filtra,
soma; papel nao aceita nada disso.
"""
from relatorio.excel import gerar_excel
from relatorio.nomes import nome_excel, nomes_sem_colisao
from relatorio.pacote import zip_relatorios

__all__ = ["gerar_excel", "nome_excel", "nomes_sem_colisao", "zip_relatorios"]
