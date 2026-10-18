"""ZIP dos relatorios em MEMORIA (io.BytesIO): o dado nao toca disco no
servidor. 1 planilha por arquivo processado; colisao de nome resolvida por
nomes_sem_colisao — nunca sobrescrita silenciosa dentro do pacote."""
from __future__ import annotations

import io
import zipfile

from relatorio.nomes import nomes_sem_colisao


def zip_relatorios(pares: list[tuple[str, bytes]]) -> bytes:
    """pares = [(nome do arquivo, bytes do arquivo)] -> bytes de um .zip."""
    nomes = nomes_sem_colisao([nome for nome, _ in pares])
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as pacote:
        for nome, (_, conteudo) in zip(nomes, pares):
            pacote.writestr(nome, conteudo)
    return buffer.getvalue()
