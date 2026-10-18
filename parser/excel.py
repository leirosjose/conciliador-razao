"""Adapter de Excel (.xls/.xlsx) -> list[Conta]. Caminho PRIMARIO e confiavel.

ROTEAMENTO POR MAGIC BYTES, nunca por extensao: assinatura PK (ZIP)
-> rota openpyxl (.xlsx); qualquer outra (OLE, BIFF cru, lixo) -> rota xlrd,
que ja trata reparo e rejeicao amigavel. Extensao mentirosa nao derruba.
As duas rotas alimentam UM UNICO loop de parse por cima de uma "grade"
(acesso uniforme a celulas); convergem pra MESMA list[Conta] e a MESMA barra
de self-check -- o core nao sabe qual rota alimentou.

Dinheiro SEMPRE Decimal (Decimal(str(v)).quantize), NUNCA float -- as duas
fontes mostram artefatos tipo 1440.090000000001 nas celulas. Datas: o xlrd da
serial do Excel -> xldate_as_datetime; o openpyxl ja da datetime nativo.

Mapa de colunas por INDICE (a planilha tem buracos -- nao mapear por adjacencia).
Fronteira de conta detectada por 'Conta:' / 'Total da conta:'. Suporta 1..N
contas empilhadas. O que vem DEPOIS de 'Total da conta:' (rodape, composicao
manual do contador) NAO e' dado -- e' ignorado.

REPARO (SO rota .xls): alguns .xls saem do exportador do Dominio com
o offset do record BOUNDSHEET (0x0085) apontando pra um bloco de records BLANK
(0x0201) orfaos entre o EOF dos globals e o BOF real da sheet -- o xlrd segue o
ponteiro e estoura. Rota de reparo: extrai o stream BIFF do container OLE
(olefile), reescreve o offset de cada BOUNDSHEET pro BOF de sheet real
(i-esimo -> i-esimo) e reabre via file_contents. Os records orfaos sao BLANK
(celulas vazias): pular eles nao perde dado. Excel integro (golden) abre na
rota normal e NUNCA passa por aqui. .xlsx corrompido (ZIP quebrado) e' outro
universo: NAO tem reparo, rejeita com erro amigavel que diz o fato (o arquivo
nao abriu, corrompido ou incompleto).
"""
from __future__ import annotations

import io
import logging
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

import olefile
import openpyxl
import xlrd
from xlrd import xldate

from core.modelo import Conta, Lancamento, Nivel
from core.veredito import self_check_parsing
from parser.registro import calando_avisos, descarte_do_xlrd, hash_curto, hash_do_arquivo

CENTAVO = Decimal("0.01")

_log = logging.getLogger(__name__)

# indices de coluna nas linhas de LANCAMENTO
COL_DATA = 0
COL_NUMERO = 1
COL_HISTORICO = 2
COL_CTA_PART = 7
COL_DEBITO = 8
COL_CREDITO = 9
COL_SALDO = 12              # default (golden); ha exportacao real com saldo na 11 --
                            # a posicao verdadeira vem do cabecalho 'Saldo-Exercício'

# indices nas linhas de cabecalho/rodape de conta
COL_CONTA_CODIGO = 1        # linha 'Conta:'
COL_CONTA_NOME = 5          # linha 'Conta:'
COL_TOTAL_ROTULO = 4        # linha 'Total da conta:'
COL_TOTAL_DEBITO = 8
COL_TOTAL_CREDITO = 9

# ids de record BIFF usados na rota de reparo
BIFF_BOF = 0x0809
BIFF_BOUNDSHEET = 0x0085
BIFF_BOF_DT_SHEET = 0x0010  # campo dt do BOF: 0x0010 = worksheet


class ErroLeituraExcel(Exception):
    """Leitura/parsing do Excel falhou. A mensagem e' pra HUMANO (a UI exibe
    str(e) direto, nunca stack trace) e carrega o contexto disponivel:
    arquivo e, quando possivel, conta/linha em processamento."""


class CelulaIlegivel(ValueError):
    """FATO legivel sobre uma celula. E' a unica excecao de linha
    cujo texto vai pra tela; qualquer outra (texto cru do xlrd/Python) vai pro
    log."""


def _stream_biff(dados: bytes) -> bytes:
    """Stream BIFF dos BYTES: de dentro do container OLE ('Workbook'/'Book')
    quando ha container; bytes que ja sao stream BIFF cru voltam como estao."""
    if olefile.isOleFile(io.BytesIO(dados)):
        ole = olefile.OleFileIO(io.BytesIO(dados))
        try:
            nome = "Workbook" if ole.exists("Workbook") else "Book"
            return ole.openstream(nome).read()
        finally:
            ole.close()
    return dados


def _extrair_stream_biff(caminho: str) -> bytes:
    """Mesma extracao, a partir de um CAMINHO (rota do parse)."""
    return _stream_biff(Path(caminho).read_bytes())


def _reparar_offsets_boundsheet(stream: bytes) -> bytes:
    """Varre os records BIFF (header: 2 bytes id + 2 bytes len, little endian)
    e reescreve o offset de cada BOUNDSHEET (pos+4:8) pro BOF de sheet real
    correspondente (i-esimo BOUNDSHEET -> i-esimo BOF com dt=worksheet)."""
    data = bytearray(stream)
    pos = 0
    bofs_sheet: list[int] = []
    boundsheets: list[int] = []
    while pos + 4 <= len(data):
        rec_id = int.from_bytes(data[pos:pos + 2], "little")
        rec_len = int.from_bytes(data[pos + 2:pos + 4], "little")
        if (rec_id == BIFF_BOF and rec_len >= 8
                and int.from_bytes(data[pos + 6:pos + 8], "little") == BIFF_BOF_DT_SHEET):
            bofs_sheet.append(pos)
        elif rec_id == BIFF_BOUNDSHEET:
            boundsheets.append(pos)
        pos += 4 + rec_len

    if not boundsheets or len(bofs_sheet) < len(boundsheets):
        raise ValueError(
            f"estrutura BIFF nao reparavel: {len(boundsheets)} BOUNDSHEET(s) "
            f"para {len(bofs_sheet)} BOF(s) de sheet"
        )
    for i, bpos in enumerate(boundsheets):
        data[bpos + 4:bpos + 8] = bofs_sheet[i].to_bytes(4, "little")
    return bytes(data)


def _money(value) -> Decimal:
    """Valor do xlrd (float) -> Decimal de 2 casas. Celula vazia -> 0.00.
    Decimal(str(v)) mata o artefato de float (1440.090000000001 -> 1440.09)."""
    if value is None or value == "":
        return Decimal("0.00")
    try:            # texto, NaN/Infinity e 1e300 (quantize) -> fato
        valor = Decimal(str(value))
        if not valor.is_finite():
            raise InvalidOperation
        return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise CelulaIlegivel(f"a célula de valor tem {str(value)!r}, que "
                             f"não é um valor em reais") from None


def _br(v: Decimal) -> str:
    """18150.00 -> '18.150,00', so' pra mensagem (o parser nao importa app/)."""
    return f"{v:,.2f}".translate(str.maketrans(",.", ".,"))


# substituto solto (U+D800 a U+DFFF), U+FFFE e U+FFFF saem do texto NA LEITURA, trocados por espaco -- a mesma
# classe e a mesma troca que a planilha faz ao gravar (relatorio/excel.py, _NAO_REABRE). O substituto solto derruba o
# id do item no motor; U+FFFF/U+FFFE apareciam como um quadradinho no historico do item sem destino.
_FORA_DO_TEXTO = re.compile("[\ud800-\udfff\ufffe\uffff]")


def limpar_texto(texto: str) -> str:
    """Texto que o leitor entrega ao modelo (arquivo e banco). Vem ANTES de tirar o espaco das pontas."""
    return _FORA_DO_TEXTO.sub(" ", texto)


def _id(value) -> str:
    """Identificador (numero/lote, cta part, codigo) -> str, sem o '.0' do
    float. Celula vazia (None no openpyxl, '' no xlrd) -> ''."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return limpar_texto(str(value)).strip()


def _fim_periodo(texto: str) -> date | None:
    """'01/01/2025 - 30/04/2026' -> date(2026, 4, 30). Formato ruim -> None.
    A idade da NF mede contra esta data (fim do periodo), NAO date.today()."""
    if " - " not in texto:
        return None
    fim = texto.split(" - ")[-1].strip()
    try:
        d, m, a = fim.split("/")
        return date(int(a), int(m), int(d))
    except (ValueError, IndexError):
        return None


class _GradeXlrd:
    """Acesso uniforme a celulas por cima do xlrd (rota .xls/BIFF)."""

    def __init__(self, book: xlrd.book.Book) -> None:
        self._book = book
        self._sheet = book.sheet_by_index(0)
        self.nrows = self._sheet.nrows
        self.ncols = self._sheet.ncols

    def text(self, r: int, c: int) -> str:
        cell = self._sheet.cell(r, c)
        return limpar_texto(cell.value).strip() if cell.ctype == xlrd.XL_CELL_TEXT else ""

    def valor(self, r: int, c: int):
        return self._sheet.cell(r, c).value

    def e_inicio_lancamento(self, r: int) -> bool:
        # linha de lancamento comeca com data (serial numerico no BIFF)
        return self._sheet.cell(r, COL_DATA).ctype in (xlrd.XL_CELL_DATE,
                                                       xlrd.XL_CELL_NUMBER)

    def data(self, r: int, c: int) -> date:
        serial = self._sheet.cell(r, c).value
        return xldate.xldate_as_datetime(serial, self._book.datemode).date()


class _GradeXlsx:
    """Acesso uniforme a celulas por cima do openpyxl (rota .xlsx).

    Materializa as linhas de uma vez (read_only e' streaming; a razao tem
    centenas de linhas, nao milhoes). Celula ausente = None -> _money/_id/text
    ja tratam. datetime nativo vira date; dinheiro float/int passa pela MESMA
    _money da rota xls (Decimal(str(v)) mata o artefato de float)."""

    @calando_avisos(_log, lambda self, caminho: hash_do_arquivo(caminho))
    def __init__(self, caminho: str) -> None:
        # file object, nao caminho: o openpyxl rejeitaria pela EXTENSAO (.xls
        # com bytes xlsx) e quem decide a rota aqui e' a assinatura, nao o nome
        with open(caminho, "rb") as f:
            wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
            try:
                sheet = wb[wb.sheetnames[0]]
                self._rows = [list(row) for row in sheet.iter_rows(values_only=True)]
            finally:
                wb.close()
        self.nrows = len(self._rows)
        self.ncols = max((len(row) for row in self._rows), default=0)

    def _cell(self, r: int, c: int):
        row = self._rows[r]
        return row[c] if c < len(row) else None

    def text(self, r: int, c: int) -> str:
        v = self._cell(r, c)
        return limpar_texto(v).strip() if isinstance(v, str) else ""

    def valor(self, r: int, c: int):
        return self._cell(r, c)

    def e_inicio_lancamento(self, r: int) -> bool:
        # openpyxl entrega a col Data como datetime nativo
        return isinstance(self._cell(r, COL_DATA), (datetime, date))

    def data(self, r: int, c: int) -> date:
        v = self._cell(r, c)
        return v.date() if isinstance(v, datetime) else v


def _numero_cru(v):
    """Numero de celula -> int (quando inteiro) ou Decimal(str(v)).

    Decimal(str(v)) PRESERVA o que esta no arquivo, artefato e tudo
    (1440.090000000001 continua 1440.090000000001): copia fiel nao arredonda.
    O ganho e' nunca deixar um float de dinheiro atravessar a ferramenta."""
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return Decimal(str(v))


@calando_avisos(_log, lambda dados: hash_curto(dados), quando=lambda dados: dados.startswith(b"PK"))
def grade_bruta(dados: bytes) -> list[list]:
    """Grade CRUA do arquivo (linha a linha, coluna a coluna, como esta na
    planilha) a partir dos BYTES do upload -- materia-prima da COPIA FIEL da
    razao na exportacao. NAO e' o parse: nada e' interpretado, nada e'
    ignorado (preambulo, rodape e a composicao manual do contador vem juntos).

    Roteia pela MESMA assinatura do parse (PK -> openpyxl; resto -> xlrd, com a
    MESMA rota de reparo BIFF): arquivo que a ferramenta consegue CONFERIR e
    arquivo que ela consegue EXPORTAR. Celula vazia -> None; data DECLARADA
    pela planilha -> datetime (serial solto nao diz nada a ninguem); numero ->
    int/Decimal, nunca float."""
    if dados.startswith(b"PK"):
        wb = openpyxl.load_workbook(io.BytesIO(dados), read_only=True, data_only=True)
        try:
            sheet = wb[wb.sheetnames[0]]
            return [[_numero_cru(v) if isinstance(v, float) else v for v in linha]
                    for linha in sheet.iter_rows(values_only=True)]
        finally:
            wb.close()

    book = _livro_xls(dados)
    sheet = book.sheet_by_index(0)
    linhas: list[list] = []
    for r in range(sheet.nrows):
        linha: list = []
        for c in range(sheet.ncols):
            celula = sheet.cell(r, c)
            if celula.ctype == xlrd.XL_CELL_DATE:
                linha.append(xldate.xldate_as_datetime(celula.value, book.datemode))
            elif celula.ctype == xlrd.XL_CELL_NUMBER:
                linha.append(_numero_cru(celula.value))
            elif celula.ctype == xlrd.XL_CELL_TEXT:
                linha.append(celula.value)
            elif celula.ctype == xlrd.XL_CELL_BOOLEAN:
                linha.append(bool(celula.value))
            else:                       # vazia, branca ou erro de formula
                linha.append(None)
        linhas.append(linha)
    return linhas


def _livro_xls(dados: bytes) -> xlrd.book.Book:
    """Book do xlrd a partir dos BYTES, com a rota de REPARO de sempre atras.
    Fonte unica da mecanica de abertura BIFF fora do parse."""
    try:
        return xlrd.open_workbook(file_contents=dados, logfile=descarte_do_xlrd())
    except Exception:
        return xlrd.open_workbook(
            file_contents=_reparar_offsets_boundsheet(_stream_biff(dados)), logfile=descarte_do_xlrd())


class ExcelParser:
    """Implementa a interface RazaoParser para arquivos .xls/.xlsx.

    `reparado` anota se a ULTIMA chamada de parse() precisou da rota de reparo
    BIFF -- a UI usa pra exibir o aviso discreto 'arquivo reparado na leitura'.
    Rota .xlsx nunca repara: `reparado` so vira True na rota xlrd.
    """

    def __init__(self) -> None:
        self.reparado = False
        self.rotulo_numero = "Lote"

    def _abrir(self, source, nome: str) -> xlrd.book.Book:
        """Caminho feliz: xlrd direto (golden nao muda de rota). QUALQUER falha
        de leitura (XLRDError, CompDocError, struct.error, ...) tenta a rota de
        reparo -- espelha a rota .xlsx (except Exception); sem isso, CompDocError
        e amigos vazavam crus E pulavam o reparo que recuperaria o arquivo
       . Se nem o reparo abrir, erro amigavel que diz o fato (o
        arquivo nao abriu nem apos a tentativa de reparo).
        O except ErroLeituraExcel vem ANTES do except Exception nos dois niveis:
        um erro amigavel proprio (nosso) sai LIMPO, nunca re-embrulhado."""
        try:
            return xlrd.open_workbook(str(source), logfile=descarte_do_xlrd())
        except ErroLeituraExcel:
            raise
        except Exception as erro:
            try:
                stream = _reparar_offsets_boundsheet(_extrair_stream_biff(str(source)))
                book = xlrd.open_workbook(file_contents=stream, logfile=descarte_do_xlrd())
            except ErroLeituraExcel:
                raise
            except Exception:
                # o texto do leitor (ingles, bytes do arquivo) so' no log
                _log.warning("arquivo %s: nao abriu (leitor: %s)", hash_do_arquivo(source), type(erro).__name__)
                raise ErroLeituraExcel(
                    f"'{nome}' não abriu nem após tentativa de reparo."
                ) from erro
            self.reparado = True
            return book

    def _abrir_grade(self, source, nome: str) -> _GradeXlrd | _GradeXlsx:
        """Roteia pela ASSINATURA do arquivo, nunca pela extensao: PK (ZIP)
        -> openpyxl; qualquer outra -> rota xlrd de sempre (reparo incluso)."""
        with open(str(source), "rb") as f:
            assinatura = f.read(4)
        if assinatura.startswith(b"PK"):
            try:
                return _GradeXlsx(str(source))
            except Exception as erro:
                # ZIP quebrado nao tem reparo (universo diferente do BIFF)
                _log.warning("arquivo %s: nao abriu como .xlsx (leitor: %s)",
                             hash_do_arquivo(source), type(erro).__name__)
                raise ErroLeituraExcel(
                    f"'{nome}' é um .xlsx que não abriu (arquivo corrompido "
                    f"ou incompleto)."
                ) from erro
        book = self._abrir(source, nome)
        if book.nsheets == 0:          # BOUNDSHEET ausente
            raise ErroLeituraExcel(f"'{nome}' não tem nenhuma planilha.")
        return _GradeXlrd(book)

    def parse(self, source, nome: str | None = None) -> list[Conta]:
        """`nome` = como o arquivo aparece nas mensagens (o nome do upload);
        sem ele, o nome do proprio caminho."""
        self.reparado = False
        self.rotulo_numero = "Lote"
        nome = nome or Path(str(source)).name
        grade = self._abrir_grade(source, nome)

        contas: list[Conta] = []
        conta: Conta | None = None
        em_bloco = False          # True entre 'Conta:' e 'Total da conta:'
        data_fim_periodo: date | None = None      # preambulo 'Periodo:' -> base da idade
        rotulo_lido = False
        col_saldo = COL_SALDO     # posicao real vem do cabecalho (varia entre exportacoes)

        for r in range(grade.nrows):
            try:
                rotulo0 = grade.text(r, COL_DATA)
                rotulo_hist = grade.text(r, COL_HISTORICO)
                rotulo_total = grade.text(r, COL_TOTAL_ROTULO)

                if rotulo0 == "Período:":
                    data_fim_periodo = _fim_periodo(grade.text(r, COL_HISTORICO))
                elif rotulo0 == "Data":
                    if not rotulo_lido:
                        self.rotulo_numero = grade.text(r, COL_NUMERO) or "Lote"
                        rotulo_lido = True
                    # cabecalho das colunas: o Dominio imprime 'Saldo-Exercício' na
                    # col 12 (golden) OU na 11 (outras exportacoes) -- le a posicao
                    # daqui (a col 1 tambem varia, 'Número'/'Lote', mas o INDICE e' fixo)
                    for c in range(grade.ncols):
                        if grade.text(r, c).startswith("Saldo"):
                            col_saldo = c
                elif rotulo0 == "Conta:":
                    conta = Conta(
                        codigo=_id(grade.valor(r, COL_CONTA_CODIGO)),
                        classificacao=grade.text(r, COL_HISTORICO),
                        nome=grade.text(r, COL_CONTA_NOME),
                        data_fim_periodo=data_fim_periodo,
                    )
                    contas.append(conta)
                    em_bloco = True
                elif em_bloco and rotulo_hist == "SALDO ANTERIOR" and conta is not None:
                    conta.saldo_anterior = _money(grade.valor(r, col_saldo))
                elif em_bloco and rotulo_total == "Total da conta:" and conta is not None:
                    conta.total_debito_dominio = _money(grade.valor(r, COL_TOTAL_DEBITO))
                    conta.total_credito_dominio = _money(grade.valor(r, COL_TOTAL_CREDITO))
                    em_bloco = False  # PARA aqui: rodape e composicao manual nao sao dado
                elif em_bloco and conta is not None and grade.e_inicio_lancamento(r):
                    conta.lancamentos.append(self._lancamento(grade, r, col_saldo))
                # demais linhas (preambulo, vazias, rodape, gabarito manual) -> ignora
            except Exception as e:
                # contexto pro proximo diagnostico: arquivo, linha (1-based,
                # como o Excel mostra) e conta em processamento
                em_conta = f", conta {conta.codigo} ({conta.nome})" if conta is not None else ""
                if isinstance(e, CelulaIlegivel):
                    fato = str(e)
                else:
                    # texto cru do leitor/Python ("array index out of
                    # range", "cannot convert float NaN to integer") so' no log
                    _log.warning("arquivo %s: linha %d nao reconhecida (leitor: %s)",
                                 hash_do_arquivo(source), r + 1, type(e).__name__)
                    fato = "o conteúdo da linha não foi reconhecido"
                raise ErroLeituraExcel(
                    f"'{nome}': erro lendo a linha {r + 1} da "
                    f"planilha{em_conta}: {fato}"
                ) from e

        if self.reparado:
            self._gate_pos_reparo(contas, nome)
            # rastro tecnico do reparo: a UI nao avisa mais o colaborador;
            # este log e' o que sobra pro diagnostico de campo
            _log.info("arquivo %s: reparado na leitura (BOUNDSHEET do exportador "
                      "do Dominio)", hash_do_arquivo(source))
        return contas

    @staticmethod
    def _gate_pos_reparo(contas: list[Conta], nome: str) -> None:
        """Arquivo que passou pela rota de reparo so' e' aceito com o self-check
        de totais 100% verde (debitos/creditos vs 'Total da conta', saldo
        recalculado vs impresso). Reparo + self-check vermelho = REJEITA com
        mensagem clara -- mesma filosofia do portao de PDF. Arquivo INTEGRO
        nao passa por aqui: nele, divergencia e' reportada, nunca rejeitada."""
        for conta in contas:
            erros = [a for a in self_check_parsing(conta) if a.nivel is Nivel.ERRO]
            if erros:
                a = erros[0]
                raise ErroLeituraExcel(
                    f"'{nome}': o arquivo veio corrompido do "
                    f"Domínio e o reparo não é confiável — a conta {conta.codigo} "
                    f"({conta.nome}): {a.mensagem} (esperado "
                    f"{_br(a.esperado)}, encontrado {_br(a.encontrado)})."
                )

    @staticmethod
    def _lancamento(grade, r, col_saldo: int = COL_SALDO) -> Lancamento:
        return Lancamento(
            data=grade.data(r, COL_DATA),
            numero=_id(grade.valor(r, COL_NUMERO)),
            historico=grade.text(r, COL_HISTORICO),
            cta_part=_id(grade.valor(r, COL_CTA_PART)),
            debito=_money(grade.valor(r, COL_DEBITO)),
            credito=_money(grade.valor(r, COL_CREDITO)),
            saldo_exercicio=_money(grade.valor(r, col_saldo)),
        )
