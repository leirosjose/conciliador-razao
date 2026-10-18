"""gerar_excel: ResultadoConferencia[] de UM arquivo -> bytes de UM .xlsx.

DUAS abas, porque o fluxo de conferencia e' em Excel (decisao de produto):
o conferente trabalha EM CIMA do arquivo — marca, anota, filtra,
soma. Por isso nada aqui sai travado e dinheiro nunca vira texto.

Aba 1 "Razão (Domínio)": copia FIEL da razao que o usuario subiu, reaberta dos
BYTES originais (nunca reconstruida do parseado) — o preambulo, o rodape e a
composicao manual do contador, que o parser ignora, vem juntos. .xls legado
vira .xlsx celula a celula: valores e texto preservados, formatacao visual do
Dominio nao (nao e' o produto).
Aba 2 "Conferência": espelho da tela, na mesma ordem (cabecalho / composicao /
achados / balde). Multi-conta empilha blocos.

Dinheiro chega Decimal do core e e' gravado como NUMERO com formato BR; data
como DATA. Os TEXTOS vem das mesmas funcoes puras da tela (app.apresentacao,
fonte unica), nas variantes CRUAS (_texto) — planilha nao e' markdown.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

from app.apresentacao import (TITULO_FECHADO, alertas_celulas,
                              avisos_fechado, balde_celulas,
                              composicao_celulas, e_subtotal,
                              fechado_celulas_balde, fechado_celulas_nfs,
                              itens_da_tabela, nota_fora_da_tabela,
                              nota_total_so_notas,
                              ponte_celulas, status_ponte, total_celulas,
                              contexto_incompleto_texto, data_br,
                              contexto_de_avisos, decisoes_celulas,
                              divergencias_celulas,
                              frases_alertas,
                              gap_incompleto, notas_composicao_texto,
                              status_conta, rotulo_saldo_final_planilha)
from app.materialidade import frase_contagem_motivos, frase_materialidade
from core.modelo import ResultadoConferencia
from parser.excel import grade_bruta
from relatorio.nomes import nfc

_VAZIO = "—"          # o travessao que a apresentacao poe em campo ausente

ABA_RAZAO = "Razão (Domínio)"
ABA_CONFERENCIA = "Conferência"

# codigo INVARIANTE do OOXML (a virgula e o ponto sao marcadores de posicao,
# nao os separadores literais): o Excel pt-BR do escritorio renderiza 1.234,56
FMT_MOEDA = "#,##0.00"
FMT_DATA = "DD/MM/YYYY"

_NEGRITO = Font(bold=True)
_TITULO = Font(bold=True, size=14)
_H_CONTA = Font(bold=True, size=12)
_CINZA = Font(color="FF555555")
_FUNDO_CAB = PatternFill("solid", fgColor="FFEDEDED")   # discreto: orienta, nao compete
# o rodape TOTAL, um tom acima do cabecalho -- fecha a tabela que o
# cabecalho abre, sem cor de status (a soma nao e' boa nem ruim)
_FUNDO_TOTAL = PatternFill("solid", fgColor="FFDCDCDC")
# colunas do bloco da ponte: o rotulo em A transborda por B..D (vazias de
# proposito -- o rotulo mais longo tem 47 caracteres) e o valor cai em E
_COL_VALOR_PONTE = 5
_WRAP = Alignment(wrap_text=True, vertical="top")
_TOPO = Alignment(vertical="top")

# larguras por coluna da aba de conferencia. As duas tabelas (composicao com 9
# colunas, balde com 12) dividem as MESMAS colunas: H e' a do historico, entao
# e' larga — e a "Idade (dias)" da composicao, que tambem cai em H, herda a
# largura. Tradeoff conhecido de empilhar tabelas numa aba so (a alternativa,
# jogar o historico pro fim, obrigaria o conferente a rolar pra ler a evidencia
# e voltar pra classificar).
_LARGURAS = (14, 13, 15, 15, 15, 15, 16, 48, 46, 26, 30, 12)

COL_CONFERIDO = "Conferido"
COL_CLASSIFICACAO = "Classificação"
COL_OBSERVACAO = "Observação"

# Vocabulario do que o conferente REALMENTE encontra quando abre um item do
# balde: a lista fecha o ciclo de aprendizado — o que ele classificar
# volta como padrao novo do classificador ou como regra nova. E' SUGESTAO:
# a celula pode ficar vazia e aceita texto fora da lista (a lista nunca sabe
# tudo; recusar o que o conferente escreveu perderia justamente o caso novo).
CLASSIFICACOES = (
    "NF em outra conta/período",
    "Adiantamento",
    "Tarifa ou despesa direta",
    "Juros ou encargo",
    "Pagamento duplicado",
    "Outro (detalhe na coluna Observação)",
)

# regra de tela: o que a coluna E', nao uma ordem pra preencher
TITULO_SEM_DESTINO = "Itens sem destino"
_INSTRUCAO_BALDE = ("Coluna Classificação: o que for marcado nela volta como "
                    "melhoria do sistema.")


# o XML do xlsx tambem nao aceita U+D800-U+DFFF (substituto solto), U+FFFE e U+FFFF: a planilha SALVA mas
# NAO REABRE (varredura de todos os codigos: so esses 2.050). Trocados por espaco, como o controle.
_NAO_REABRE = re.compile("[\ud800-\udfff\ufffe\uffff]")


def _grava(ws: Worksheet, linha: int, coluna: int, valor):
    """Toda escrita de celula da planilha passa aqui. Texto e' sempre
    TEXTO: o openpyxl grava str iniciada por '=' como formula e '#N/A'
    (e cia.) como erro -- a copia fiel deixaria de ser fiel."""
    if isinstance(valor, str):      # controle que o xlsx recusa
        valor = _NAO_REABRE.sub(" ", ILLEGAL_CHARACTERS_RE.sub(" ", valor))
    celula = ws.cell(row=linha, column=coluna, value=valor)
    if isinstance(valor, str) and celula.data_type in ("f", "e"):
        celula.data_type = "s"
    return celula


class _Folha:
    """Cursor de escrita: acumula linhas na aba e formata a celula pelo TIPO do
    valor (Decimal -> moeda, date -> data). Zero logica de negocio."""

    def __init__(self, ws: Worksheet) -> None:
        self.ws = ws
        self.linha = 1
        self._validacao: DataValidation | None = None

    def escreve(self, valores, *, fonte: Font | None = None,
                fundo: PatternFill | None = None, wrap: tuple[int, ...] = ()) -> int:
        atual = self.linha
        for col, v in enumerate(valores, start=1):
            celula = _grava(self.ws, atual, col, v)
            if isinstance(v, Decimal):
                celula.number_format = FMT_MOEDA
            elif isinstance(v, (datetime, date)):
                celula.number_format = FMT_DATA
            if fonte is not None:
                celula.font = fonte
            if fundo is not None:
                celula.fill = fundo
            celula.alignment = _WRAP if col in wrap else _TOPO
        self.linha += 1
        return atual

    def texto(self, texto: str, *, fonte: Font | None = None) -> int:
        return self.escreve([texto], fonte=fonte)

    def rotulo_valor(self, rotulo: str, valor) -> int:
        return self.escreve([rotulo, valor])

    def vazia(self) -> None:
        self.linha += 1

    def tabela(self, colunas: tuple[str, ...], linhas: list[dict],
               wrap: tuple[str, ...] = (),
               fonte: Font | None = None) -> tuple[int, int]:
        """Cabecalho + uma linha por dict, na ordem de `colunas`; devolve a
        primeira e a ultima linha de DADO. As colunas de trabalho (Conferido,
        Classificacao, Observacao) nao vem nos dados: sao o espaco EM BRANCO
        do conferente -- o sistema nunca chuta o que ele vai escrever.
        `fonte` veste as linhas de DADO (o bloco de quitadas sai em cinza).

        `wrap` vem por NOME de coluna, nao por indice: coluna nova no meio da
        tabela reindexa tudo em silencio, e o sintoma (a errada quebrando
        linha) nao derruba teste nenhum. Nome nao escorrega — e nome ERRADO
        estoura aqui (ValueError do .index), em vez de sumir sem wrap."""
        self.escreve(colunas, fonte=_NEGRITO, fundo=_FUNDO_CAB)
        indices = tuple(colunas.index(nome) + 1 for nome in wrap)
        primeira = self.linha
        for linha in linhas:
            self.escreve([linha.get(c) for c in colunas], fonte=fonte, wrap=indices)
        return primeira, self.linha - 1

    def dropdown(self, coluna: int, primeira: int, ultima: int) -> None:
        """Lista suspensa de CLASSIFICACOES no intervalo. Uma unica validacao
        por aba (criada na primeira vez), com um intervalo por bloco de conta:
        aba sem balde nenhum nao carrega validacao orfa."""
        if self._validacao is None:
            self._validacao = DataValidation(
                type="list",
                formula1='"' + ",".join(CLASSIFICACOES) + '"',
                allowBlank=True,            # nao obrigatorio: pode ficar vazia
                showErrorMessage=False)     # aceita texto fora da lista
            self.ws.add_data_validation(self._validacao)
        letra = get_column_letter(coluna)
        self._validacao.add(f"{letra}{primeira}:{letra}{ultima}")


def _sem_colunas_vazias(celulas: list[dict],
                        opcionais: tuple[str, ...]) -> list[dict]:
    """Tira das linhas as colunas `opcionais` que estao vazias em TODAS elas
    -- coluna cheia de travessao so' ocupa largura. Colunas
    obrigatorias ficam sempre — a tabela nao muda de forma por acaso."""
    vazias = {c for c in opcionais
              if all(l.get(c) in (None, "", _VAZIO) for l in celulas)}
    return [{k: v for k, v in l.items() if k not in vazias} for l in celulas]


def _copia_fiel(ws: Worksheet, dados_originais: bytes) -> None:
    for r, linha in enumerate(grade_bruta(dados_originais), start=1):
        for c, valor in enumerate(linha, start=1):
            if valor is None:
                continue
            celula = _grava(ws, r, c, valor)
            if isinstance(valor, (datetime, date)):
                celula.number_format = FMT_DATA


def _bloco_conta(folha: _Folha, res: ResultadoConferencia,
                 banco: bool = False) -> None:
    conta = res.conta
    _, titulo_veredito = status_conta(res.achados)
    folha.texto(f"Conta {conta.codigo} — {conta.nome}", fonte=_H_CONTA)
    folha.texto(f"Período até {data_br(conta.data_fim_periodo)}", fonte=_CINZA)
    folha.rotulo_valor("Saldo anterior", conta.saldo_anterior)
    folha.rotulo_valor("Total de débitos", conta.total_debito_dominio)
    folha.rotulo_valor("Total de créditos", conta.total_credito_dominio)
    folha.rotulo_valor(rotulo_saldo_final_planilha(banco),
                       conta.saldo_final)
    folha.texto(f"Veredito: {titulo_veredito}")
    contexto = contexto_incompleto_texto(res.achados, res.ponte)
    if contexto:
        folha.texto(contexto)
    folha.vazia()

    folha.texto("Composição do saldo — ordenado por idade, NFs mais antigas "
                "no topo", fonte=_NEGRITO)
    # UMA tabela, como na tela -- o que esta em aberto e as NFs que
    # fecharam no periodo (EM ABERTO zero), pela mesma juncao e a mesma ordem.
    linhas = itens_da_tabela(res)
    celulas = composicao_celulas(linhas)
    if celulas:
        colunas = tuple(celulas[0]) + (COL_CONFERIDO,)
        folha.tabela(colunas, celulas)
        if res.totais_tabela is not None:       # soma pronta do core
            total = total_celulas(res.totais_tabela)
            folha.escreve([total.get(c) for c in colunas],
                          fonte=_NEGRITO, fundo=_FUNDO_TOTAL)
        # a planilha nao tem tooltip -- o escopo do TOTAL
        # vai escrito, so' quando ha linha que nao e' nota
        so_notas = nota_total_so_notas(linhas)
        if so_notas:
            folha.texto(f"Nota: {so_notas}", fonte=_CINZA)
        for nota in notas_composicao_texto(linhas):
            folha.texto(f"Nota: {nota}", fonte=_CINZA)
    else:
        folha.texto("Sem itens de composição no período.")
    folha.vazia()

    _bloco_ponte(folha, res, banco=banco)
    _bloco_fechado(folha, res)

    # as decisoes do conferente vem LOGO APOS a composicao — e onde o
    # leitor pergunta "por que esta linha existe?". Secao so' aparece quando ha
    # decisao: planilha do caso comum nao ganha um "Nenhuma" a mais.
    decisoes = _sem_colunas_vazias(decisoes_celulas(res.decisoes),
                                   ("Justificativa", "Origem"))
    if decisoes:
        folha.texto(f"Decisões manuais ({len(decisoes)})", fonte=_NEGRITO)
        folha.tabela(tuple(decisoes[0]), decisoes, wrap=("Histórico",))
        folha.vazia()

    # ERRO e ALERTA em secoes PROPRIAS e nomeadas. "Nenhuma
    # divergência" seguido de quatro alertas parecia contradicao -- sao coisas
    # diferentes: erro e' a composicao que nao fecha; alerta e' aviso pra
    # conferir. A contagem vai no titulo, pra nao precisar contar linha.
    divs = divergencias_celulas(res.achados)
    if divs:
        folha.texto(f"Erros contábeis ({len(divs)})", fonte=_NEGRITO)
        folha.tabela(tuple(divs[0]), divs, wrap=("Mensagem",))
    else:
        folha.texto("Erros contábeis: nenhum.", fonte=_NEGRITO)
    folha.vazia()

    # alertas em TABELA, com os numeros em colunas proprias. Antes
    # era um paragrafo por celula (o par anulado tinha 305 caracteres).
    avisos = _sem_colunas_vazias(alertas_celulas(res.achados), ("NF/Lote",))
    if avisos:
        folha.texto(f"Alertas ({len(avisos)})", fonte=_NEGRITO)
        folha.tabela(tuple(avisos[0]), avisos, wrap=("Detalhe", "Evidencia"))
        folha.vazia()

    # No papel a ordem era cronologica; na PLANILHA o balde sai por VALOR, o
    # que pesa no topo (a coluna Data continua la: um clique reordena).
    # o nome da tela ("sem destino"), nao o jargao "balde"
    folha.texto(f"{TITULO_SEM_DESTINO} — ordenado por valor, o maior no topo",
                fonte=_NEGRITO)
    celulas_balde = balde_celulas(res.balde, por_valor=True,
                                  ctx=contexto_de_avisos(res))
    if celulas_balde:
        materialidade = frase_materialidade(res.balde, gap_incompleto(res.achados))
        if materialidade:
            folha.texto(materialidade, fonte=_NEGRITO)
        contagem = frase_contagem_motivos(res.balde)
        if contagem:
            folha.texto(contagem)
        folha.texto(_INSTRUCAO_BALDE, fonte=_CINZA)
        colunas = (tuple(celulas_balde[0])
                   + (COL_CLASSIFICACAO, COL_OBSERVACAO, COL_CONFERIDO))
        primeira, ultima = folha.tabela(colunas, celulas_balde,
                                      wrap=("Histórico", "Sugestão do motor"))
        folha.dropdown(colunas.index(COL_CLASSIFICACAO) + 1, primeira, ultima)
    else:
        # na planilha: fato. "Todo pagamento casou" era falso
        # quando o periodo zerado compensou pagamento sem nota
        folha.texto("Nenhum item sem destino.")
    folha.vazia()


def _bloco_ponte(folha: _Folha, res: ResultadoConferencia,
                 banco: bool = False) -> None:
    """A ponte do saldo, logo apos a composicao, como na tela: as
    MESMAS linhas (ponte_celulas) e o MESMO status (status_ponte, que e' o do
    veredito). Valor como NUMERO -- o conferente refaz a soma se quiser."""
    if res.ponte is None:
        return
    folha.texto("Ponte do saldo", fonte=_NEGRITO)
    _, marca = status_ponte(res)
    linhas = ponte_celulas(res.ponte, banco=banco)
    for i, linha in enumerate(linhas):
        ultima = i == len(linhas) - 1
        valores = [None] * (_COL_VALOR_PONTE + 1)
        valores[0] = linha["Linha"]
        valores[_COL_VALOR_PONTE - 1] = linha["Valor"]
        valores[_COL_VALOR_PONTE] = marca if ultima else None
        destaque = e_subtotal(linha["Linha"]) or ultima
        folha.escreve(valores, fonte=_NEGRITO if destaque else None)
    nota = nota_fora_da_tabela(res.totais_tabela)
    if nota:
        folha.texto(f"Nota: {nota}", fonte=_CINZA)
    folha.vazia()


def _bloco_fechado(folha: _Folha, res: ResultadoConferencia) -> None:
    """O periodo que o corte por saldo zero tirou da composicao,
    logo apos a ponte -- o "(-) Pagamentos sem NF em periodo ja zerado" e' o
    total daqui. Mesmas tabelas da tela, valores como NUMERO e "Zerou em" como
    DATA. So' aparece quando tem conteudo, como na tela."""
    fechado = res.fechado
    if fechado is None or not fechado.tem_conteudo:
        return
    folha.texto(TITULO_FECHADO, fonte=_NEGRITO)
    # uma frase por bloco com pendencia, cada uma com o zero DELE
    for aviso in avisos_fechado(res) or [
            f"O saldo da conta zerou em {data_br(fechado.data)} (lote "
            f"{fechado.lote}); nada ficou pendente até ali."]:
        folha.texto(aviso)
    nfs = fechado_celulas_nfs(fechado)
    if nfs:
        folha.tabela(tuple(nfs[0]), nfs)
    sem_nf = fechado_celulas_balde(fechado)
    if sem_nf:
        if nfs:
            folha.vazia()
        folha.tabela(tuple(sem_nf[0]), sem_nf, wrap=("Histórico",))
    folha.vazia()


def _conferencia(ws: Worksheet, resultados: list[ResultadoConferencia],
                 nome_origem: str, quando: datetime, banco: bool = False) -> None:
    folha = _Folha(ws)
    folha.texto("Conferência de Razão de Fornecedores", fonte=_TITULO)
    folha.texto(f"Arquivo: {nome_origem}", fonte=_CINZA)
    folha.texto(f"Gerado em {quando.strftime('%d/%m/%Y %H:%M')}", fonte=_CINZA)
    folha.vazia()
    for res in resultados:
        _bloco_conta(folha, res, banco=banco)
    for i, largura in enumerate(_LARGURAS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = largura


def gerar_excel(resultados: list[ResultadoConferencia], dados_originais: bytes,
                nome_origem: str, gerado_em: datetime | None = None) -> bytes:
    """Todas as contas do arquivo no MESMO .xlsx, na mesma ordem da tela.
    `dados_originais` sao os BYTES do upload (a aba fiel se abre deles);
    `gerado_em` existe pro teste fixar o relogio."""
    nome_origem = nfc(nome_origem)          # upload NFD do macOS
    quando = gerado_em if gerado_em is not None else datetime.now()
    wb = Workbook()
    razao = wb.active
    razao.title = ABA_RAZAO
    _copia_fiel(razao, dados_originais)
    _conferencia(wb.create_sheet(ABA_CONFERENCIA), resultados, nome_origem, quando)
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
