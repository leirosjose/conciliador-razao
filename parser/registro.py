"""O que o servico pode escrever fora da tela (stderr/stdout -> logs\\conciliador_*.log) SEM dado da razao.

So fato neutro: texto fixo, contagem, TIPO da excecao, lugar do codigo e o hash curto do CONTEUDO do arquivo (8 hex do
sha256 dos bytes; o mesmo no parser e no app, entao liga as linhas de um mesmo arquivo). Nunca o nome do arquivo, a
mensagem da excecao ou o aviso da biblioteca: tudo isso pode citar o dado. Este modulo so serve ao REGISTRO; nao le nem
interpreta razao."""
from __future__ import annotations

import hashlib
import io
import logging
import sys
import threading
import warnings
from collections import Counter
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
_PROFUNDIDADE_DA_CAUSA = 3
# reentrante: leitura dentro de leitura, na mesma thread, nao trava o servico
_TRAVA_DOS_AVISOS = threading.RLock()
# hashes cujo aviso ja virou linha: 1 linha por arquivo, nao 1 por leitura/reexecucao
_AVISOS_JA_REGISTRADOS: set = set()
_LIMITE_DOS_REGISTRADOS = 2000
_TRAVA_DO_CONJUNTO = threading.Lock()


def hash_curto(dados) -> str:
    """8 hex do sha256 dos bytes; '?' se nao forem bytes (o registro nunca falha por causa do hash)."""
    try:
        return hashlib.sha256(bytes(dados)).hexdigest()[:8]
    except Exception:
        return "?"


def hash_do_arquivo(caminho) -> str:
    """O mesmo hash, pelo arquivo no disco ('?' se nao abrir)."""
    try:
        return hash_curto(Path(str(caminho)).read_bytes())
    except Exception:
        return "?"


def descarte_do_xlrd() -> io.StringIO:
    """Destino do que o xlrd escreve por conta propria (por padrao o stdout do processo): memoria, descartada."""
    return io.StringIO()


def _lugar(arquivo: str, linha: int, funcao: str) -> str:
    caminho = Path(arquivo)
    partes = caminho.parts
    if "site-packages" in partes:
        # biblioteca: o lugar dentro dela (pasta/arquivo), sem o caminho da instalacao (que traria nome de usuario
        # da maquina); checado ANTES do relative_to, pra valer com a venv dentro ou fora da pasta do projeto
        nome = "/".join(partes[partes.index("site-packages") + 1:])
    else:
        try:
            nome = caminho.resolve().relative_to(_RAIZ).as_posix()
        except ValueError:
            nome = "/".join(partes[-2:])
    return f"{nome}:{linha} ({funcao})"


def _pilha_de(exc: BaseException) -> str:
    quadros = []
    tb = exc.__traceback__
    while tb is not None:
        quadros.append(_lugar(tb.tb_frame.f_code.co_filename, tb.tb_lineno, tb.tb_frame.f_code.co_name))
        tb = tb.tb_next
    return f"{type(exc).__name__} em " + " <- ".join(reversed(quadros))


def pilha_sem_mensagem(exc: BaseException) -> str:
    """TIPO + lugar do codigo (arquivo, linha, funcao; do mais fundo ao mais externo) da excecao e das que a causaram;
    a MENSAGEM nunca entra (ela pode citar o dado)."""
    linhas = [_pilha_de(exc)]
    origem = exc
    for _ in range(_PROFUNDIDADE_DA_CAUSA):
        origem = origem.__cause__ or (None if origem.__suppress_context__ else origem.__context__)
        if origem is None:
            break
        linhas.append("causa: " + _pilha_de(origem))
    return "\n  ".join(linhas)


def registrar_excecao(log: logging.Logger, mensagem: str, *args) -> None:
    """Substitui `log.exception(...)`: grava o texto fixo e a pilha SEM mensagem, e o registro nao leva `exc_info`
    (nenhum outro handler ou formatador consegue reconstruir a mensagem a partir dele). Chamar dentro do `except`."""
    exc = sys.exc_info()[1]
    pilha = pilha_sem_mensagem(exc) if exc is not None else "sem excecao ativa"
    log.error(mensagem + "\n  %s", *args, pilha)


@contextmanager
def avisos_calados(log: logging.Logger, hash_do_arquivo_lido):
    """Aviso de biblioteca (warnings) durante a leitura do arquivo NAO vai pra saida (a mensagem pode citar celula e
    valor do arquivo). O registro leva texto fixo + categoria + contagem + hash, 1 vez por arquivo (hash).
    `catch_warnings` mexe no estado GLOBAL do processo e nao e seguro entre threads: a trava (reentrante) serializa as
    leituras que entram aqui, entao cada thread conta os SEUS avisos e o filtro volta ao que era; uma segunda leitura
    simultanea espera a primeira terminar (so a janela da leitura do .xlsx, nao o processamento). Aviso de OUTRA thread
    que nao passe por aqui, emitido dentro da janela, tambem fica nessa contagem (e nao e gravado)."""
    pegos: list = []
    with _TRAVA_DOS_AVISOS:
        with warnings.catch_warnings(record=True) as capturados:
            warnings.simplefilter("always")
            try:
                yield
            finally:
                pegos = list(capturados)
    if pegos:
        h = hash_do_arquivo_lido()
        with _TRAVA_DO_CONJUNTO:
            if h != "?" and h in _AVISOS_JA_REGISTRADOS:
                return
            if len(_AVISOS_JA_REGISTRADOS) >= _LIMITE_DOS_REGISTRADOS:
                _AVISOS_JA_REGISTRADOS.clear()
            _AVISOS_JA_REGISTRADOS.add(h)
        por_categoria = Counter(w.category.__name__ for w in pegos)
        n = len(pegos)
        log.info("arquivo %s: %d %s (%s)", h,
                 n, "aviso do leitor nao gravado" if n == 1 else "avisos do leitor nao gravados",
                 ", ".join(f"{c}={k}" for c, k in sorted(por_categoria.items())))


def calando_avisos(log: logging.Logger, hash_dos_argumentos, quando=None):
    """Decorador de `avisos_calados` pra funcao de leitura sem mexer no corpo dela:
    `hash_dos_argumentos(*args, **kwargs)` devolve o hash do arquivo que a funcao le; `quando(*args, **kwargs)`,
    se dado, diz se esta chamada entra na janela (o .xls nao emite aviso de biblioteca e nao precisa esperar a
    trava)."""
    def decorador(funcao):
        @wraps(funcao)
        def envelopada(*args, **kwargs):
            if quando is not None and not quando(*args, **kwargs):
                return funcao(*args, **kwargs)
            with avisos_calados(log, lambda: hash_dos_argumentos(*args, **kwargs)):
                return funcao(*args, **kwargs)
        return envelopada
    return decorador
