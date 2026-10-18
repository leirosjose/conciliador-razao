"""Camada de APRESENTACAO: traduz o que o core devolve para linhas/labels de
tela. PURO -- sem streamlit, sem I/O, SEM aritmetica de dinheiro. So leitura de
campos Decimal + formatacao de exibicao; toda conta de saldo vive no core.
"""
from __future__ import annotations

import re
from collections import Counter, namedtuple
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from html import escape

from app.larguras import largura_coluna
from core.classifica import Tipo
from core.modelo import (
    ALVO_ANTERIOR,
    Achado,
    ComposicaoItem,
    CriterioDesempate,
    CriterioSugestao,
    DestinoAlocacao,
    ItemRevisao,
    Lancamento,
    MotivoRevisao,
    Nivel,
    Origem,
    RegraCasamento,
)

CENTAVO = Decimal("0.01")
_VAZIO = "—"

# Rotulo de EXIBICAO da linha do saldo anterior. O valor do CORE
# (ALVO_ANTERIOR, que a alocacao manual recebe como alvo) NAO muda -- so' o que
# o leitor ve. "(anterior)" sozinho nao dizia o que a linha era: quem confere precisou
# perguntar. Um mapa so', consumido pela tabela (tela + Excel) e pelo seletor.
ROTULO_ANTERIOR = "(saldo anterior)"


def rotulo_linha(nf_numero: str) -> str:
    """Como a linha se chama PRA QUEM LE. Identidade de core -> nome de tela."""
    return ROTULO_ANTERIOR if nf_numero == ALVO_ANTERIOR else nf_numero


def nome_de_linha(numero: str) -> str:
    """"NF 48217" pra um numero de nota (so' digitos); qualquer outro nome sai
    como esta: rotulo do motor ("(anterior)", "(transferencia lote 322087)") ou
    nome livre digitado pelo operador. "NF" na frente de um nome que nao e'
    numero de nota seria mentira."""
    # Numero de NF e' so' digito (parser/historico.py); nome
    # LIVRE digitado pro operador ("LINHA NOVA X") nao ganha "NF" na frente
    return f"NF {numero}" if numero.isdigit() else numero

# severidades de veredito -- chaves que a tela mapeia pra cor (success/warning/error)
FECHA = "FECHA"
INCOMPLETO = "INCOMPLETO"
DIVERGENCIA = "DIVERGENCIA"


def moeda_br(v: Decimal) -> str:
    """Decimal -> '1.234,56' (padrao BR). Formatacao de EXIBICAO: nao reconverte
    pra float, nao faz conta -- so renderiza o Decimal que veio do core."""
    q = v.quantize(CENTAVO, rounding=ROUND_HALF_UP)
    sinal = "-" if q < 0 else ""
    inteiro, _, frac = f"{abs(q):.2f}".partition(".")
    grupos: list[str] = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    grupos.insert(0, inteiro)
    return f"{sinal}{'.'.join(grupos)},{frac}"


def pct_br(percentual: Decimal) -> str:
    """Decimal -> '2,00' (separador BR). Mesmo espirito de moeda_br: troca o
    separador de um Decimal que ja veio pronto, sem reconverter nem calcular."""
    return f"{percentual}".replace(".", ",")


_MD_ESPECIAIS = "$*_`~[]!"


def markdown_seguro(texto: str) -> str:
    """Escapa texto DINAMICO que vai pra dentro de Markdown (titulo de
    expander, st.markdown, st.caption). Dois 'R$' na mesma linha viram par de
    delimitadores LaTeX no renderizador do Streamlit — o trecho vira formula
    e o cifrao some (um caso: historico com 'Valor de R$ ...' no
    titulo que ja tem o R$ do item); *, _, `, ~ virariam enfase/codigo;
    [ e ] matam link '[texto](url)' E imagem '![](url)' — ambos exigem o
    colchete (imagem markdown auto-carrega URL externa no navegador). ( ) NAO
    se escapa: seria redundante (o colchete ja mata o construto), backslasharia
    todo parentese legitimo do texto financeiro e '\\(...\\)' ainda e' um
    delimitador de math. Quebras de linha viram espaco pra o historico
    multilinha nao escapar do blockquote '> '.
    A barra escapa PRIMEIRO (senao escaparia os proprios escapes). A tabela
    HTML propria NAO passa por aqui: la o escape e de HTML e cifrao nao e
    especial em HTML.
    O texto ja sai SEM gatilho de link (sem_link_automatico): nome de
    arquivo, de fornecedor ou de cliente com endereco, e-mail ou entidade
    nunca vira link, e o "\\_" do escape deixa de aparecer escrito."""
    texto = texto.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    texto = texto.replace("\\", "\\\\")
    for c in _MD_ESPECIAIS:
        texto = texto.replace(c, "\\" + c)
    return sem_link_automatico(texto)


# markdown_seguro nao desliga o link automatico (URL, www.,
# e-mail, <...>) -- medido no navegador. Um caractere sem largura (U+2060)
# depois do gatilho desfaz o padrao sem mudar o que se le. O "&" entra porque
# o markdown troca a entidade ("&colon;", "&#58;", "&#x3a;") pelo caractere
# DEPOIS daqui: com o "&" desfeito, entidade nenhuma e' decodificada.
# 1 caractere por gatilho -- quem ja traz o caractere nao ganha outro
# (markdown_seguro aplica a protecao; o rotulo do numero e o do seletor de
# janela a aplicam antes e passam por ele depois).
_GATILHO_DE_LINK = re.compile(r"(?i)(<|&|https?:(?=//)|www(?=\.)|@)(?!\u2060)")


def sem_link_automatico(texto: str) -> str:
    """Texto que vai pra markdown sai sem gatilho de link. E o ultimo passo de
    markdown_seguro; aplicar de novo num texto ja protegido nao muda nada."""
    return _GATILHO_DE_LINK.sub("\\1\u2060", texto)


def texto_digitado(texto: str | None) -> str:
    """Texto que a pessoa digitou ou colou num campo da tela, antes de ir adiante
    (motor, planilha, comparacao). Nome copiado da tela traz o caractere sem
    largura de sem_link_automatico: aqui ele sai. Todo campo de texto passa por
    aqui (trava: tests/test_nome_nunca_vira_link.py)."""
    return (texto or "").replace("\u2060", "")


def _rotulo_do_numero(rotulo: str, banco: bool) -> str:
    """Nome da coluna do numero do lancamento: o cabecalho do ARQUIVO
    (dado externo que vai pra markdown: sai sem gatilho de link); "Lote" no
    modo banco e quando o arquivo nao traz o cabecalho."""
    if banco:
        return "Lote"
    return sem_link_automatico(rotulo.strip()) or "Lote"


def md_ja_escapado(texto: str) -> str:
    """Marcador (identidade) de texto que JA chega escapado por partes -- a
    tabela da ponte, montada celula a celula com markdown_seguro, e os campos
    de balde_detalhes/titulo_conta, escapados na origem. Existe pra que a trava
    tests/test_injecao_markdown.py enxergue a decisao: todo texto que vira
    markdown na tela passa por markdown_seguro OU declara que ja passou."""
    return texto


def data_br(d: date | None) -> str:
    """date -> 'dd/mm/aaaa'; None (sem data: item anterior, NF sem quitacao)
    -> '—' (coluna homogenea de strings, como a idade)."""
    return d.strftime("%d/%m/%Y") if d is not None else _VAZIO


def titulo_conta(conta, arquivo: str | None = None) -> str:
    """Cabecalho da conta pra st.subheader. codigo/nome (celula) e arquivo
    (nome do upload) sao dado EXTERNO -- escapam aqui, no ponto de montagem.
    Em lote, o prefixo diz de qual arquivo veio."""
    titulo = (f"Conta {markdown_seguro(conta.codigo)} — "
              f"{markdown_seguro(conta.nome)}")
    if arquivo:
        titulo = f"📄 {markdown_seguro(arquivo)} — {titulo}"
    return titulo


def status_conta(achados: list[Achado]) -> tuple[str, str]:
    """Reduz os Nivel dos achados a UMA severidade de tela + titulo. Traducao,
    nao recalculo: ERRO manda (vermelho); senao INCOMPLETO (amarelo, ha balde);
    senao FECHA (verde). ALERTA NAO derruba o verde -- e sinalizacao a parte."""
    if any(a.nivel is Nivel.ERRO for a in achados):
        # "balde" e' jargao da casa -- no veredito, o que o leitor ve
        return DIVERGENCIA, ("Divergência: a composição não fecha e a diferença "
                             "não é explicada pelos itens sem destino")
    if any(a.nivel is Nivel.INCOMPLETO for a in achados):
        return INCOMPLETO, ("Incompleto: há itens sem destino que respondem pela "
                            "diferença")
    return FECHA, "Fecha: a composição bate com o saldo final"


def saldo_dominio_texto(conta, banco: bool = False) -> str:
    """O saldo final do Domínio como o leitor fala -- "R$ X a pagar"
    (conta credora, saldo negativo no Domínio) ou "a receber" (devedora). O
    sinal do Domínio e' convenção contábil; aqui vira palavra. abs() e'
    formatação de sinal, não conta."""
    saldo = conta.saldo_final
    origem = "Saldo calculado dos lançamentos lidos" if banco else "Saldo no Domínio"
    if saldo == Decimal("0.00"):
        return f"{origem}: R$ 0,00"
    lado = "a pagar" if saldo < 0 else "a receber"
    return f"{origem}: R$ {moeda_br(abs(saldo))} {lado}"


# O que cada coluna da composição quer dizer, sem jargão -- vira o
# tooltip (help) do cabeçalho na tela. Uma frase por coluna, fato, sem ordem.
AJUDA_COLUNAS = {
    "NF": "Número da nota fiscal. Linhas entre parênteses não são notas: "
          "saldo trazido do período anterior, transferido de outra conta ou "
          "pago acima das notas que o pagamento cita.",
    # A data que o razao traz e' a do LANCAMENTO da compra -- nao
    # necessariamente a emissao da nota
    "Data NF": "Data da nota no razão: a do lançamento da compra, que não é "
               "necessariamente a emissão. Nas linhas entre parênteses, a data "
               "do lançamento.",
    # Vazios nas linhas entre parenteses -- fora dos totais
    "Valor compra": "Valor total da nota. Vazio nas linhas entre parênteses, "
                    "que não são notas.",
    "Total pago": "Pagamentos que o sistema ligou a esta nota. Vazio nas "
                  "linhas entre parênteses, que não são notas.",
    "Retido": "Impostos retidos na fonte ligados à nota (IRRF, ISS, INSS, "
              "PIS, COFINS, CSLL). Quitam a nota sem dinheiro sair.",
    "Baixa adiant.": "Parte da nota quitada com um adiantamento já pago ao "
                     "fornecedor.",
    "Alocado à mão": "O que foi ligado a esta nota manualmente nesta tela. "
                     "Crédito ligado aparece negativo.",
    "EM ABERTO": "Quanto falta pagar: valor da nota menos pago, retido, baixa "
                 "e alocado à mão. Nas linhas entre parênteses, o valor que "
                 "elas trazem ao saldo. Negativo = pago acima do valor.",
    "Última quitação": "Data do último pagamento, retenção ou baixa da nota.",
    "Pago antes da NF no razão": "Data do primeiro pagamento ligado à nota "
                                 "feito antes da data da nota no razão. Essa "
                                 "data é a do lançamento da compra, não "
                                 "necessariamente a emissão.",
    "Idade (dias)": "Dias entre a data da nota no razão e o fim do período do "
                    "arquivo.",
}

# Cabecalho CURTO so' na tela -- a chave da coluna (Excel, testes,
# column_order) continua o nome completo, que vai na frente do tooltip. Assim
# 8 colunas cabem a 1200px com a sidebar aberta sem titulo cortado.
ROTULO_CURTO = {"Última quitação": "Últ. quitação", "Idade (dias)": "Idade",
                "Pago antes da NF no razão": "Antes da NF"}


def ajuda_coluna(nome: str) -> str:
    """O tooltip da coluna; quando o cabecalho e' encurtado, o nome inteiro
    abre o texto."""
    if nome in ROTULO_CURTO:
        return f"{nome}: {AJUDA_COLUNAS[nome]}"
    return AJUDA_COLUNAS[nome]


def resposta_conferido(res) -> str | None:
    """Quando a conta FECHA, o topo responde a pergunta de quem abriu a
    tela ("quanto devo, e do que?") numa frase, em vez de dizer que a
    composicao bate. Usuario-alvo: colaborador sem experiencia contabil.
    Outros vereditos: None (a tela mantem o texto de sempre).

    Zero conta aqui: o saldo e' o alvo que o core ja calculou (o mesmo do
    placar), e as linhas sao as que a composicao ja tem. O saldo anterior vai
    numa clausula propria: ele nao e' nota nem tem data, e contado como nota
    a "mais antiga" mentiria."""
    severidade, _ = status_conta(res.achados)
    check = next((a for a in res.achados
                  if a.codigo == "self_check_composicao"), None)
    if severidade != FECHA or check is None:
        return None
    saldo = f"R$ {moeda_br(check.valores['alvo'])}"
    abertas = [i for i in res.itens if i.saldo_aberto != Decimal("0.00")]
    notas = [i for i in abertas if i.origem is not Origem.SALDO_ANTERIOR]
    anterior = next((i for i in abertas if i.origem is Origem.SALDO_ANTERIOR),
                    None)
    if not abertas:
        return "Conferido. Saldo zerado: nenhuma nota em aberto."
    if len(notas) == 1 and anterior is None:
        (nota,) = notas
        quando = f" ({data_br(nota.data_compra)})" if nota.data_compra else ""
        return (f"Conferido. Saldo de {saldo} = "
                f"{nome_de_linha(nota.nf_numero)}{quando}, em aberto.")
    partes = []
    if notas:
        datas = [i.data_compra for i in notas if i.data_compra is not None]
        mais_antiga = (f" (a mais antiga de {data_br(min(datas))})"
                       if datas else "")
        palavra = "nota" if len(notas) == 1 else "notas"
        partes.append(f"{len(notas)} {palavra} em aberto{mais_antiga}")
    if anterior is not None:
        partes.append(f"R$ {moeda_br(anterior.saldo_aberto)} de saldo anterior")
    return f"Conferido. Saldo de {saldo} = {' e '.join(partes)}."


def _idade_key(item: ComposicaoItem) -> tuple[bool, int]:
    # mais antiga (maior idade) no topo; item sem idade (saldo anterior) por ultimo
    return (item.idade_dias is None, -(item.idade_dias or 0))


def celula_texto(v) -> str:
    """Valor NATIVO de uma celula -> texto de exibicao, pelo TIPO: Decimal vira
    moeda BR, date vira dd/mm/aaaa, ausencia vira travessao, o resto vira str.
    E o que mantem as tabelas de TEXTO (tela) e as de VALOR (Excel) com
    UMA definicao de coluna cada -- a de texto e a de valor formatada."""
    if v is None:
        return _VAZIO
    if isinstance(v, Decimal):
        return moeda_br(v)
    if isinstance(v, date):
        return data_br(v)
    if isinstance(v, str):
        return v
    return str(v)


def _linhas_de_texto(celulas: list[dict]) -> list[dict]:
    return [{k: celula_texto(v) for k, v in linha.items()} for linha in celulas]


def _linha_composicao(nf: str, valores, data_nf=None, ultima=None,
                      idade=None, antes=None) -> dict:
    """UMA definicao das colunas da tabela de composicao, em ordem. `valores`
    e' qualquer coisa com os seis campos monetarios -- o ComposicaoItem de uma
    linha ou o TotaisComposicao do rodape (mesmos nomes de proposito),
    entao a linha TOTAL nunca escorrega de coluna."""
    return {
        "NF": nf,
        "Data NF": data_nf,
        "Valor compra": valores.valor_compra,
        "Total pago": valores.total_pago,
        # Retencao (IRRF/ISS/INSS...) ligada a NF e quitacao sem
        # numerario -- coluna propria, como a baixa; "Total pago" nunca a
        # incluiu (o manual dizia que sim e foi corrigido)
        "Retido": valores.total_retido,
        "Baixa adiant.": valores.total_baixado,
        # O VALOR que o contador alocou, em coluna propria -- "Total
        # pago" e so' o que o motor casou (nao se mistura), e a linha
        # se le como uma conta: compra - pago - baixa - alocado = EM ABERTO
        "Alocado à mão": valores.total_manual,
        "EM ABERTO": valores.saldo_aberto,
        "Última quitação": ultima,
        # Pagamento casado ANTES da emissao -- fato na linha,
        # o mesmo tratamento pra todo casamento. Nao muda destino nem rotula.
        "Pago antes da NF no razão": antes,
        "Idade (dias)": idade,
    }


def composicao_celulas(itens: list[ComposicaoItem]) -> list[dict]:
    """As MESMAS colunas e a MESMA ordem da tabela de composicao, com os
    valores NATIVOS (Decimal / date / int / None) -- o Excel precisa de
    NUMERO em celula numerica (o conferente soma e filtra em cima), nao de
    texto ja formatado. Fonte unica das colunas: composicao_linhas formata
    daqui."""
    celulas = []
    for i in sorted(itens, key=_idade_key):
        celula = _linha_composicao(rotulo_linha(i.nf_numero), i, i.data_compra,
                                   i.data_ultima_quitacao, i.idade_dias,
                                   i.pagamento_antes_da_emissao)
        if not i.e_nota:
            # Linha que nao e' nota fica fora dos totais de
            # compra e pago (core) -- na linha, as duas celulas VAZIAS, e o
            # valor dela so' em EM ABERTO. Tela e planilha iguais.
            celula["Valor compra"] = celula["Total pago"] = None
        celulas.append(celula)
    return celulas


# Rotulo do rodape. Maiusculo como o "EM ABERTO": e' o nome da linha
# que o contador procura no pe da tabela, nao enfeite.
ROTULO_TOTAL = "TOTAL"


def total_celulas(totais) -> dict:
    """A linha TOTAL com valores NATIVOS (Excel). Os numeros vem PRONTOS do
    core (res.totais_tabela) -- aqui nenhuma soma nasce. Data e idade ficam
    None: nao existe "data do total"."""
    return _linha_composicao(ROTULO_TOTAL, totais)


def total_linha(totais, rotulo: str = ROTULO_TOTAL) -> dict:
    """A linha TOTAL em texto (tela). Data e idade VAZIAS, nao travessao: o
    travessao diz "esta linha nao tem esse dado", e o rodape nem e' linha.
    A tela da' NOME ao escopo do total (ROTULO_TOTAL_*); o Excel segue
    com "TOTAL"."""
    celulas = total_celulas(totais)
    celulas["NF"] = rotulo
    return {k: ("" if v is None else celula_texto(v)) for k, v in celulas.items()}


# O TOTAL diz O QUE soma. Por padrao a tela mostra so' o que esta em
# aberto; com o toggle, a tabela inteira -- e o rotulo acompanha.
# Rotulos CURTOS -- o rotulo mora na coluna NF e era ele que fixava a
# largura dela (177px; num caso, a tabela no lote rolava de lado). O escopo inteiro
# fica no tooltip da NF da grade do total (ajuda_total).
ROTULO_TOTAL_EM_ABERTO = "Total em aberto"
ROTULO_TOTAL_COM_QUITADAS = "Total com quitadas"
_ESCOPO_TOTAL = {
    ROTULO_TOTAL_EM_ABERTO: ("Total em aberto: soma só das notas com valor em "
                             "aberto. As notas quitadas não entram. Valor "
                             "compra e Total pago somam só as notas; as linhas "
                             "entre parênteses entram só em EM ABERTO."),
    ROTULO_TOTAL_COM_QUITADAS: ("Total com quitadas: soma de todas as notas "
                                "da tabela, em aberto e quitadas. Valor compra "
                                "e Total pago somam só as notas; as linhas "
                                "entre parênteses entram só em EM ABERTO."),
}


def ajuda_total(rotulo: str) -> str:
    """O tooltip da coluna NF na grade do TOTAL: o escopo por extenso."""
    return _ESCOPO_TOTAL.get(rotulo, ajuda_coluna("NF"))


def rotulo_toggle_quitadas(res) -> str | None:
    """"Mostrar notas quitadas (N)", N = linhas que a visao padrao esconde
    (NFs quitadas e linhas zeradas). None quando nao ha o que esconder."""
    escondidas = len(itens_da_tabela(res)) - len(res.itens_em_aberto)
    return f"Mostrar notas quitadas ({escondidas})" if escondidas else None


def composicao_linhas(itens: list[ComposicaoItem],
                      juros: frozenset[str] = frozenset()) -> list[dict]:
    """Linhas da tabela de composicao, com a NF mais antiga no topo (aging
    sort-only: sem limiar inventado -- so ordena e mostra os dias).
    Idade SEMPRE string de exibicao: item de saldo anterior nao tem idade e a
    coluna nao pode misturar int com '—' (o arrow do st.dataframe estoura).
    `juros`: as NFs com alerta de possivel juros (nfs_com_possivel_juros)."""
    linhas = _linhas_de_texto(composicao_celulas(itens))
    # EM ABERTO negativo e' pagamento acima da nota -- a linha diz
    # isso em palavra (fato). So' a TELA: no Excel a NF e' celula de filtro.
    # O total continua somando o negativo (vem pronto do core).
    # Residuo dentro da tolerancia de centavos ja aprovada e'
    # arredondamento, nao pagamento a maior -- mesma fonte que cala o alerta
    # de juros (quitada_com_arredondamento); ai so' a nota de arredondamento.
    for linha, item in zip(linhas, sorted(itens, key=_idade_key)):
        # Data curta so' na TELA (cabe na coluna estreita); o Excel
        # le composicao_celulas, com a data completa
        if item.pagamento_antes_da_emissao is not None:
            linha[COLUNA_ANTES_DA_NF] = data_curta(item.pagamento_antes_da_emissao)
        # Na linha que nao e' nota, o que nao se
        # aplica fica VAZIO -- data ausente, compra e pago (fora dos totais)
        if not item.e_nota:
            linha["Valor compra"] = linha["Total pago"] = ""
            if linha["Data NF"] == _VAZIO:
                linha["Data NF"] = ""
        # A linha da sobra ja se chama "(pago a maior lote X)"
        if (item.saldo_aberto < Decimal("0.00")
                and not item.quitada_com_arredondamento
                and item.origem is not Origem.PAGO_A_MAIOR):
            # Um nome so' -- a NF que tem o alerta de possivel
            # juros se chama assim na tabela tambem, como nas Observacoes
            marca = (MARCA_POSSIVEL_JUROS if item.nf_numero in juros
                     else MARCA_PAGO_A_MAIOR)
            linha["NF"] = f"{linha['NF']} {marca}"
    return linhas


MARCA_PAGO_A_MAIOR = "(pago a maior)"


def linhas_sem_nota(itens: list[ComposicaoItem]) -> list[bool]:
    """Por linha, na ORDEM da tabela (composicao_linhas), se ela
    NAO e' nota -- a tela as pinta de cinza pra o olho separar nota de
    ajuste. A regra e' a do core (ComposicaoItem.e_nota)."""
    return [not i.e_nota for i in sorted(itens, key=_idade_key)]


def nota_total_so_notas(itens: list[ComposicaoItem]) -> str | None:
    """O que o TOTAL de compra e pago deixa de fora, dito
    onde nao ha tooltip (planilha). None quando toda linha e' nota."""
    if all(i.e_nota for i in itens):
        return None
    return ("Valor compra e Total pago do TOTAL somam só as notas; as linhas "
            "entre parênteses (saldo anterior, transferência, pago a maior) "
            "entram só em EM ABERTO.")
MARCA_POSSIVEL_JUROS = "(possível juros)"
_CODIGOS_JUROS = ("possivel_juros", "possivel_juros_manual")


def nfs_com_possivel_juros(achados: list[Achado]) -> frozenset[str]:
    """As NFs que o core marcou com possivel juros (automatico ou apos
    alocacao manual). A marca da linha vem do MESMO achado das Observacoes:
    o nome nunca diverge entre as duas."""
    return frozenset(a.referencia for a in achados
                     if a.codigo in _CODIGOS_JUROS and a.referencia)
COLUNA_ANTES_DA_NF = "Pago antes da NF no razão"


def data_curta(d: date) -> str:
    """dd/mm/aa -- so' onde a coluna e' estreita."""
    return d.strftime("%d/%m/%y")


def larguras_composicao(linhas: list[dict], rotulo_total: str) -> dict[str, int]:
    """Largura das colunas que variam com o conteudo, pelo maior texto
    VISIVEL (app/larguras.py). NF inclui o rotulo do TOTAL: as duas grades
    dividem as larguras e o rotulo mora na coluna NF da segunda.
    Idade nunca abaixo de 4 digitos (a coluna nao pula de largura entre
    contas). Cabecalho e' o que a tela mostra (o curto, quando ha)."""
    def textos(coluna: str, *extras: str) -> list[str]:
        return ([ROTULO_CURTO.get(coluna, coluna), *extras]
                + [str(l[coluna]) for l in linhas if coluna in l])
    return {
        "NF": largura_coluna(textos("NF", rotulo_total)),
        COLUNA_ANTES_DA_NF: largura_coluna(textos(COLUNA_ANTES_DA_NF)),
        "Idade (dias)": largura_coluna(textos("Idade (dias)", "9999")),
    }

# EM ABERTO nunca sai -- e' a pergunta da tela. As demais seguem
# a regra geral de colunas_visiveis.
_SEMPRE_VISIVEIS = ("NF", "EM ABERTO")


def colunas_visiveis(itens: list[ComposicaoItem]) -> list[str]:
    """As colunas da composicao que a tela mostra pra estes itens.
    Regra geral: a coluna aparece se ALGUMA linha visivel tem dado nela --
    data/idade presente (idade 0 e' dado) ou dinheiro != 0; senao some. NF e
    EM ABERTO ficam sempre. Comparacao, nao conta. O TOTAL usa a mesma lista;
    o Excel usa composicao_celulas inteira -- la' todas ficam."""
    celulas = composicao_celulas(itens)
    if not celulas:
        return []
    return [c for c in celulas[0]
            if c in _SEMPRE_VISIVEIS or any(_tem_dado(l[c]) for l in celulas)]


# Colunas que so' aparecem com "Mostrar todas as colunas". A "Idade"
# saiu da visao padrao porque a 1200px, com a sidebar aberta, a tabela de um caso no
# lote ainda rolava de lado com ela (medido). A
# informacao continua: no toggle e no Excel (que tem todas as colunas).
SO_COM_TODAS_AS_COLUNAS = ("Idade (dias)",)


def colunas_da_tela(itens: list[ComposicaoItem], todas: bool) -> list[str]:
    """As colunas que a TELA mostra: as de colunas_visiveis, menos as que so'
    entram com o toggle."""
    visiveis = colunas_visiveis(itens)
    if todas:
        return visiveis
    return [c for c in visiveis if c not in SO_COM_TODAS_AS_COLUNAS]


def _tem_dado(valor) -> bool:
    if isinstance(valor, Decimal):
        return valor != Decimal("0.00")
    return valor is not None


# Texto de GENTE pra regra de inferencia que ligou a quitacao. Plural na
# frase, nao aqui.
_REGRA_CASAMENTO = {
    RegraCasamento.VALOR_DECLARADO: "pelo valor declarado da série",
    RegraCasamento.SERIE_ORDINAL: "pela continuidade da série de parcelas",
}


# texto de GENTE pro criterio de desempate do passe 2b. Vive em app/,
# nunca no core -- o core devolve o enum.
_CRITERIO_DESEMPATE = {
    CriterioDesempate.UNICA_EM_ABERTO: "única candidata ainda em aberto",
    CriterioDesempate.DATA_MAIS_ANTIGA: "título mais antigo em aberto",
}


def notas_composicao_texto(itens: list[ComposicaoItem], *,
                           linha_anterior: bool = True) -> list[str]:
    """Notas informativas sob a tabela, em texto CRU: baixa
    parcial com o rotulo da literatura contabil (baixa total OU parcial, Lei
    6.404 art. 180 — nunca 'parcela 1 de 2') e quitacao com arredondamento
    (residuo negativo dentro da tolerancia; a decisao vive no modelo, aqui
    so' se le e formata). Mesma ordem da tabela (mais antiga no topo).
    Variante crua: a exportacao consome DAQUI — planilha nao e markdown."""
    notas: list[str] = []
    for i in sorted(itens, key=_idade_key):
        # A linha agregada se EXPLICA. Dois numeros, ambos lidos de campo
        # (trazido = valor_compra; sem detalhe = saldo_aberto) -- o que o
        # periodo quitou continua nas colunas do meio, e nenhuma soma nasce aqui.
        # A TELA pede sem esta nota (linha_anterior=False) -- os
        # dois numeros ja estao na linha logo acima (Valor compra / EM ABERTO)
        # e o fato que a linha nao mostra ("sem detalhe de notas neste
        # razao") vive em Observacoes, que a triagem conta. O Excel mantem.
        if i.origem is Origem.SALDO_ANTERIOR and linha_anterior:
            notas.append(
                f"{ROTULO_ANTERIOR}: R$ {moeda_br(i.valor_compra)} de saldo "
                f"trazido do período anterior; R$ {moeda_br(i.saldo_aberto)} "
                f"ainda sem detalhe")
        # O que o CONTADOR decidiu vale pra QUALQUER origem — linha criada
        # a mao e o "(anterior)" tambem recebem alocacao, entao estas duas notas
        # ficam ANTES do gate de COMPRA_PERIODO das notas automaticas.
        if i.origem is Origem.ALOCACAO_MANUAL:
            notas.append(f"{i.nf_numero}: linha criada à mão nesta sessão")
        if i.quitacoes_manuais:
            plural = ("quitações alocadas à mão" if i.quitacoes_manuais > 1
                      else "quitação alocada à mão")
            rotulo = (i.nf_numero if i.nf_numero.startswith("(")
                      else f"NF {i.nf_numero}")
            notas.append(f"{rotulo}: {i.quitacoes_manuais} {plural}")
        if i.origem is not Origem.COMPRA_PERIODO:
            continue
        if i.total_baixado > Decimal("0.00") and i.saldo_aberto > Decimal("0.00"):
            # Rotulo aprovado pela contabilidade: com ele o conferente entende que o
            # lancamento veio do adiantamento a fornecedor. Nao renomear sem voltar a perguntar —
            # a palavra e' o que faz o conferente reconhecer a origem.
            notas.append(
                f"NF {i.nf_numero}: baixa parcial de adiantamento "
                f"({moeda_br(i.total_baixado)} de {moeda_br(i.valor_compra)})")
        if i.quitada_com_arredondamento:
            notas.append(
                f"NF {i.nf_numero}: quitada com arredondamento de "
                f"{moeda_br(-i.saldo_aberto)} (dentro da tolerância de "
                f"centavos)")
        # Onde a maquina ESCOLHEU (desempate), e nao apenas reconheceu.
        # Um criterio por nota -- contagens de criterios distintos nao se somam.
        for criterio, qtd in Counter(i.desempates).items():
            plural = "quitações casadas" if qtd > 1 else "quitação casada"
            notas.append(
                f"NF {i.nf_numero}: {qtd} {plural} por desempate "
                f"({_CRITERIO_DESEMPATE[criterio]})")
        # Irmao do desempate -- ligacao por inferencia declarada
        for regra, qtd in Counter(i.por_regra).items():
            plural = "quitações casadas" if qtd > 1 else "quitação casada"
            notas.append(f"NF {i.nf_numero}: {qtd} {plural} "
                         f"{_REGRA_CASAMENTO[regra]}")
    return notas


def notas_composicao(itens: list[ComposicaoItem]) -> list[str]:
    """As mesmas notas, escapadas pro markdown da tela (st.caption)."""
    return [markdown_seguro(nota) for nota in notas_composicao_texto(itens)]


def itens_da_tabela(res) -> list[ComposicaoItem]:
    """Tudo que a tabela da composicao mostra: o que esta EM ABERTO mais as NFs
    que FECHARAM no periodo (EM ABERTO 0,00) — a foto completa numa tabela so'.

    As quitadas nao tem secao/expander proprio. O canal do
    core continua separado (`itens` = o que compoe o saldo; `quitadas` = prova
    de que fecharam) — a JUNCAO e' de apresentacao, e a ordenacao continua sendo
    uma so' (idade, mais antiga no topo), aplicada em `composicao_celulas`.
    Consumida pela tela E pela planilha: um caminho so'."""
    return list(res.itens) + list(res.quitadas)


# === Ponte do saldo ===========================================================
# Usuario: colaborador SEM experiencia contabil (premissa fixa do projeto). O
# caminho do saldo anterior + compras ate o Dominio, na ordem em que se faz a
# conta no papel. Os numeros vem PRONTOS do core (res.ponte); aqui so' rotulo,
# operador e formato. Na PLANILHA (auditoria) a linha zerada aparece; na tela
# so' com o toggle "Mostrar todas as linhas".

# (rotulo, campo da PonteSaldo, rotulo quando o liquido vem NEGATIVO). So' as
# duas linhas de decisao do contador tem sinal: credito alocado entra
# negativo no core e a tela troca o operador em vez de imprimir "(-) -80,00".
_LINHAS_PONTE = (
    ("Saldo anterior", "saldo_anterior", None),
    ("(+) Compras do período", "total_compras", None),
    ("(+) Transferências de outra conta do fornecedor",
     "total_transferencias", None),
    ("(-) Pagamentos casados", "total_pago", None),
    ("(-) Retenções", "total_retido", None),
    ("(-) Baixas de adiantamento", "total_baixa_adiantamento", None),
    ("(-) Alocado à mão", "total_alocado_manual", "(+) Alocado à mão"),
    # O topo chega no aberto NF a NF; o que o corte por saldo
    # zero tirou sai pelo LIQUIDO do que ficou sem NF no periodo zerado. Sem a
    # palavra "bloco": o contador le "periodo ja zerado" e sabe o que e'.
    ("(=) Em aberto NF a NF", "total_em_aberto_nf_a_nf", None),
    ("(-) Pagamentos sem NF em período já zerado",
     "total_compensado_saldo_zero",
     "(+) Créditos sem NF em período já zerado"),
    ("(=) Em aberto pela composição", "total_em_aberto", None),
    # Sem "balde" -- tela e planilha com a mesma palavra
    ("(-) Débitos sem destino", "balde_debitos", None),
    ("(+) Créditos sem destino", "balde_creditos", None),
    ("(-) Declarado fora da composição", "total_fora_composicao",
     "(+) Declarado fora da composição"),
    ("(=) Saldo final apurado", "saldo_apurado", None),
    ("Saldo final Domínio", "saldo_dominio", None),
)


def ponte_celulas(ponte, banco: bool = False) -> list[dict]:
    """As linhas da ponte com valores NATIVOS (Excel), na ordem do papel."""
    celulas = []
    for rotulo, campo, se_negativo in _LINHAS_PONTE:
        valor = getattr(ponte, campo)
        if se_negativo is not None and valor < Decimal("0.00"):
            # troca de SINAL de exibicao, nao conta: o modulo do mesmo
            # numero, com o operador que diz o que ele faz no saldo
            rotulo, valor = se_negativo, -valor
        if banco and rotulo == "Saldo final Domínio":
            rotulo = "Saldo final calculado"
        celulas.append({"Linha": rotulo, "Valor": valor})
    return celulas


def ponte_linhas(ponte, banco: bool = False) -> list[dict]:
    """A mesma ponte em texto (tela)."""
    return _linhas_de_texto(ponte_celulas(ponte, banco=banco))


# A ponte da TELA, pra quem nao e' da area. A do Excel (ponte_celulas)
# continua completa -- la e' documento de auditoria.
_EM_ABERTO_NF_A_NF = "(=) Em aberto NF a NF"
_SEM_NOTA_PONTE = {
    "(-) Pagamentos sem NF em período já zerado":
        "(-) Pagamento sem nota que zerou a conta",
    "(+) Créditos sem NF em período já zerado":
        "(+) Crédito sem nota que zerou a conta",
}
_SEMPRE_NA_PONTE = ("(=) Saldo final apurado", "Saldo final Domínio")


def ponte_celulas_tela(res, todas: bool = False, banco: bool = False) -> list[dict]:
    """A ponte da tela: as duas linhas "(=) Em aberto" fundidas (fica so' a da
    composicao; o pagamento sem nota entra direto, com o nome que o expander
    do periodo zerado usa) e, por padrao, so' as linhas com valor -- mais o
    apurado e o Dominio, que fecham a conta. `todas=True` e' o toggle."""
    celulas = []
    for c in ponte_celulas(res.ponte):
        if c["Linha"] == _EM_ABERTO_NF_A_NF:
            continue
        linha = _SEM_NOTA_PONTE.get(c["Linha"], c["Linha"])
        if (c["Linha"] in _SEM_NOTA_PONTE and res.fechado is not None
                and res.fechado.blocos):
            # O MESMO nome do expander, com plural (6 pagamentos num
            # caso nao sao "pagamento ... zerou")
            linha = f"{linha[:4]}{titulo_fechado(res.fechado)}"
        if (not todas and c["Valor"] == Decimal("0.00")
                and linha not in _SEMPRE_NA_PONTE):
            continue
        if banco and linha == "Saldo final Domínio":
            linha = "Saldo final calculado"
        celulas.append({"Linha": linha, "Valor": c["Valor"]})
    return celulas


def ponte_linhas_tela(res, todas: bool = False, banco: bool = False) -> list[dict]:
    return _linhas_de_texto(ponte_celulas_tela(res, todas, banco=banco))


# O que o balde ainda pesa, nunca como R$ negativo. Balde so'
# com credito tinha diferenca negativa ("R$ -187,40"); misto mostrava o
# liquido. Os dois lados vem PRONTOS do core (ponte.balde_debitos/creditos):
# aqui so' se escolhe a frase. So' debito: o texto de sempre.
def _lados_do_balde(ponte) -> tuple[Decimal, Decimal]:
    zero = Decimal("0.00")
    if ponte is None:
        return zero, zero
    return ponte.balde_debitos, ponte.balde_creditos


def descricao_sem_destino(ponte) -> str | None:
    """"R$ D" / "um crédito de R$ C" / "R$ D em débitos e R$ C em créditos".
    None quando o balde nao tem credito: o chamador usa o texto de sempre."""
    debitos, creditos = _lados_do_balde(ponte)
    if creditos == Decimal("0.00"):
        return None
    if debitos == Decimal("0.00"):
        return f"um crédito de R$ {moeda_br(creditos)}"
    return (f"R$ {moeda_br(debitos)} em débitos e R$ {moeda_br(creditos)} "
            f"em créditos")


def ponte_curta_do_total(res, banco: bool = False) -> str | None:
    """A ponte em UMA linha, logo abaixo do total -- do "Total em
    aberto" ao saldo do Dominio sem abrir a ponte: "+ crédito sem destino
    R$ X = saldo no Domínio R$ Y" (debito entra com "-"). Texto CRU: comeca
    com + ou -, entao quem injeta em markdown escapa o primeiro caractere
    (senao vira item de lista).

    So' existe quando a conta e' exatamente essa: balde com item, nada
    declarado fora da composicao e diferenca zero (comparacoes de campos
    prontos do core). Fora disso, o "=" mentiria -- a ponte completa explica."""
    ponte = res.ponte
    zero = Decimal("0.00")
    if (not res.balde or ponte is None or ponte.diferenca != zero
            or ponte.total_fora_composicao != zero):
        return None
    lancamentos = [l for item in res.balde for l in item.lancamentos]
    termos = []
    for sinal, palavra, valor, do_lado in (
            ("-", "débito", ponte.balde_debitos, lambda l: l.debito > zero),
            ("+", "crédito", ponte.balde_creditos, lambda l: l.credito > zero)):
        if valor == zero:
            continue
        plural = "s" if sum(1 for l in lancamentos if do_lado(l)) > 1 else ""
        termos.append(f"{sinal} {palavra}{plural} sem destino "
                      f"R$ {moeda_br(valor)}")
    if not termos:
        return None
    origem = "saldo calculado" if banco else "saldo no Domínio"
    return (f"{' '.join(termos)} = {origem} "
            f"R$ {moeda_br(ponte.saldo_dominio)}")


def titulo_ponte(res) -> str:
    """O titulo do expander JA e' a resposta: fecha em quanto, ou por quanto
    nao fecha. Status do veredito, numeros do core. Segue a
    regra da marca -- "fecha" sozinho so' com balde vazio; com item sem
    destino (ou declarado fora), o titulo diz quanto."""
    severidade, _ = status_ponte(res)
    ponte = res.ponte
    if severidade == PONTE_DIVERGE:
        return (f"Ponte do saldo — não fecha: diferença de "
                f"R$ {moeda_br(ponte.diferenca)}")
    titulo = f"Ponte do saldo — fecha em R$ {moeda_br(ponte.saldo_apurado)}"
    if severidade == PONTE_PENDENTE:
        if res.balde:
            lados = descricao_sem_destino(ponte)
            if lados is not None:                       # ha credito
                return f"{titulo}, com {lados} sem destino"
            return (f"{titulo}, com R$ {moeda_br(ponte.balde_liquido)} sem "
                    f"destino")
        return (f"{titulo}, com R$ {moeda_br(ponte.total_fora_composicao)} "
                f"declarado fora da composição")
    return titulo


def e_subtotal(rotulo: str) -> bool:
    """As linhas (=) sao RESULTADO, nao movimento: a tela e a planilha as
    destacam pra o olho achar onde a conta para."""
    return rotulo.startswith("(=)")


# severidades do status da ponte -- a tela mapeia pra cor (verde / a do
# INCOMPLETO / vermelho)
PONTE_OK = "OK"
PONTE_PENDENTE = "PENDENTE"
PONTE_DIVERGE = "DIVERGE"


def status_ponte(res) -> tuple[str, str]:
    """O status da ponte e' o do VEREDITO: sem juiz proprio, mapeado do
    nivel do self_check_composicao.
      OK         -> "OK" verde. So' com balde vazio e nada declarado fora:
                    e' o unico caso em que a conta esta de fato conciliada.
      INCOMPLETO -> "Fecha — R$ X sem destino": a identidade
                    fecha, mas "OK" verde com balde cheio passava a impressao
                    de conta conciliada. Sem balde, o que sobra e' a ressalva
                    do que foi declarado fora da composicao.
      ERRO       -> "DIVERGE <diferenca>".
    A diferenca e' sempre impressa quando nao e' zero -- o que a tolerancia
    de centavos aceitou aparece escrito, nunca escondido."""
    check = next((a for a in res.achados
                  if a.codigo == "self_check_composicao"), None)
    ponte = res.ponte
    diferenca = ponte.diferenca
    if check is not None and check.nivel is Nivel.ERRO:
        return PONTE_DIVERGE, f"DIVERGE {moeda_br(diferenca)}"
    if check is not None and check.nivel is Nivel.INCOMPLETO:
        lados = descricao_sem_destino(ponte) if res.balde else None
        if lados is not None:                           # ha credito
            # "um crédito de" -> "crédito de" (o status e' rotulo, nao frase)
            texto = f"Fecha — {lados.removeprefix('um ')} sem destino"
        else:
            # A marca fala como a linha da ponte -- "sem destino"
            texto = (f"Fecha — R$ {moeda_br(ponte.balde_liquido)} sem destino"
                     if res.balde else
                     f"Fecha — R$ {moeda_br(ponte.total_fora_composicao)} "
                     f"declarado fora da composição")
        if diferenca != Decimal("0.00"):
            texto += (f"; diferença de {moeda_br(abs(diferenca))} dentro da "
                      f"tolerância")
        return PONTE_PENDENTE, texto
    return PONTE_OK, "OK"


def nota_fora_da_tabela(totais) -> str | None:
    """A nota que explica por que o TOTAL de "Valor compra"/"Total pago" nao
    bate com a ponte. So' existe quando um deles difere (a diferenca vem
    MEDIDA do core); sem diferenca, sem nota."""
    difere = [(nome, valor) for nome, valor in
              (("Valor compra", totais.compra_fora_da_tabela),
               ("Total pago", totais.pago_fora_da_tabela))
              if valor != Decimal("0.00")]
    if not difere:
        return None
    # UMA frase, sem "ponte" nem "consumiu": o que aconteceu com o
    # saldo anterior e onde ele nao aparece
    valores = {valor for _, valor in difere}
    if len(difere) == 2 and len(valores) == 1:
        return (f"O saldo anterior de R$ {moeda_br(difere[0][1])} foi pago no "
                f"período: a linha zerou e fica fora dos totais de Valor "
                f"compra e Total pago da tabela.")
    if len(difere) == 1:
        nome, valor = difere[0]
        return (f"O saldo anterior pago no período fica fora do total de "
                f"{nome} da tabela (R$ {moeda_br(valor)}): a linha zerou.")
    partes = " e ".join(f"R$ {moeda_br(valor)} em {nome}"
                        for nome, valor in difere)
    return (f"O saldo anterior pago no período fica fora dos totais da "
            f"tabela ({partes}): a linha zerou.")


# === Fechado por saldo zero =================================================
# Usuario: colaborador SEM experiencia contabil (premissa fixa do projeto). O
# que o corte tirou da composicao, como INFORMACAO: o
# saldo zerou e o total se compensa, mas o total nao prova que cada NF foi
# paga. Duas tabelas -- as NFs (e a linha do saldo anterior) e os lancamentos
# sem NF -- cada linha com a data em que o saldo zerou depois dela.

TITULO_FECHADO = "Fechado por saldo zero"


def fechado_celulas_nfs(fechado) -> list[dict]:
    """As colunas da composicao + "Zerou em", valores NATIVOS (Excel). Mesma
    definicao de coluna da tabela principal (_linha_composicao)."""
    return [{**celula, "Zerou em": fechado.zerou_em[item.nf_numero].data}
            for celula, item in zip(composicao_celulas(fechado.itens),
                                    sorted(fechado.itens, key=_idade_key))]


def fechado_celulas_balde(fechado) -> list[dict]:
    """Os lancamentos sem NF do periodo zerado, em ordem de data. Le o campo
    do lado que tem valor (lado_e_quantia), nunca soma."""
    celulas = []
    for item, l in _balde_cronologico(fechado.balde):
        lado, quantia = lado_e_quantia(l)
        celulas.append({
            "Lote": l.numero,
            "Data": l.data,
            "Lado": lado,
            "Valor": quantia,
            "Histórico": l.historico,
            "Zerou em": fechado.zerou_em[item.identificador].data,
        })
    return celulas


# --- a mesma secao pra quem NAO e' da area ----------------------------------
# Expander fechado, uma frase por bloco no modelo "Em <data> entrou um
# pagamento de R$ X sem numero de nota. Ele bate exatamente com N notas...".
# Somas e diferenca vem do BlocoZerado (core); aqui so' palavras.

def _sao_pagamentos(itens) -> bool:
    """"pagamento" so' quando o motor RECONHECEU o lancamento como pagamento
    (so' faltou a nota); historico nao reconhecido e' "lancamento" -- pode ser
    tarifa, nao pagamento, e a tela nao afirma o que nao sabe."""
    return all(i.motivo is not MotivoRevisao.NAO_CLASSIFICADO
               and i.motivo is not MotivoRevisao.RECEBIMENTO
               and i.motivo is not MotivoRevisao.ESTORNO_SEM_PAR
               and i.motivo is not MotivoRevisao.LADO_INESPERADO
               and all(l.debito > Decimal("0.00") for l in i.lancamentos)
               for i in itens)


def titulo_fechado(fechado) -> str:
    sem_nota = [i for b in fechado.blocos for i in b.balde]
    plural = len(sem_nota) != 1
    palavra = "Pagamento" if _sao_pagamentos(sem_nota) else "Lançamento"
    return (f"{palavra}s sem nota que zeraram a conta" if plural
            else f"{palavra} sem nota que zerou a conta")


def abrir_fechado(fechado) -> bool:
    """Fechado por padrao; ABERTO quando algum bloco nao bate exato -- ai e'
    pendencia de verdade, nao informacao."""
    return any(not b.bate for b in fechado.blocos)


def _quando_entrou(bloco) -> tuple[str, str]:
    """(abertura da frase, palavra no singular) -- "Em 05/01 entrou um
    pagamento de R$ X" ou "Entre 03/01 e 06/01 entraram 2 pagamentos..."."""
    palavra = "pagamento" if _sao_pagamentos(bloco.balde) else "lançamento"
    datas = sorted(l.data for i in bloco.balde for l in i.lancamentos)
    valor = f"R$ {moeda_br(bloco.total_sem_nf)}"
    if len(datas) == 1:
        return (f"Em {data_br(datas[0])} entrou um {palavra} de {valor} sem "
                f"número de nota"), palavra
    periodo = (f"Em {data_br(datas[0])}" if datas[0] == datas[-1]
               else f"Entre {data_br(datas[0])} e {data_br(datas[-1])}")
    return (f"{periodo} entraram {len(datas)} {palavra}s sem número de nota, "
            f"somando {valor}"), palavra


def _notas_do_bloco(bloco, artigo_plural: str = "") -> tuple[str, bool]:
    """(as notas do bloco por extenso, se e' plural). "a NF 5001", "2 notas",
    "as 2 notas" (com artigo_plural="as "), "+ o saldo anterior"."""
    notas = [i for i in bloco.itens if i.origem is not Origem.SALDO_ANTERIOR]
    partes = []
    if len(notas) == 1:
        partes.append(f"a {nome_de_linha(notas[0].nf_numero)}")
    elif notas:
        partes.append(f"{artigo_plural}{len(notas)} notas")
    if len(notas) != len(bloco.itens):
        partes.append("o saldo anterior")
    return " e ".join(partes), len(notas) > 1 or len(partes) > 1


def frase_bloco(bloco) -> str:
    entrou, _ = _quando_entrou(bloco)
    data_zero = data_br(bloco.zero.data)
    um = len([l for i in bloco.balde for l in i.lancamentos]) == 1
    if bloco.bate:
        notas, _ = _notas_do_bloco(bloco)
        return (f"{entrou}. {'Ele bate' if um else 'Eles batem'} exatamente "
                f"com {notas} e em {data_zero} a conta ficou zerada. O total "
                f"fecha; a quitação nota a nota não foi comprovada.")
    fim = f"Em {data_zero} a conta ficou zerada. Não bate exato."
    if not bloco.itens:
        return (f"{entrou}, e nenhuma nota em aberto até ali fecha com "
                f"{'ele' if um else 'eles'}. {fim}")
    notas, plural = _notas_do_bloco(bloco, artigo_plural="as ")
    return (f"{entrou}, mas {notas} em aberto até ali "
            f"{'somam' if plural else 'soma'} R$ {moeda_br(bloco.total_aberto)} "
            f"(diferença de R$ {moeda_br(abs(bloco.diferenca))}). {fim}")


# Tabela ESTATICA de leitura -- a mesma tecnica da antiga tabela propria do
# balde (que as caixinhas substituiram). Volta pro
# periodo zerado porque ali o st.table nao alinha moeda a direita (ignora o
# Styler) e o st.dataframe corta o historico. Sem sort, sem filtro: sao poucas
# linhas de prova. Nenhuma linha em branco no HTML: ela encerraria o bloco
# HTML do markdown e o resto sairia como texto.
_CSS_LEITURA = """<style>
.tabela-leitura { border-collapse: collapse; border: 0; margin-bottom: 1rem; }
.tabela-leitura.larga { width: 100%; }
.tabela-leitura th, .tabela-leitura td { border: 0; background: transparent; }
.tabela-leitura th { white-space: nowrap; text-align: left; font-size: .8em;
  font-weight: 600; color: rgba(128,128,128,.9); padding: 8px 16px 6px 0;
  border-bottom: 1px solid rgba(128,128,128,.4); vertical-align: bottom; }
.tabela-leitura td { vertical-align: top; padding: 9px 16px 9px 0;
  border-bottom: 1px solid rgba(128,128,128,.16); white-space: nowrap; }
.tabela-leitura td.txt { white-space: normal; overflow-wrap: break-word;
  line-height: 1.45; }
.tabela-leitura td.estica { width: 99%; }
.tabela-leitura.hist td.txt { font-size: .9em; overflow-wrap: anywhere; }
.tabela-leitura.triagem th { white-space: normal; }
.tabela-leitura th.num, .tabela-leitura td.num { text-align: right; }
</style>"""


def _celula_html(texto) -> str:
    """Escape de HTML + cifrao como entidade: dois R$ nunca viram formula."""
    # Quebra de linha vira espaco -- linha em branco encerraria o
    # bloco HTML do markdown e o resto sairia como markdown vivo
    texto = " ".join(str(texto).splitlines())
    return escape(texto).replace("$", "&#36;")


def _com_pontos_de_quebra(html: str) -> str:
    """Nome de arquivo nao tem espaco: sem ponto de quebra o navegador ou
    estoura a largura ou quebra letra a letra. <wbr> depois de _ . - deixa
    quebrar so' entre pedacos do nome (conferido no navegador)."""
    for c in "_.-":
        html = html.replace(c, c + "<wbr>")
    return html


def historico_html(texto) -> str:
    """O historico INTEIRO como texto literal numa citacao HTML.
    Em markdown, o Streamlit faz titulo ("# ..."), lista, link automatico (URL,
    www., e-mail), emoji (":x:") e icone a partir do dado do arquivo -- medido
    no navegador; escape de markdown nao desliga o link automatico. A celula
    e' a da tabela de leitura (_celula_html: HTML, cifrao e quebra de linha)."""
    return f"<blockquote>{_celula_html(texto)}</blockquote>"


def tabela_html(linhas: list[dict], *, numericas=frozenset({"Valor"}),
                quebra=frozenset({"Histórico"}), estica: str | None = "Histórico",
                variante: str = "hist", larga: bool = False,
                nomes_de_arquivo=frozenset(), ancoras: list[str | None] | None = None) -> str:
    """Linhas de texto -> tabela HTML estatica de LEITURA: `numericas` a
    direita e sem quebra, `quebra` quebrando linha, `estica` ocupando a
    sobra (a tabela vai na largura toda so' quando essa coluna existe). TUDO
    escapado -- historico e erro sao texto cru do arquivo, nunca HTML vivo."""
    if not linhas:
        return ""
    colunas = list(linhas[0])

    def classe(c, *, cabecalho=False):
        if c in numericas:
            return ' class="num"'
        if cabecalho or c not in quebra:
            return ""
        return ' class="txt estica"' if c == estica else ' class="txt"'
    cab = "".join(f"<th{classe(c, cabecalho=True)}>{_celula_html(c)}</th>"
                  for c in colunas)
    def celula(c, valor, ancora):
        texto = _celula_html(valor)
        texto = _com_pontos_de_quebra(texto) if c in nomes_de_arquivo else texto
        partes = (ancora or "").split("-")
        valida = (len(partes) == 3 and partes[0] == "conta"
                  and all(p.isascii() and p.isdigit() for p in partes[1:]))
        if variante == "triagem" and c in {"Arquivo", "Conta"} and valida:
            return f'<a href="#{ancora}">{texto}</a>'
        return texto
    corpo = "".join(
        "<tr>" + "".join(f"<td{classe(c)}>{celula(c, l[c], ancoras[i] if ancoras else None)}</td>"
                         for c in colunas) + "</tr>"
        for i, l in enumerate(linhas))
    largura = " larga" if larga or estica in colunas else ""
    return (f'{_CSS_LEITURA}<table class="tabela-leitura {variante}{largura}">'
            f"<thead><tr>{cab}</tr></thead><tbody>{corpo}</tbody></table>")


def tabela_triagem(linhas: list[dict], com_arquivo: bool = True, *,
                   ancoras: list[str | None] | None = None) -> str:
    """A triagem do lote na tabela de leitura. Oito colunas nao
    cabem numa linha a 1200px com a sidebar aberta (o Fornecedor sozinho chega
    a 60 caracteres): aqui texto e cabecalho QUEBRAM linha e nada e' cortado.
    A ordem ja vem pronta (problema primeiro), entao perder o sort do
    st.dataframe custa pouco. Mesmas colunas, mesmo conteudo."""
    if not com_arquivo:
        linhas = [{k: v for k, v in linha.items() if k != "Arquivo"}
                  for linha in linhas]
    return tabela_html(
        linhas, numericas=frozenset({"Falta alocar", "Itens sem destino",
                                     "Sugeridos"}),
        quebra=frozenset({"Arquivo", "Fornecedor", "Achados"}),
        estica=None, larga=True, variante="triagem",
        nomes_de_arquivo=frozenset({"Arquivo"}), ancoras=ancoras)


def bloco_linhas_nfs(bloco) -> list[dict]:
    """NF | Data | Valor -- so' o que o leitor precisa pra conferir."""
    return [{"NF": rotulo_linha(i.nf_numero), "Data": data_br(i.data_compra),
             "Valor": moeda_br(i.saldo_aberto)}
            for i in sorted(bloco.itens, key=_idade_key)]


def bloco_linhas_sem_nf(bloco) -> list[dict]:
    """Lote | Data | Valor | Historico -- o historico e' a evidencia, CRU: o
    escape e' do formato de saida (tabela_html escapa HTML e cifrao)."""
    return [{"Lote": l.numero, "Data": data_br(l.data),
             "Valor": moeda_br(lado_e_quantia(l)[1]),
             "Histórico": l.historico}
            for _, l in _balde_cronologico(bloco.balde)]


def nota_anterior_fechado(fechado) -> str | None:
    """A linha do saldo anterior que ficou ZERADA no periodo zerado (a baixa
    de um caso): nao e' pendencia, mas nao some -- vira uma frase."""
    anterior = next((i for i in fechado.itens
                     if i.origem is Origem.SALDO_ANTERIOR
                     and i.saldo_aberto == Decimal("0.00")), None)
    if anterior is None or anterior.valor_compra == Decimal("0.00"):
        return None
    zero = fechado.zerou_em[ALVO_ANTERIOR].data
    return (f"O saldo anterior de R$ {moeda_br(anterior.valor_compra)} foi "
            f"quitado antes de a conta zerar em {data_br(zero)}.")


def avisos_fechado(res) -> list[str]:
    """As frases dos alertas do periodo zerado (texto CRU), UMA POR BLOCO com
    pendencia, na ordem da razao."""
    return [frase_achado(a) for a in res.achados
            if a.codigo == "periodo_zerado_com_pendencia"]


# === Placar e decisoes da alocacao manual ====================================
# Usuario: colaborador SEM experiencia contabil (premissa fixa do projeto) --
# a tela inteira fala com quem nao e' da area, decisao inclusive. Texto mostra
# FATO (regra de tela): o que o motor viu e o que nao decidiu, sem instrucao.

def placar_composicao(res) -> dict:
    """Os numeros do topo: composicao x Dominio, delta, e o que falta decidir.

    ZERO aritmetica aqui: total/alvo/gap vem prontos do core, no achado da
    reconciliacao (valores). Esta funcao escolhe rotulo e formato."""
    check = next((a for a in res.achados
                  if a.codigo == "self_check_composicao"), None)
    numeros = check.valores if check else {}
    ressalva = next((a for a in res.achados
                     if a.codigo == "composicao_com_ressalva"), None)
    gap = numeros.get("gap")
    # Com credito no balde, o terceiro numero deixa de ser o liquido
    # (que podia sair negativo): so' credito -> o credito; misto -> os
    # debitos, e o credito vai na linha pequena (delta_extra)
    rotulo, delta, extra = ("Falta alocar",
                            moeda_br(gap) if gap is not None else _VAZIO, None)
    debitos, creditos = _lados_do_balde(res.ponte)
    if res.balde and creditos != Decimal("0.00"):
        if debitos == Decimal("0.00"):
            rotulo, delta = "Crédito sem destino", moeda_br(creditos)
        else:
            rotulo, delta = "Débitos sem destino", moeda_br(debitos)
            extra = f"crédito sem destino R$ {moeda_br(creditos)}"
    return {
        "composicao": moeda_br(numeros["total"]) if numeros else _VAZIO,
        "dominio": moeda_br(numeros["alvo"]) if numeros else _VAZIO,
        "rotulo_delta": rotulo,
        "delta": delta,
        "delta_extra": extra,
        "fechada": bool(numeros) and gap == Decimal("0.00") and not res.balde,
        "itens": len(res.balde),
        "decisoes": len(res.decisoes),
        "ressalva": moeda_br(ressalva.encontrado) if ressalva else None,
    }


def resumo_do_trabalho(res) -> str:
    """A linha que o cabecalho do balde repete (o placar nao e sticky de
    proposito: o olho esta AQUI enquanto se decide)."""
    placar = placar_composicao(res)
    if not res.balde:
        return "Nada em revisão."
    itens = f"{placar['itens']} {'item' if placar['itens'] == 1 else 'itens'}"
    lados = descricao_sem_destino(res.ponte)
    if lados is not None:                               # ha credito
        if lados.startswith("um crédito"):
            return f"Crédito sem destino de R$ {placar['delta']} em {itens}"
        return f"Sem destino: {lados}, em {itens}"
    # mesma palavra do placar: "falta alocar", nao um sinonimo novo
    return f"Falta alocar R$ {placar['delta']} em {itens}"


_DESTINO_TEXTO = {
    DestinoAlocacao.LINHA_ABERTA: "{alvo}",
    DestinoAlocacao.COMPRA_NOVA: "compra nova{rotulo}",
    DestinoAlocacao.FORA_DA_COMPOSICAO: "fora da composição{rotulo}",
}


def _texto_destino(destino: DestinoAlocacao, alvo: str, rotulo: str) -> str:
    alvo_legivel = nome_de_linha(alvo)
    return _DESTINO_TEXTO[destino].format(
        alvo=alvo_legivel, rotulo=f' "{rotulo}"' if rotulo else "")


# --- frases de sugestao: uma funcao por criterio, mesmo padrao de
# _FRASES_ACHADO. O core entrega os numeros em `evidencia`; a conta que
# sustenta a proposta e escrita AQUI, pra o conferente refazer de cabeca antes
# de aceitar. Criterio sem template cai no fallback -- VISIVEL, nunca frase
# pela metade nem excecao.

_TEXTO_SUGESTAO = {
    CriterioSugestao.SERIE_X_VALOR_DECLARADO: lambda s, alvo: (
        f"provável {alvo}: o histórico declara "
        f"{_inteiro(s.evidencia['parcelas'])} x "
        f"R$ {moeda_br(s.evidencia['parcela_declarada'])} = "
        f"R$ {moeda_br(s.evidencia['valor_compra'])}, o valor de compra dela"
        + _ressalva_diferenca(s)),
    CriterioSugestao.CONTINUIDADE_SERIE_ORDINAL: lambda s, alvo: (
        f"provável {alvo}: ela já tem {_inteiro(s.evidencia['casadas'])} "
        f"parcelas de R$ {moeda_br(s.evidencia['parcela'])} casadas por número "
        f"({_inteiro(s.evidencia['primeiro_ordinal'])}ª a "
        f"{_inteiro(s.evidencia['ultimo_ordinal'])}ª) e esta é a "
        f"{_inteiro(s.evidencia['ordinal'])}ª, ainda livre — cabe no saldo em "
        f"aberto de R$ {moeda_br(s.evidencia['saldo_aberto'])}"),
    CriterioSugestao.SERIE_X_SALDO_REMANESCENTE: lambda s, alvo: (
        f"provável {alvo}: a série declarada "
        f"({_inteiro(s.evidencia['parcelas'])} x "
        f"R$ {moeda_br(s.evidencia['parcela_declarada'])} = "
        f"R$ {moeda_br(s.evidencia['saldo_remanescente'])}) bate com o saldo "
        f"em aberto dela" + _entre_candidatas(s) + _ressalva_duplicidade(s)),
}


def _ressalva_diferenca(s) -> str:
    """O pago difere do declarado. E o numero que o contador confere ANTES de
    aceitar: aceitar aloca o PAGO, nao o declarado, e pode estourar o titulo no
    fim da serie (o `possivel_juros_manual` cobre, com origem visivel).

    A causa nao se afirma alem do que os numeros mostram: pago a MAIS sugere
    juros de atraso; pago a MENOS pode ser desconto ou retencao, e a frase nao
    escolhe por conta propria (mesma taxonomia conservadora do possivel_desconto)."""
    dif = s.evidencia.get("diferenca")
    if not dif:                             # ausente ou 0,00: nada a ressalvar
        return ""
    pago = f"Pago R$ {moeda_br(s.evidencia['pago'])}"
    if dif > 0:
        return (f". {pago} — R$ {moeda_br(dif)} acima da parcela declarada "
                f"(provável juros de atraso)")
    return (f". {pago} — R$ {moeda_br(-dif)} abaixo da parcela declarada "
            f"(possível desconto concedido ou retenção não lançada)")


def _ressalva_duplicidade(s) -> str:
    """A MESMA parcela declarada 2+ vezes na razao. Vai colado na proposta, na
    caixinha onde o contador decide — o alerta de possivel duplicidade no
    painel continua existindo, mas ele nao chega na hora do clique."""
    quantas = s.evidencia.get("ocorrencias_da_serie")
    if not quantas:
        return ""
    return (f". Esta parcela aparece {_inteiro(quantas)} vezes na "
            f"razão — há alerta de possível duplicidade")


def _inteiro(v: Decimal) -> str:
    """Contagem (numero de parcelas), nao dinheiro: sai sem centavos."""
    return str(int(v))


def _entre_candidatas(s) -> str:
    """O criterio de unicidade so convence com a descartada a vista."""
    outras = [c for c in s.candidatos if c != s.alvo]
    return f" — descartada(s): {', '.join(outras)}" if outras else ""


def frase_sugestao(s) -> str:
    """Frase de EXIBICAO da sugestao (texto cru: a tela escapa na injecao, o
    Excel usa direto). Consumida pela caixinha, pela coluna do balde e pela
    triagem — uma frase so, derivada de `item.sugestao`."""
    alvo = nome_de_linha(s.alvo)
    template = _TEXTO_SUGESTAO.get(s.criterio)
    if template is None:
        return f"destino provável: {alvo}"
    try:
        return template(s, alvo)
    except (KeyError, TypeError, AttributeError):
        return f"destino provável: {alvo}"     # numeros ausentes: nunca quebra


def decisoes_celulas(decisoes: list) -> list[dict]:
    """As decisoes APLICADAS com valores NATIVOS, pro Excel (o conferente soma
    e filtra em cima). Historico integral: e a evidencia que vai pro cliente
    junto com a decisao."""
    celulas: list[dict] = []
    for d in decisoes:
        for l in d.item.lancamentos:
            lado, quantia = lado_e_quantia(l)
            celulas.append({
                "Lote": l.numero,
                "Data": l.data,
                "Lado": lado,
                "Valor": quantia,
                "Decisão": _texto_destino(d.destino, d.alvo, ""),
                "Justificativa": d.rotulo or _VAZIO,
                # Origem so se declara quando existe -- decisao propria do
                # conferente nao ganha carimbo
                "Origem": ("sugestão do motor aceita"
                           if d.criterio_sugerido is not None else _VAZIO),
                "Histórico": l.historico,
            })
    return celulas


def decisao_texto(linha: dict) -> str:
    """Texto cru da linha de decisao; a tela escapa ao exibir."""
    if linha.get("item_ausente", False):
        texto = "lançamento não encontrado nesta conferência"
    else:
        texto = (f"{linha['lote']} · {linha['data']} · {linha['lado']} "
                 f"{linha['valor']}")
    return f"{texto}  →  {linha['destino']}" if linha["destino"] else texto


def decisoes_linhas(alocacoes: list, res) -> list[dict]:
    """Uma linha por alocacao FEITA NA SESSAO, na ordem em que o contador
    decidiu — aplicada ou recusada. A recusada aparece no MESMO lugar, com o
    motivo do core, porque e ali que esta o botao de desfazer.

    `indice` e a posicao na lista da sessao: e o que o desfazer remove."""
    erros = list(res.erros_alocacao)
    aplicadas = {d.item.identificador: d for d in res.decisoes}
    linhas: list[dict] = []
    for indice, alocacao in enumerate(alocacoes):
        erro = next((e for e in erros if e.alocacao == alocacao), None)
        decisao = aplicadas.get(alocacao.item_id)
        if erro is not None:
            erros.remove(erro)
            linha = {"indice": indice, "lote": _VAZIO, "data": _VAZIO,
                     "lado": _VAZIO, "valor": _VAZIO,
                     "destino": _texto_destino(alocacao.destino,
                                               alocacao.alvo,
                                               alocacao.rotulo),
                     "erro": erro.mensagem}
            item = next((i for i in res.balde
                         if i.identificador == alocacao.item_id), None)
            if item is None and decisao is not None:
                item = decisao.item
            if item is None and res.fechado is not None:
                item = next((i for i in res.fechado.balde
                             if i.identificador == alocacao.item_id), None)
            if item is None and erro.codigo == "ITEM_INEXISTENTE":
                linha["item_ausente"] = True
            elif item is not None:
                lancamento = item.lancamentos[0]
                lado, quantia = lado_e_quantia(lancamento)
                linha.update(lote=lancamento.numero,
                             data=data_br(lancamento.data),
                             lado=lado, valor=moeda_br(quantia))
            linhas.append(linha)
            continue
        if decisao is None:                # nao deveria acontecer; nunca sumir
            linhas.append({"indice": indice, "lote": _VAZIO, "data": _VAZIO,
                           "lado": _VAZIO, "valor": _VAZIO,
                           "destino": _VAZIO,
                           "erro": "alocação sem efeito"})
            continue
        lancamento = decisao.item.lancamentos[0]
        lado, quantia = lado_e_quantia(lancamento)
        linhas.append({
            "indice": indice,
            "lote": lancamento.numero,
            "data": data_br(lancamento.data),
            "lado": lado,
            "valor": moeda_br(quantia),
            "destino": _texto_destino(decisao.destino, decisao.alvo,
                                      decisao.rotulo),
            "erro": None,
        })
    return linhas


# tabela UNICA por MotivoRevisao (#39): rotulo de CELULA (a tabela escaneia),
# TITULO da expansao (meio-termo, identificavel por leigo) e o texto de GENTE
# (1 frase de diagnostico + 1 de acao, parametrizavel com dados do item).
# Motivo novo = 1 linha aqui, nao 3 dicts distantes. Vive em app/, nunca no core.
_Motivo = namedtuple("_Motivo", "celula titulo humano")
_MOTIVOS = {
    MotivoRevisao.SEM_VINCULO: _Motivo(
        "Sem NF", "Sem NF correspondente",
        "Pagamento sem número de NF no histórico e sem NF em aberto de valor "
        "compatível nesta conta."),
    MotivoRevisao.EMPATE: _Motivo(
        "Empate", "Empate entre NFs",
        "Pagamento identificado, mas o valor casa com mais de uma NF em aberto "
        "({nfs_candidatas}); o motor não escolhe entre elas."),
    MotivoRevisao.NAO_CLASSIFICADO: _Motivo(
        "Não reconhecido", "Histórico não reconhecido",
        "Histórico não reconhecido pelos padrões da ferramenta."),
    MotivoRevisao.ESTORNO_SEM_PAR: _Motivo(
        "Estorno sem par", "Estorno sem a operação correspondente",
        "Histórico reconhecido como estorno, mas a operação que ele reverte "
        "não está nos itens sem destino — ou já foi conciliada com uma NF, ou não está "
        "nesta razão."),
    MotivoRevisao.MULTI_NF_NAO_CONFERE: _Motivo(
        "Soma não confere", "Soma das NFs não confere",
        "Pagamento cita mais de uma NF ({nfs_candidatas}), mas não foi "
        "possível casar: {detalhe}."),
    # O destino e' o balde por decisao contabil. Na tela, SO' o fato e o
    # limite do motor -- a leitura "mercadoria
    # devolvida sem troca" e' hipotese, e o historico ja diz "recebimento"
    MotivoRevisao.RECEBIMENTO: _Motivo(
        "Recebimento", "Recebimento do fornecedor",
        "Dinheiro recebido do fornecedor, sem nota fiscal. O motor não decide "
        "este tipo de operação."),
}


# Historico com o valor no lado oposto ao do tipo. O nome e' o
# FATO concreto, pelo tipo que o historico declarou (o core manda em
# ItemRevisao.tipo_declarado); a frase diz o lado em que o tipo entra e o que
# o motor fez com o valor -- so' fato, regra de tela.
_MOTIVOS_LADO = {
    Tipo.COMPRA: _Motivo(
        "Compra lançada a débito", "Compra lançada a débito",
        "Histórico de compra com o valor no débito. Compra entra no crédito: "
        "o motor não soma este valor a nenhuma NF."),
    Tipo.PAGAMENTO: _Motivo(
        "Pagamento lançado a crédito", "Pagamento lançado a crédito",
        "Histórico de pagamento com o valor no crédito. Pagamento entra no "
        "débito: o motor não abate este valor de nenhuma NF."),
    Tipo.RETENCAO: _Motivo(
        "Retenção lançada a crédito", "Retenção lançada a crédito",
        "Histórico de retenção com o valor no crédito. Retenção entra no "
        "débito: o motor não abate este valor de nenhuma NF."),
    Tipo.BAIXA_ADIANTAMENTO: _Motivo(
        "Baixa de adiantamento lançada a crédito",
        "Baixa de adiantamento lançada a crédito",
        "Histórico de baixa de adiantamento com o valor no crédito. Baixa "
        "entra no débito: o motor não abate este valor de nenhuma NF."),
}


# O historico CITA um numero, que nao tem compra nesta conta --
# "sem numero de NF no historico" seria falso. So' fato (regra de tela).
_SEM_VINCULO_CITADA = ("Pagamento cita a NF {nf}, que não tem compra nesta "
                       "conta no período do arquivo, e não há NF em aberto de "
                       "valor compatível.")


def _motivo_de(item: ItemRevisao) -> "_Motivo | None":
    """Os textos do motivo do item -- fonte UNICA da tela, da tabela, da
    contagem e do Excel. Lado inesperado e' nomeado pelo tipo declarado; sem
    ele (item montado a mao), None -> fallback visivel de sempre."""
    if item.motivo is MotivoRevisao.LADO_INESPERADO:
        return _MOTIVOS_LADO.get(item.tipo_declarado)
    return _MOTIVOS.get(item.motivo)

# Decisao contabil: credito NAO RECONHECIDO na conta do
# fornecedor e dinheiro VOLTANDO. A leitura mais provavel: devolucao de
# mercadoria sem troca por outra. LEITURA, nao classificacao — ha
# subjetividade neste tipo de operacao, e por isso o item continua no balde
# pra analise humana. Frase presa ao LADO (credito), nunca ao historico: o dia
# em que o padrao do PIX for reconhecido, este texto some sozinho com o motivo.
_LEITURA_CREDITO = (" Crédito na conta do fornecedor é dinheiro voltando: "
                    "possível devolução em dinheiro (mercadoria devolvida sem "
                    "troca). O motor não decide este tipo de operação.")


def _so_credito(item: ItemRevisao) -> bool:
    """Item cujos lancamentos sao TODOS credito. Leitura de campo, sem soma."""
    return bool(item.lancamentos) and all(l.credito > 0 for l in item.lancamentos)


def motivo_humano(item: ItemRevisao) -> str:
    """O que o revisor le no item do balde: por que o motor nao decidiu sozinho
    e o que fazer. Motivo sem texto mapeado cai na mensagem tecnica do motor --
    fallback VISIVEL, nunca tela em branco. O detalhe do multi-NF formata os
    numeros que o core entregou em item.valores (#34: soma apurada em BR)."""
    m = _motivo_de(item)
    if m is None:
        return item.mensagem or item.motivo.value
    if item.motivo is MotivoRevisao.SEM_VINCULO and item.nf_citada:
        return _SEM_VINCULO_CITADA.format(nf=item.nf_citada)
    if item.motivo is MotivoRevisao.NAO_CLASSIFICADO and _so_credito(item):
        return m.humano + _LEITURA_CREDITO
    if item.valores and "soma" in item.valores:
        detalhe = (f"soma dos saldos das NFs citadas "
                   f"R$ {moeda_br(item.valores['soma'])}, pagamento "
                   f"R$ {moeda_br(item.valores['pagamento'])}")
    else:
        detalhe = item.mensagem or _VAZIO
    return m.humano.format(nfs_candidatas=", ".join(item.candidatos) or _VAZIO,
                           detalhe=detalhe)


# O cabecalho ORIENTA, nao compete (1 linha sempre, peso discreto,
# sem caixa alta); dado com respiro; grade SO horizontal e leve (o `border: 0`
# em th/td mata a grade pesada que o tema do Streamlit injeta em tabela de
# markdown — era ela a caixa em volta de cada celula do print). Colunas
# curtas no minimo necessario (nowrap + width 1px = encolhe ao conteudo);
# o historico absorve TODO o resto e quebra limpo. Zebra sutil pra leitura
# de linha longa nao se perder; cores herdadas do tema (claro/escuro).
def lado_e_quantia(l: Lancamento) -> tuple[str, Decimal]:
    """Le o lado que TEM valor (debito ou credito) -- escolha de campo, nunca
    aritmetica de dinheiro na tela. Devolve (rotulo por extenso, Decimal cru).
    Fonte unica da regra de leitura do lado pra tabela e caixinhas (#12).
    Lancamento 0,00 nos dois lados -> 'Zero', nao 'Credito' por default (#27)."""
    if l.debito != 0:
        return "Débito", l.debito
    if l.credito != 0:
        return "Crédito", l.credito
    return "Zero", l.debito


def _lado_e_valor(l: Lancamento) -> tuple[str, str]:
    """O mesmo par, com o valor ja em moeda BR (consumo de TEXTO)."""
    lado, quantia = lado_e_quantia(l)
    return lado, moeda_br(quantia)


# --- Pagamento datado ANTES da emissao da
# NF que o item cita ou que o motor sugere. Decisao contabil: sinalizar, podendo
# deixar no balde e informar que o pagamento foi antes da data da compra, pois
# dependendo da situação será realocado para adiantamento ou não. Isto será
# decidido no processo de conciliação.
#
# Tres coisas que o aviso NAO faz, todas por decisao contabil:
#   - nao muda destino (o item continua exatamente onde estava);
#   - nao rotula de adiantamento (a realocacao e' decisao do processo);
#   - nao vira achado (nao e' divergencia; e' contexto na hora de decidir).
# So' apresentacao: comparar duas datas nao e' aritmetica de dinheiro, e o core
# ja entregou as duas.
_AVISO_PRE_EMISSAO = (
    "Pagamento em {data_pgto} é ANTERIOR à data no razão {nfs}. Dependendo "
    "da situação será realocado para adiantamento — quem decide é o processo "
    "de conciliação.")


# Os avisos da caixinha ficaram DOIS (pagamento pre-emissao;
# NFs gemeas) e vao ficar mais. Um parametro por aviso faria as
# assinaturas do balde crescerem sem fim — entao o que atravessa e' UM contexto
# de leitura, montado uma vez por conta. Read-only e frozen: aviso e' leitura,
# nunca decisao.
@dataclass(frozen=True)
class ContextoAvisos:
    """O que a casca precisa saber ALEM do proprio item pra avisar sobre ele.

    `datas_nf`: emissao de cada NF reconstruida (aberta ou quitada).
    `gemeas`: numero da NF -> o grupo INTEIRO de gemeas a que ela pertence.
    Vazio quando nao ha nada a avisar — e ai todo aviso sai "" em silencio."""
    datas_nf: dict[str, date] = field(default_factory=dict)
    gemeas: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # (linha, valor) de cada "pago a maior" da conta -- o recebimento
    # do balde mostra ao lado, sem casar
    pagos_a_maior: tuple[tuple[str, Decimal], ...] = ()


def contexto_de_avisos(res) -> ContextoAvisos:
    """Monta o contexto a partir do resultado ja conferido. UMA vez por conta.

    As gemeas vem do ACHADO, nao de uma varredura propria: quem detecta
    duplicidade e' o core (`duplicidade_de_emissao`), e a caixinha aponta pro
    MESMO achado que o painel mostra. Detectar de novo aqui criaria duas
    verdades sobre o mesmo fenomeno — e a casca nao decide regra."""
    gemeas: dict[str, tuple[str, ...]] = {}
    for a in res.achados:
        if a.codigo == "possivel_duplicidade_emissao" and a.referencia:
            grupo = tuple(n.strip() for n in a.referencia.split(","))
            for numero in grupo:
                gemeas[numero] = grupo
    # o valor da linha e' o "Total pago" dela (a sobra), ja positivo no core
    pagos = tuple((i.nf_numero, i.total_pago) for i in res.itens
                  if i.origem is Origem.PAGO_A_MAIOR)
    return ContextoAvisos(datas_nf=datas_de_emissao(res), gemeas=gemeas,
                          pagos_a_maior=pagos)


def datas_de_emissao(res) -> dict[str, date]:
    """{numero da NF: data da compra} de TUDO que o motor reconstruiu — o que
    esta aberto (`itens`) e o que fechou (`quitadas`). As duas fontes
    porque o item do balde pode citar uma NF que ja fechou, e o aviso vale
    igual. Item sem data de compra (o "(anterior)", NF sem compra na janela)
    fica de fora: sem data nao ha o que comparar."""
    return {i.nf_numero: i.data_compra
            for i in list(res.itens) + list(res.quitadas)
            if i.data_compra is not None}


def _nfs_citadas(item: ItemRevisao) -> list[str]:
    """As NFs que ESTE item aponta: a sugerida quando o motor propos uma,
    senao as candidatas apuradas. A sugerida tem precedencia porque e' a que o
    conferente esta prestes a aceitar."""
    if item.sugestao is not None and item.sugestao.alvo:
        return [item.sugestao.alvo]
    return list(item.candidatos)


def aviso_pre_emissao(lanc: Lancamento, item: ItemRevisao,
                      ctx: "ContextoAvisos | None") -> str:
    """O aviso deste LANCAMENTO, ou "" quando nao ha o que avisar.

    Por lancamento, e nao por item: a tabela e a caixinha sao por lancamento, e
    num item agregado (o um-pra-muitos) so' alguns podem anteceder.
    So' DEBITO: credito na conta do fornecedor nao e' pagamento."""
    datas_nf = ctx.datas_nf if ctx else {}
    if not datas_nf or lanc.debito <= Decimal("0.00"):
        return ""
    posteriores = [(nf, datas_nf[nf]) for nf in _nfs_citadas(item)
                   if nf in datas_nf and lanc.data < datas_nf[nf]]
    if not posteriores:
        return ""
    rotulo = "da NF" if len(posteriores) == 1 else "das NFs"
    nfs = f"{rotulo} " + ", ".join(f"{nf} ({data_br(d)})" for nf, d in posteriores)
    return _AVISO_PRE_EMISSAO.format(data_pgto=data_br(lanc.data), nfs=nfs)


_RESSALVA_GEMEAS = (
    "As NFs {nfs} têm alerta de possível duplicidade na emissão (mesmo valor, "
    "mesma data no razão): pode não haver o que decidir aqui.")


def ressalva_gemeas(item: ItemRevisao, ctx: "ContextoAvisos | None") -> str:
    """O item disputa 2+ NFs do MESMO grupo de gemeas.

    Vai na CAIXINHA porque e' la que se decide: o alerta do painel esta a tres
    secoes de distancia e nao chega na hora do clique. Mesmo raciocinio da
    `_ressalva_duplicidade`.

    Exige 2+ do mesmo grupo entre as NFs em jogo: item que toca UMA gemea so'
    nao vive o dilema, e o alerta do painel basta.

    "Em jogo" aqui e' candidatas E sugerida — e NAO a precedencia da sugerida
    que o aviso de pre-emissao usa. A diferenca e' o ponto da decisao contabil: no
    pre-emissao interessa a NF que o conferente vai aceitar; aqui interessa
    justamente que a proposta pode estar apontando pra uma nota que nao
    deveria existir. Medido num caso: com a precedencia, os QUATRO pagamentos
    de mesmo valor ficavam sem ressalva, porque a
    sugestao apontava outra NF pra eles. Eram exatamente os itens que a decisao contabil
    reclassifica."""
    gemeas = ctx.gemeas if ctx else {}
    if not gemeas:
        return ""
    citadas = list(item.candidatos)
    if item.sugestao is not None and item.sugestao.alvo:
        citadas.append(item.sugestao.alvo)
    citadas = list(dict.fromkeys(citadas))
    for grupo in dict.fromkeys(gemeas[nf] for nf in citadas if nf in gemeas):
        do_grupo = [nf for nf in citadas if nf in grupo]
        if len(do_grupo) >= 2:
            return _RESSALVA_GEMEAS.format(nfs=", ".join(sorted(do_grupo)))
    return ""


def ressalva_pago_a_maior(item: ItemRevisao,
                          ctx: "ContextoAvisos | None") -> str:
    """O recebimento do fornecedor mostra, AO LADO, o pago a maior da
    mesma conta. Fato, sem casar: os valores podem nao bater (num caso, nao
    bateram) e a decisao e' humana."""
    pagos = ctx.pagos_a_maior if ctx else ()
    if item.motivo is not MotivoRevisao.RECEBIMENTO or not pagos:
        return ""
    return " ".join(f"Nesta conta: R$ {moeda_br(valor)} pago a maior na linha "
                    f"{linha}." for linha, valor in pagos)


def avisos_do_item(lanc: Lancamento, item: ItemRevisao,
                   ctx: "ContextoAvisos | None") -> str:
    """TODOS os avisos deste lancamento, numa frase so'. Ponto UNICO: a
    caixinha, a planilha e os testes leem daqui, e aviso novo entra aqui
    dentro sem tocar em assinatura nenhuma."""
    partes = (aviso_pre_emissao(lanc, item, ctx), ressalva_gemeas(item, ctx),
              ressalva_pago_a_maior(item, ctx))
    return " ".join(t for t in partes if t)


def balde_detalhes(balde: list[ItemRevisao],
                   ctx: "ContextoAvisos | None" = None,
                   banco: bool = False, rotulo_numero: str = "Lote") -> list[dict]:
    """Uma expansao por LANCAMENTO do balde (o conferente processa
    caixinha por caixinha), na MESMA ordem cronologica da tabela — a tabela
    e a visao de VARREDURA; as caixinhas, a de PROCESSAMENTO item a item.
    Titulo identificavel por HUMANO (numero + data + lado + valor + motivo);
    dentro: localizacao, lado por extenso,
    contrapartida, orientacao do motivo PARAMETRIZADA com os dados do item
    (no multi-NF inclui a soma que o motor apurou) e o historico INTEGRAL."""
    detalhes: list[dict] = []
    vistos: set[str] = set()
    for item, l in _balde_cronologico(balde):
        lado, valor = _lado_e_valor(l)
        _, quantia = lado_e_quantia(l)
        mrev = _motivo_de(item)
        titulo_motivo = mrev.titulo if mrev else item.motivo.value
        # O item e a unidade de DECISAO; a caixinha e por lancamento. Item
        # com 2+ lancamentos mostra o controle de alocacao so na primeira, senao
        # a segunda so' conseguiria produzir ITEM_JA_ALOCADO.
        primeiro = item.identificador not in vistos
        vistos.add(item.identificador)
        # titulo/localizacao/motivo ja saem ESCAPADOS (vao direto pra
        # markdown); `historico` fica CRU — e a evidencia, e quem injetar
        # em markdown escapa na hora (a tabela HTML escapa como HTML)
        detalhes.append({
            "titulo": markdown_seguro(
                f"{_rotulo_do_numero(rotulo_numero, banco)} "
                f"{l.numero or '—'} · {data_br(l.data)} · {lado} R$ {valor} · "
                f"{titulo_motivo}"),
            "localizacao": markdown_seguro(
                localizacao_lancamento(l, lado, banco=banco, rotulo=rotulo_numero)),
            "motivo": markdown_seguro(motivo_humano(item)),
            "historico": l.historico,
            # o que a tela precisa pra montar o controle de alocacao
            "item_id": item.identificador,
            "quantia": quantia,
            "aloca": primeiro,
            # o OBJETO (a tela marca a opcao e carimba a origem no clique)
            # e a FRASE crua da evidencia (a tela escapa na injecao, como o
            # historico). None/"" quando o motor nao propos nada.
            "sugestao": item.sugestao,
            "sugestao_frase": (frase_sugestao(item.sugestao)
                               if item.sugestao is not None else ""),
            # Linha PROPRIA, nao um apendice do motivo — e' contexto de
            # decisao, e a caixinha e' onde se decide. "" quando nao ha aviso.
            "aviso": markdown_seguro(avisos_do_item(l, item, ctx)),
        })
    return detalhes


def _achado_incompleto(achados: list[Achado]) -> Achado | None:
    """O achado INCOMPLETO que carrega o gap (encontrado), se houver. Predicado
    UNICO consumido por contexto_incompleto e pela triagem do lote (#13)."""
    return next((a for a in achados
                 if a.nivel is Nivel.INCOMPLETO and a.encontrado is not None), None)


def gap_incompleto(achados: list[Achado]) -> Decimal | None:
    """O gap que o balde responde (None quando a composicao fecha). Leitura de
    campo -- quem precisa do NUMERO (materialidade, triagem) consome daqui."""
    a = _achado_incompleto(achados)
    return a.encontrado if a is not None else None


# frase que traduz o gap do INCOMPLETO. A frase exata mora AQUI (constante);
# o smoke so confere o VALOR, delegando o texto a este modulo.
_CONTEXTO_INCOMPLETO = ("O motor não conseguiu alocar {valor} — "
                        "os itens abaixo explicam exatamente essa diferença.")


def contexto_incompleto_texto(achados: list[Achado], ponte=None) -> str | None:
    """Frase que explica o semaforo amarelo em portugues, junto do veredito,
    em texto CRU (a exportacao consome daqui). So existe quando ha achado
    INCOMPLETO; a identidade gap == Σ(D−C) do balde (garantida no veredito)
    e' o que torna a frase verdadeira."""
    a = _achado_incompleto(achados)
    if a is None:
        return None
    # Com credito no balde, os dois lados em vez do liquido. Sem
    # `ponte` (chamador antigo) ou com decisao "fora da composicao" no gap,
    # o texto de sempre.
    lados = (descricao_sem_destino(ponte)
             if ponte is not None and ponte.total_fora_composicao == 0 else None)
    return _CONTEXTO_INCOMPLETO.format(
        valor=lados or f"R$ {moeda_br(a.encontrado)}")


def contexto_incompleto(achados: list[Achado], ponte=None) -> str | None:
    """A mesma frase, escapada pro markdown da tela (st.caption)."""
    texto = contexto_incompleto_texto(achados, ponte)
    return markdown_seguro(texto) if texto is not None else None


def _balde_cronologico(balde: list[ItemRevisao]) -> list[tuple[ItemRevisao, Lancamento]]:
    """Achata (item, lancamento) e ordena por DATA crescente: conferente
    trabalha em ordem cronologica, como se le um razao — e a ordem casa com o
    extrato. Tabela e expansoes consomem a MESMA ordem (linha N <-> expansao N).
    Ordenacao e' apresentacao; sort estavel preserva a ordem do arquivo em
    datas iguais."""
    pares = [(item, l) for item in balde for l in item.lancamentos]
    return sorted(pares, key=lambda par: par[1].data)


def _balde_por_valor(balde: list[ItemRevisao]) -> list[tuple[ItemRevisao, Lancamento]]:
    """Os mesmos pares, do MAIOR valor pro menor — ordem do Excel: la o
    conferente ataca primeiro o que pesa. DETERMINISTICA: empate de valor
    desempata por DATA e depois por LOTE, entao o mesmo arquivo gera sempre a
    mesma planilha (diff de conferencia so muda quando o dado muda).
    A TELA nao usa esta ordem — la o fluxo e cronologico (#28)."""
    return sorted(_balde_cronologico(balde),
                  key=lambda par: (-lado_e_quantia(par[1])[1],
                                   par[1].data, par[1].numero))


def balde_celulas(balde: list[ItemRevisao], por_valor: bool = False,
                  ctx: "ContextoAvisos | None" = None) -> list[dict]:
    """As colunas do balde com valores NATIVOS (date, Decimal), pro EXCEL --
    la o balde continua sendo tabela (com Sugestao e Classificacao lado a
    lado, o formato certo pro meio). Na TELA nao ha mais tabela: a caixinha
    por item e' a unica visao. UM row por lancamento -- LE o campo do
    lado que tem valor (escolha de campo, nao soma). Historico integral =
    evidencia."""
    celulas: list[dict] = []
    pares = _balde_por_valor(balde) if por_valor else _balde_cronologico(balde)
    for item, l in pares:
        lado, quantia = lado_e_quantia(l)
        mrev = _motivo_de(item)
        celulas.append({
            "Lote": l.numero,
            "Data": l.data,
            # por EXTENSO: "D"/"C" seco e taquigrafia de contador
            "Lado": lado,
            "Valor": quantia,
            "Motivo": mrev.celula if mrev else item.motivo.value,
            "NFs candidatas": ", ".join(item.candidatos) if item.candidatos else _VAZIO,
            "Contrapartida": l.cta_part,     # de onde saiu/entrou (na tabela)
            "Histórico": l.historico,
            # POR ULTIMO de proposito: no Excel as colunas em branco de
            # preenchimento manual sao concatenadas depois das celulas, entao
            # esta cai imediatamente a esquerda de Classificacao -- proposta do
            # motor e dropdown lado a lado, que e onde o conferente trabalha.
            "Sugestão do motor": _com_aviso(
                frase_sugestao(item.sugestao) if item.sugestao is not None
                else "", avisos_do_item(l, item, ctx)),
        })
    return celulas


def _com_aviso(frase: str, aviso: str) -> str:
    """Junta proposta e aviso na MESMA celula. Nao ha coluna nova: a planilha
    foi enxugada de proposito, e o aviso pertence ao lugar onde o
    conferente le o que fazer com o item. Nenhum dos dois -> celula vazia."""
    return " ".join(t for t in (frase, aviso) if t) or _VAZIO


def balde_lancamentos(balde: list[ItemRevisao],
                      por_valor: bool = False) -> list[Lancamento]:
    """Os Lancamento do balde na MESMA ordem de balde_celulas (linha N <->
    lancamento N). Selecao pura -- quem precisa do OBJETO (a materialidade
    precisa dos dois lados pra pesar a contribuicao) consome daqui em vez de
    reordenar por conta propria."""
    pares = _balde_por_valor(balde) if por_valor else _balde_cronologico(balde)
    return [l for _, l in pares]


# triagem do lote: 1 linha por CONTA processada + 1 por arquivo que
# falhou. Rank de severidade: problemas primeiro (erro de leitura e
# divergencia > incompleto > fecha com alerta > fecha limpo), depois arquivo
# e conta — o conferente varre o resumo, ignora os verdes, desce nas amarelas.
def _triagem_ordenada(entradas: list[tuple[str, list | None, str | None]]
                      ) -> list[tuple[int, object, dict]]:
    """entradas = [(arquivo, resultados | None, erro | None)]: resultados sao
    os ResultadoConferencia do arquivo; erro e' a mensagem amigavel quando a
    leitura falhou (arquivo vira linha propria — falha nunca some do resumo).
    Devolve (indice da entrada, resultado | None, linha), ja na ordem: fonte
    UNICA da ordem do lote -- triagem, detalhe e exportacao leem daqui."""
    ordenaveis: list[tuple[int, str, str, int, object, dict]] = []
    for idx, (arquivo, resultados, erro) in enumerate(entradas):
        if erro is not None:
            ordenaveis.append((0, arquivo, "", idx, None, {
                "Arquivo": arquivo, "Conta": _VAZIO, "Fornecedor": _VAZIO,
                "Veredito": ACIMA_DO_LIMITE if isinstance(erro, FraseAcimaDoLimite) else "⛔ Erro de leitura",
                "Falta alocar": _VAZIO,
                "Itens sem destino": _VAZIO, "Sugeridos": _VAZIO,
                "Achados": _VAZIO,
            }))
            continue
        if not resultados:
            # arquivo LIDO ok mas sem nenhuma conta de fornecedor: nao pode
            # sumir da triagem -- vira linha propria de problema
            ordenaveis.append((0, arquivo, "", idx, None, {
                "Arquivo": arquivo, "Conta": _VAZIO, "Fornecedor": _VAZIO,
                "Veredito": "⚠️ Sem contas", "Falta alocar": _VAZIO,
                "Itens sem destino": _VAZIO, "Sugeridos": _VAZIO,
                "Achados": "nenhuma conta de fornecedor encontrada no arquivo",
            }))
            continue
        for res in resultados:
            severidade, _ = status_conta(res.achados)
            # so' o que o motor NAO decidiu conta e rebaixa o verde
            n_alertas = len(alertas_nao_decididos(res.achados))
            if severidade == DIVERGENCIA:
                rotulo, rank = "🔴 Divergência", 0
            elif severidade == INCOMPLETO:
                rotulo, rank = "🟡 Incompleto", 1
            else:
                # a MESMA palavra que abre o veredito da conta
                rotulo, rank = "🟢 Conferido", 2 if n_alertas else 3
            inc = _achado_incompleto(res.achados)
            # conta que fecha nao "falta" nada -- e' 0,00, nao travessao
            gap = (moeda_br(inc.encontrado) if inc is not None
                   else moeda_br(Decimal("0.00")) if severidade == FECHA
                   else _VAZIO)
            # credito no balde -> os dois lados, nunca liquido negativo
            debitos, creditos = _lados_do_balde(res.ponte)
            if inc is not None and res.balde and creditos != Decimal("0.00"):
                gap = (f"crédito {moeda_br(creditos)}"
                       if debitos == Decimal("0.00") else
                       f"{moeda_br(debitos)} e crédito {moeda_br(creditos)}")
            sugeridos = sum(1 for i in res.balde if i.sugestao is not None)
            ordenaveis.append((rank, arquivo, res.conta.codigo, idx, res, {
                "Arquivo": arquivo,
                "Conta": res.conta.codigo,
                "Fornecedor": res.conta.nome,
                "Veredito": rotulo,
                "Falta alocar": gap,
                "Itens sem destino": str(len(res.balde)),
                # quanto do balde ja vem proposto -- e o que diz ao
                # conferente qual conta fecha rapido
                "Sugeridos": str(sugeridos) if sugeridos else _VAZIO,
                "Achados": f"{n_alertas} alerta(s)" if n_alertas else _VAZIO,
            }))
    return [(idx, res, linha) for _, _, _, idx, res, linha in
            sorted(ordenaveis, key=lambda t: (t[0], t[1], t[2]))]


def triagem_linhas(entradas: list[tuple[str, list | None, str | None]]) -> list[dict]:
    """As linhas da triagem do lote, problemas primeiro (ver _triagem_ordenada)."""
    return [linha for _, _, linha in _triagem_ordenada(entradas)]


def resumo_envio_texto(recebidos: int, lidos: int, erros: int, sem_contas: int,
                       no_zip: int, *, acima_do_limite: int = 0) -> list[str]:
    """Fatos dos arquivos recebidos e das exportações prontas, sem contar contas."""
    parcelas = []
    if recebidos:
        parcelas.append("1 arquivo recebido" if recebidos == 1 else f"{recebidos} arquivos recebidos")
    if lidos:
        parcelas.append("1 lido" if lidos == 1 else f"{lidos} lidos")
    if erros:
        parcelas.append(f"{erros} com erro de leitura")
    if acima_do_limite:
        parcelas.append(f"{acima_do_limite} acima do limite")
    if sem_contas:
        parcelas.append(f"{sem_contas} sem contas")
    linhas = [" · ".join(parcelas)] if parcelas else []
    if no_zip >= 2:
        linhas.append(f"{no_zip} arquivos no ZIP")
    return linhas


def ordem_do_lote(entradas: list[tuple[str, list | None, str | None]]
                  ) -> list[tuple[int, object]]:
    """(indice da entrada, resultado | None) na MESMA ordem da
    triagem. None = a linha do arquivo que nao virou conta (erro / sem
    contas). O detalhe do lote desce nesta ordem: quem le a triagem e rola a
    pagina encontra as contas na mesma sequencia."""
    return [(idx, res) for idx, res, _ in _triagem_ordenada(entradas)]


def divergencias_celulas(achados: list[Achado]) -> list[dict]:
    """Erros reais (nivel ERRO) com esperado/encontrado NATIVOS (Decimal|None)
    -- fonte unica das colunas; divergencias() formata daqui."""
    return [
        {
            "Verificação": _TIPO_ALERTA.get(a.codigo, a.codigo),
            "Mensagem": frase_achado(a),        # frase formatada daqui
            "Esperado": a.esperado,
            "Encontrado": a.encontrado,
        }
        for a in achados
        if a.nivel is Nivel.ERRO
    ]


def titulo_divergencias(ha_divergencia: bool) -> str:
    """O X vermelho so' quando HA divergencia -- ao lado de
    "Nenhuma." ele assustava. Sem divergencia, icone neutro (cinza)."""
    if ha_divergencia:
        return "#### ❌ Divergências"
    return "#### :gray[:material/check_circle:] Divergências"


def divergencias(achados: list[Achado]) -> list[dict]:
    """Erros reais (nivel ERRO) -> linhas com esperado/encontrado ao centavo."""
    return _linhas_de_texto(divergencias_celulas(achados))


def alertas(achados: list[Achado]) -> list[Achado]:
    """Sinalizacoes (nivel ALERTA): nao sao erro nem balde -- nota secundaria."""
    return [a for a in achados if a.nivel is Nivel.ALERTA]


# === Alertas em duas classes (regra aprovada) ================================
# Exibicao pura: o core nao muda. Criterio unico -- a frase descreve uma
# decisao que o motor tomou por regra APROVADA (registrado: a frase e' prova),
# ou um fato que nenhuma regra decide? Todo codigo de ALERTA do core tem
# entrada aqui (trava: tests/test_classe_alerta.py); desconhecido cai no lado
# seguro (aparece e conta).
REGISTRADO = "Registrado pelo motor"
NAO_DECIDIDO = "Não decidido pelo motor"         # fato, nao instrucao
_CLASSE_ALERTA = {
    "casamento_por_desempate": REGISTRADO,    # regra 1 (serie > unica > FIFO)
    "casamento_por_valor_declarado": REGISTRADO,  # regra aprovada
    "casamento_por_serie_ordinal": REGISTRADO,    # regra aprovada
    "casamento_por_valor_citacao_sem_nota": REGISTRADO,  # regra aprovada
    "possivel_compra_repetida": NAO_DECIDIDO,     # fato, composicao intacta
    "pago_a_maior": NAO_DECIDIDO,             # a sobra nao tem rotulo
    "lacuna_na_serie": NAO_DECIDIDO,          # fato do razao
    "estorno_pareado": REGISTRADO,            # par anulado, liquido zero
    "corte_recuado": REGISTRADO,              # adendo aprovado do corte por saldo zero
    "periodo_zerado_com_pendencia": None,     # depende do bloco: ver classe_alerta
    "possivel_duplicidade": NAO_DECIDIDO,
    "possivel_duplicidade_emissao": NAO_DECIDIDO,
    "possivel_juros": NAO_DECIDIDO,
    "possivel_juros_manual": NAO_DECIDIDO,
    "possivel_desconto": NAO_DECIDIDO,
    "saldo_anterior_nao_detalhado": NAO_DECIDIDO,
    "transferencia_nao_detalhada": NAO_DECIDIDO,
    "conta_devedora": NAO_DECIDIDO,
    "self_check_saldo_corrente": NAO_DECIDIDO,   # a LEITURA pode estar errada
}


def classe_alerta(a: Achado) -> str:
    """Periodo zerado: registrado quando o sem NF do bloco cobre as NFs dele
    EXATO (comparacao de dois campos prontos do core, sem conta)."""
    if a.codigo == "periodo_zerado_com_pendencia":
        bate = a.valores.get("aberto") == a.valores.get("sem_nf")
        return REGISTRADO if bate else NAO_DECIDIDO
    return _CLASSE_ALERTA.get(a.codigo) or NAO_DECIDIDO


def alertas_registrados(achados: list[Achado]) -> list[Achado]:
    return [a for a in alertas(achados) if classe_alerta(a) == REGISTRADO]


def alertas_nao_decididos(achados: list[Achado]) -> list[Achado]:
    return [a for a in alertas(achados) if classe_alerta(a) == NAO_DECIDIDO]


# --- frases de achado (#34): o core entrega codigo + numeros (esperado/
# encontrado/valores); a FRASE com moeda BR nasce AQUI, uma funcao por codigo
# (padrao _CONTEXTO_INCOMPLETO, #14/#16). Faltou numero (achado sintetico,
# codigo compartilhado com OK) -> fallback pra mensagem crua do core:
# VISIVEL, nunca frase pela metade nem excecao.

# Decisao contabil: o COMPORTAMENTO ja estava certo — o motor
# sinaliza e NAO vincula. O que faltava era dizer ao conferente o que fazer com
# a sobra: juros nao amortiza a compra, vai pra conta de despesa propria. Texto
# UNICO nas duas frases (automatico e manual): e' o mesmo juros, muda so' a
# origem do estouro.
_ORIENTACAO_JUROS = (" — juros é despesa em conta específica, não "
                     "abatimento do valor da compra (fornecedor)")

_FRASES_ACHADO = {
    # O limite do corte dito com todas as letras -- o total se
    # compensa, a quitacao NF a NF nao foi provada
    "periodo_zerado_com_pendencia": lambda a: (
        f"{a.mensagem}: R$ {moeda_br(a.valores['aberto'])} em NFs que não "
        f"casaram NF a NF se compensam com R$ {moeda_br(a.valores['sem_nf'])} "
        f"em lançamentos sem NF. Informação, não divergência: o saldo final "
        f"não depende desse período, mas o total não prova que cada NF foi "
        f"paga"),
    "possivel_juros": lambda a: (
        f"{a.mensagem}: quitado R$ {moeda_br(a.encontrado)} sobre compra "
        f"R$ {moeda_br(a.esperado)} (diferença R$ {moeda_br(a.valores['diferenca'])})"
        + _ORIENTACAO_JUROS),
    # mesma frase, codigo PROPRIO: o estouro veio de alocacao manual e a
    # origem tem que ser visivel na tela e no export, nunca deduzida
    "possivel_juros_manual": lambda a: (
        f"{a.mensagem}: quitado R$ {moeda_br(a.encontrado)} sobre compra "
        f"R$ {moeda_br(a.esperado)} (diferença R$ {moeda_br(a.valores['diferenca'])})"
        + _ORIENTACAO_JUROS),
    # Decisao contabil: irmao do saldo_anterior_nao_detalhado —
    # valor em aberto legitimo cujo detalhe NF a NF vive fora deste arquivo
    "transferencia_nao_detalhada": lambda a: (
        f"saldo de R$ {moeda_br(a.encontrado)} transferido de outra conta do "
        f"mesmo fornecedor (matriz/filial), sem detalhe de notas neste razão"),
    "saldo_anterior_nao_detalhado": lambda a: (
        f"saldo anterior de R$ {moeda_br(a.encontrado)} sem detalhe de notas "
        f"neste razão"),
    # Decisao contabil: diagnostico, nao "revisar". As tres
    # causas comuns vem da contabilidade — o sistema nao escolhe entre elas, lista o que
    # o conferente vai procurar.
    "conta_devedora": lambda a: (
        f"conta devedora de R$ {moeda_br(a.encontrado)}: há mais pagamentos "
        f"(débitos) que provisões (créditos). Causas comuns: parcelas pagas "
        f"com juros, pagamentos sem nota fiscal, ou notas ainda não "
        f"contabilizadas"),
    # codigo compartilhado com OK/INCOMPLETO: so o ERRO tem 'residuo' em
    # valores -- os demais caem no fallback pela KeyError
    "self_check_composicao": lambda a: (
        f"divergência não explicada pelos itens sem destino: diferença de "
        f"R$ {moeda_br(a.encontrado)}, "
        f"os itens sem destino explicam R$ {moeda_br(a.esperado)}, sobra "
        f"R$ {moeda_br(a.valores['residuo'])} sem explicação"),
    "self_check_saldo_corrente": lambda a: (
        f"{a.mensagem}: variação impressa R$ {moeda_br(a.encontrado)} != "
        f"débito-crédito R$ {moeda_br(a.esperado)}"),
    # Decisao contabil: NFs gemeas. A frase termina na ACAO
    # contabil — quem resolve isto e' o cliente, nao o conferente. A data de
    # emissao NAO entra: o core nao formata data.
    "possivel_duplicidade_emissao": lambda a: (
        f"{a.mensagem} — valor R$ {moeda_br(a.encontrado)}. Havendo "
        f"duplicidade na emissão, uma das notas é estornada."),
    "possivel_duplicidade": lambda a: (
        f"{a.mensagem} — valor da parcela R$ {moeda_br(a.valores['valor'])}"),
    "casamento_por_desempate": lambda a: (
        f"{a.mensagem} (R$ {moeda_br(a.valores['pagamento'])})"),
    # Os tres numeros que sustentam a ligacao. A diferenca e' fato
    # (pago - declarado); o rotulo dela, quando estoura a NF, e' o do alerta
    # de possivel juros, nao desta frase.
    # O fato, com os tres numeros. Sem rotulo pra sobra -- juros,
    # adiantamento ou outro titulo nao e' o motor que decide.
    "pago_a_maior": lambda a: (
        f"{a.mensagem}: pago R$ {moeda_br(a.valores['pagamento'])}; as notas "
        f"citadas somavam R$ {moeda_br(a.valores['soma'])} em aberto; "
        f"R$ {moeda_br(a.valores['sobra'])} acima, na linha {a.referencia}"),
    "casamento_por_serie_ordinal": lambda a: (
        f"{a.mensagem} (R$ {moeda_br(a.valores['pagamento'])})"),
    # A NF, quantas vezes, o valor e as linhas (lotes e datas)
    "possivel_compra_repetida": lambda a: (
        f"NF {a.referencia} lançada {a.valores['vezes']:.0f} vezes com o mesmo "
        f"valor, R$ {moeda_br(a.valores['valor'])}: {_lotes_e_datas(a)}"),
    "casamento_por_valor_citacao_sem_nota": lambda a: (
        f"{a.mensagem} (R$ {moeda_br(a.valores['pagamento'])})"),
    "casamento_por_valor_declarado": lambda a: (
        f"{a.mensagem}: pago R$ {moeda_br(a.valores['pagamento'])}, "
        f"declarado R$ {moeda_br(a.valores['declarado'])} (diferença "
        f"R$ {moeda_br(a.valores['diferenca'])})"),
    # O par anulado nao deixa linha na composicao (liquido zero), entao
    # esta frase e a UNICA resposta a "cade a baixa?" — leva os dois lotes, as
    # duas datas, o valor e os DOIS historicos INTEIROS. Longa de proposito:
    # historico truncado obrigaria o conferente a voltar ao Dominio.
    "estorno_pareado": lambda a: (
        f"par anulado: R$ {moeda_br(a.valores['valor'])} do lote "
        f"{a.lancamentos[0].numero} ({data_br(a.lancamentos[0].data)}) "
        f"estornado pelo lote {a.lancamentos[1].numero} "
        f"({data_br(a.lancamentos[1].data)}) — líquido zero, os dois saem da "
        f"revisão manual e nada entra na composição. "
        f'Operação: "{a.lancamentos[0].historico}". '
        f'Estorno: "{a.lancamentos[1].historico}".'),
    # a faixa do desconto cobre tambem IRRF (1,5%) e ISS (2%): a frase oferece
    # as DUAS leituras em vez de afirmar desconto (taxonomia conservadora).
    # Decisao contabil: a frase termina no processo do escritorio —
    # normalmente, quando o cliente e' avisado do saldo a pagar, ele informa
    # que houve desconto na compra. Quem
    # resolve o alerta nao e' o conferente sozinho, e o cliente.
    "possivel_desconto": lambda a: (
        f"{a.mensagem}: quitado R$ {moeda_br(a.encontrado)} de "
        f"R$ {moeda_br(a.esperado)} (falta R$ {moeda_br(a.valores['diferenca'])}, "
        f"{pct_br(a.valores['percentual'])}% — possível desconto concedido ou "
        f"retenção não lançada)."),
}


def frase_achado(a: Achado) -> str:
    """Frase de EXIBICAO de um achado (texto cru: a tela escapa na injecao,
    o Excel usa direto). Codigo sem template ou sem os numeros -> a.mensagem."""
    template = _FRASES_ACHADO.get(a.codigo)
    if template is None:
        return a.mensagem
    try:
        return template(a)
    except (KeyError, TypeError, AttributeError):
        return a.mensagem       # numeros ausentes: mensagem crua, visivel


# Rotulo CURTO por codigo de alerta -- e a coluna "Tipo" da tabela do
# Excel (a tela continua com a frase inteira: la ela cabe numa linha de info).
# Codigo sem rotulo cai no proprio codigo: VISIVEL, nunca celula vazia.
_TIPO_ALERTA = {
    "periodo_zerado_com_pendencia": "Período já zerado",
    "corte_recuado": "Saldo zero não aproveitado",
    "possivel_juros": "Possível juros",
    "possivel_juros_manual": "Possível juros (após alocação manual)",
    "possivel_desconto": "Possível desconto",
    "possivel_duplicidade": "Possível duplicidade",
    # rotulo PROPRIO: a duplicidade de parcela e a PARCELA paga 2x; esta e a
    # NOTA emitida 2x. Dois fenomenos com o mesmo rotulo curto seria pior que
    # rotulo nenhum.
    "possivel_duplicidade_emissao": "Possível duplicidade na emissão",
    "casamento_por_desempate": "Casado por desempate",
    "casamento_por_valor_declarado": "Casado pelo valor declarado",
    "casamento_por_serie_ordinal": "Casado pela série de parcelas",
    "casamento_por_valor_citacao_sem_nota": "Casado pelo valor (NF citada sem compra)",
    "possivel_compra_repetida": "NF lançada mais de uma vez",
    "pago_a_maior": "Pago a maior",
    "lacuna_na_serie": "Parcela ausente na série",
    "estorno_pareado": "Par anulado",
    "saldo_anterior_nao_detalhado": "Saldo anterior não detalhado",
    "transferencia_nao_detalhada": "Saldo transferido não detalhado",
    "conta_devedora": "Conta devedora",
    "composicao_com_ressalva": "Itens fora da composição",
    # as verificacoes de leitura/fechamento tambem tem nome --
    # codigo snake_case na tela e no Excel nao e' fato legivel
    "self_check_saldo_corrente": "Saldo da linha não confere",
    "self_check_total_debito": "Total de débitos",
    "self_check_total_credito": "Total de créditos",
    "self_check_saldo_final": "Saldo final",
    "self_check_composicao": "Composição x saldo final",
}

# o detalhe CURTO da tabela: uma linha, sem repetir o que ja esta em coluna
# (valor, diferenca). Codigo sem detalhe proprio usa a mensagem neutra do core.
_DETALHE_ALERTA = {
    "estorno_pareado": lambda a: (
        f"lote {a.lancamentos[0].numero} ({data_br(a.lancamentos[0].data)}) "
        f"estornado pelo lote {a.lancamentos[1].numero} "
        f"({data_br(a.lancamentos[1].data)}) — líquido zero"),
}


def _evidencia_alerta(a: Achado) -> str:
    """O texto INTEGRAL que sustenta o alerta (quando o achado e' a unica
    prova do que aconteceu, o historico inteiro tem que ir junto). Sai em
    coluna PROPRIA da tabela, em vez de virar paragrafo dentro do detalhe."""
    return " | ".join(f'{l.numero}: "{l.historico}"' for l in a.lancamentos)


def alertas_celulas(achados: list[Achado]) -> list[dict]:
    """Os ALERTAs como TABELA, com valores NATIVOS: o conferente
    filtra por tipo e soma a coluna. Antes eram paragrafos numa celula so' — o
    par anulado saia com 305 caracteres.

    "NF/Lote" vem de `Achado.referencia` (dado, nao prosa: quem emite o achado
    ja sabe de qual NF/lote fala). Vazia quando o achado e' da CONTA inteira —
    e a coluna SOME quando nenhum alerta da conta tem referencia."""
    celulas: list[dict] = []
    for a in alertas(achados):
        detalhe = _DETALHE_ALERTA.get(a.codigo)
        celulas.append({
            "Tipo": _TIPO_ALERTA.get(a.codigo, a.codigo),
            # identifica a linha ANTES dos numeros: o olho procura a NF primeiro
            "NF/Lote": a.referencia or _VAZIO,
            "Valor": a.encontrado if a.encontrado is not None else a.valores.get("valor"),
            "Diferença": a.valores.get("diferenca"),
            "Detalhe": detalhe(a) if detalhe else a.mensagem,
            # a planilha e' o documento completo -- TODOS os alertas
            # ficam, com a classe em coluna pra filtro
            "Classe": classe_alerta(a),
            "Evidencia": _evidencia_alerta(a) or _VAZIO,
        })
    return celulas


@dataclass(frozen=True)
class Observacao:
    """Uma caixa das Observacoes da TELA: a frase e, quando ha, a lista curta
    que vai embaixo dela (texto CRU; a tela escapa item a item)."""
    frase: str
    lista: tuple[str, ...] = ()


def observacoes_tela(achados: list[Achado]) -> list[Observacao]:
    """As Observacoes da tela (so' o NAO decidido pelo motor). Com
    2+ alertas de possivel juros, eles viram UMA caixa -- "Possível juros por
    atraso em N notas" + (NF, diferença) -- e a frase da conta de despesa
    aparece uma vez. O mesmo pra NF lancada 2+ vezes com o mesmo
    valor (um caso tem 13). A caixa fica onde estava o primeiro do grupo. Os
    demais alertas, um por caixa, como sempre. O Excel segue um por linha."""
    nao_decididos = alertas_nao_decididos(achados)
    grupos = [(codigos, [a for a in nao_decididos if a.codigo in codigos],
               titulo, item)
              for codigos, titulo, item in _GRUPOS_OBSERVACAO]
    grupos = [g for g in grupos if len(g[1]) >= 2]
    obs: list[Observacao] = []
    for a in nao_decididos:
        grupo = next((g for g in grupos if a.codigo in g[0]), None)
        if grupo is None:
            obs.append(Observacao(frase_achado(a)))
        elif a is grupo[1][0]:
            _, membros, titulo, item = grupo
            obs.append(Observacao(titulo(len(membros)),
                                  tuple(item(m) for m in membros)))
    return obs


def _lotes_e_datas(a: Achado) -> str:
    """"lotes 59786 e 59834 (05/05/2026)" -- as linhas da compra repetida.
    Datas distintas, na ordem."""
    lotes = [l.numero for l in a.lancamentos]
    datas = sorted({l.data for l in a.lancamentos})
    return (f"lotes {_e_lista(lotes)} "
            f"({_e_lista([data_br(d) for d in datas])})")


def _e_lista(textos: list[str]) -> str:
    return (textos[0] if len(textos) == 1
            else ", ".join(textos[:-1]) + " e " + textos[-1])


def _item_compra_repetida(a: Achado) -> str:
    try:
        return (f"{nome_de_linha(a.referencia)}: "
                f"R$ {moeda_br(a.valores['valor'])}, {_lotes_e_datas(a)}")
    except (KeyError, TypeError, AttributeError, IndexError):
        return a.mensagem


def _item_juros(a: Achado) -> str:
    """"NF 5001: diferença R$ 2,46" (+ a origem, quando veio de alocacao
    manual: ela tem que ficar visivel)."""
    try:
        texto = (f"{nome_de_linha(a.referencia)}: diferença "
                 f"R$ {moeda_br(a.valores['diferenca'])}")
    except (KeyError, TypeError, AttributeError):
        return a.mensagem                   # numeros ausentes: mensagem crua
    if a.codigo == "possivel_juros_manual":
        texto += ", após alocação manual"
    return texto


# Os alertas que viram UMA caixa quando sao 2+ na conta -- (codigos,
# titulo da caixa pela quantidade, linha da lista)
_GRUPOS_OBSERVACAO = (
    (_CODIGOS_JUROS,
     lambda n: f"Possível juros por atraso em {n} notas{_ORIENTACAO_JUROS}.",
     lambda a: _item_juros(a)),
    (("possivel_compra_repetida",),
     lambda n: f"NF lançada mais de uma vez com o mesmo valor em {n} notas.",
     lambda a: _item_compra_repetida(a)),
)


def frases_alertas(achados: list[Achado]) -> list[str]:
    """As frases prontas dos ALERTAs, na ordem — o que a tela e o Excel exibem."""
    return [frase_achado(a) for a in alertas(achados)]


def erro_planilha_do_arquivo(nome: str) -> str:
    """A planilha de UM arquivo do lote não saiu; só fato (a conferência está na tela)."""
    return (f"Erro inesperado gerando a planilha de '{nome}'; a planilha deste arquivo "
            f"não foi gerada. A conferência dele está na tela.")


CONTAS_NA_TELA = "Contas na tela"


def contas_na_tela_texto(inicio: int, fim: int, total: int) -> str:
    """Fato da janela de contas de UM arquivo (a tela desenha poucas por vez; triagem e planilha levam todas)."""
    return f"Contas {inicio} a {fim} de {total} deste arquivo"


ACIMA_DO_LIMITE = "⛔ Acima do limite"


class FraseAcimaDoLimite(str):
    """Texto da recusa por teto de entrada; segue sendo texto, so' marca a linha da triagem."""


def _milhar(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def arquivo_com_conta_grande_texto(arquivo: str, codigo: str, lancamentos: int, limite: int) -> str:
    return (f"'{arquivo}': a conta {codigo} tem {_milhar(lancamentos)} lançamentos; o limite por conta é "
            f"{_milhar(limite)}. Nenhum resultado foi gerado pra este arquivo.")


def arquivo_com_contas_grandes_texto(arquivo: str, quantidade: int, codigo: str, lancamentos: int,
                                     limite: int) -> str:
    return (f"'{arquivo}': {quantidade} contas têm mais de {_milhar(limite)} lançamentos (a maior, conta "
            f"{codigo}, tem {_milhar(lancamentos)}); o limite por conta é {_milhar(limite)}. "
            f"Nenhum resultado foi gerado pra este arquivo.")


def arquivo_com_contas_demais_texto(arquivo: str, contas: int, limite: int) -> str:
    return (f"'{arquivo}' tem {_milhar(contas)} contas; o limite por arquivo é {_milhar(limite)}. "
            f"Nenhum resultado foi gerado pra este arquivo.")


ERRO_CLIQUE = "Erro inesperado ao executar a ação; a ação não foi concluída."
ERRO_TELA = "Erro inesperado ao montar a tela; a tela não foi desenhada por inteiro."


def rotulo_saldo_final_planilha(banco: bool = False) -> str:
    return "Saldo final (calculado)" if banco else "Saldo final (Domínio)"


def rotulo_saldo(banco: bool = False) -> str:
    return "Saldo calculado" if banco else "Saldo Domínio"


def composicao_fechada_texto(banco: bool = False) -> str:
    return ("Composição fechada — bate ao centavo com o saldo calculado" if banco
            else "Composição fechada — bate com o Domínio ao centavo")


def ressalva_composicao_texto(valor: str, banco: bool = False) -> str:
    if banco:
        return (f"Ressalva: R$ {valor} declarado(s) fora da composição — "
                "a diferença para o saldo calculado é essa.")
    return (f"Ressalva: R$ {valor} declarado(s) fora da composição — "
            "a diferença com o Domínio é essa.")


def localizacao_lancamento(lancamento, lado: str, banco: bool = False,
                          rotulo: str = "Lote") -> str:
    rotulo = _rotulo_do_numero(rotulo, banco)
    return (f"{rotulo} {lancamento.numero or '—'} · {lado} · "
            f"Contrapartida (Cta.C.Part.): {lancamento.cta_part}")
