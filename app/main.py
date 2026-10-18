"""Tela de Conferencia de Razao de Fornecedores (Streamlit).

CASCA PURA: recebe o arquivo, entrega ao motor (core via app.pipeline) e
renderiza o que volta (traduzido por app.apresentacao). ZERO logica contabil,
ZERO aritmetica de dinheiro aqui -- isso vive no core. O Decimal vem pronto do
motor; nesta camada so se FORMATA pra exibicao.

Rodar:  streamlit run app/main.py
"""
from __future__ import annotations

import functools
import logging
import os
import pathlib
import sys
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from threading import Lock

# detalhe tecnico de erro inesperado vai pro log do servico. So fato neutro (hash do arquivo, tipo
# e lugar do codigo); nunca nome de arquivo, mensagem da excecao nem dado da razao (parser/registro.py)
_log = logging.getLogger("app.main")
# rastro tecnico com data/hora no log do servico (stderr ->
# logs\conciliador_*.log). Os loggers "app" e "parser" ganham UM handler; o
# Streamlit reexecuta este script a cada interacao -- sem a guarda, duplicaria.
for _nome in ("app", "parser"):
    _lg = logging.getLogger(_nome)
    if not _lg.handlers:
        _h = logging.StreamHandler()
        _h.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
        _lg.addHandler(_h)
        _lg.setLevel(logging.INFO)

# repo root no sys.path: permite importar core/parser/app quando rodado via
# `streamlit run app/main.py` (o Streamlit so poe a pasta do script no path).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from streamlit.errors import FragmentHandledException  # noqa: E402,F401

from app.apresentacao import (  # noqa: E402
    CONTAS_NA_TELA,
    ERRO_CLIQUE,
    ERRO_TELA,
    FECHA,
    INCOMPLETO,
    PONTE_DIVERGE,
    PONTE_OK,
    PONTE_PENDENTE,
    REGISTRADO,
    ROTULO_CURTO,
    ROTULO_TOTAL_COM_QUITADAS,
    ROTULO_TOTAL_EM_ABERTO,
    SO_COM_TODAS_AS_COLUNAS,
    FraseAcimaDoLimite,
    abrir_fechado,
    ajuda_coluna,
    ajuda_total,
    alertas_registrados,
    arquivo_com_conta_grande_texto,
    arquivo_com_contas_demais_texto,
    arquivo_com_contas_grandes_texto,
    balde_detalhes,
    bloco_linhas_nfs,
    bloco_linhas_sem_nf,
    colunas_da_tela,
    colunas_visiveis,
    composicao_fechada_texto,
    composicao_linhas,
    contas_na_tela_texto,
    contexto_de_avisos,
    contexto_incompleto_texto,
    decisao_texto,
    decisoes_linhas,
    divergencias,
    e_subtotal,
    erro_planilha_do_arquivo,
    frase_bloco,
    frases_alertas,
    gap_incompleto,
    historico_html,
    itens_da_tabela,
    larguras_composicao,
    linhas_sem_nota,
    markdown_seguro,
    md_ja_escapado,
    nfs_com_possivel_juros,
    nota_anterior_fechado,
    nota_fora_da_tabela,
    notas_composicao_texto,
    observacoes_tela,
    ordem_do_lote,
    placar_composicao,
    ponte_curta_do_total,
    ponte_linhas_tela,
    resposta_conferido,
    ressalva_composicao_texto,
    resumo_do_trabalho,
    resumo_envio_texto,
    rotulo_saldo,
    rotulo_toggle_quitadas,
    saldo_dominio_texto,
    sem_link_automatico,
    status_conta,
    status_ponte,
    tabela_html,
    tabela_triagem,
    texto_digitado,
    titulo_conta,
    titulo_divergencias,
    titulo_fechado,
    titulo_ponte,
    total_linha,
    triagem_linhas,
)
from app.destinos import indice_sugerido, opcoes_de_alocacao  # noqa: E402
from app.materialidade import (  # noqa: E402
    frase_contagem_motivos,
    frase_materialidade,
    frase_sugestoes,
)
from app.pipeline import (  # noqa: E402
    MAX_CONTAS_POR_ARQUIVO,
    MAX_LANCAMENTOS_POR_CONTA,
    ArquivoAcimaDoLimite,
    ResultadoProcessamento,
    chaves_das_contas,
    processar_excel,
)
from core.modelo import (  # noqa: E402
    AlocacaoManual,
    ResultadoConferencia,
)
from parser.excel import ErroLeituraExcel  # noqa: E402
from parser.registro import hash_curto, registrar_excecao  # noqa: E402
from relatorio import gerar_excel, nome_excel, nomes_sem_colisao, zip_relatorios  # noqa: E402

MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

st.set_page_config(page_title="Conferência de Razão de Fornecedores", layout="wide")

# Uploader em PORTUGUES: o cromo do st.file_uploader ("Upload",
# "200MB per file") nao tem i18n nativa (doc 1.58 conferida) — troca de TEXTO
# via CSS, apresentacao pura, zero logica. Os data-testids valem pra 1.58
# PINADA no requirements; subir a versao = conferir o roteiro (uploader PT).
st.markdown("""<style>
[data-testid="InputInstructions"] { display: none; }
@media (prefers-color-scheme: light) {
  [data-testid="stTabs"] [role="tab"]:is([aria-selected="true"], :hover, :focus-visible),
  [data-testid="stTabs"] [role="tab"]:is([aria-selected="true"], :hover, :focus-visible) p {
    color: #ee0000 !important; /* provisório: cor definida só aqui. */ } }
[data-testid="stFileUploaderDropzoneInstructions"] > * { display: none; }
[data-testid="stFileUploaderDropzoneInstructions"]::after {
  content: "até 200MB por arquivo · XLS, XLSX"; }
/* SO o botao de upload (secondary); o X de remover e o + dos cards são
   borderlessIcon e ficam intocados */
[data-testid="stFileUploaderDropzone"] [data-testid="stBaseButton-secondary"] > * {
  display: none; }
[data-testid="stFileUploaderDropzone"] [data-testid="stBaseButton-secondary"]::after {
  content: "Escolher arquivos"; font-size: 0.875rem; }
/* texto dos botoes de exportar da sidebar a ESQUERDA -- nome curto
   e longo (que quebra em 2 linhas) ficam alinhados; a largura igual vem do
   width="stretch" nativo do st.download_button */
[data-testid="stSidebar"] [data-testid="stDownloadButton"] button {
  justify-content: flex-start; text-align: left; }
[data-testid="stSidebar"] [data-testid="stDownloadButton"] button > div,
[data-testid="stSidebar"] [data-testid="stDownloadButton"] button > div > span {
  justify-content: flex-start; }
[data-testid="stSidebar"] [data-testid="stDownloadButton"] button p {
  text-align: left; }
/* Margem lateral do layout wide 5rem -> 2.5rem: a composicao de 8 colunas
   (num caso, ~766px) cabe a 1200px com a sidebar aberta, sozinha e no lote
   (a moldura de cada conta no lote come 32px; com 3rem ainda rolava). Mesma
   media query do Streamlit 1.58 (736px + 2*(5rem - 1rem)); abaixo dela o
   padding nativo de 1rem fica intocado */
@media (min-width: calc(736px + 8rem)) {
  [data-testid="stMain"] [data-testid="stMainBlockContainer"] {
    padding-left: 2.5rem; padding-right: 2.5rem; } }
</style>""", unsafe_allow_html=True)


# === Estado de sessao das alocacoes manuais =================================
# Estado manual: guarda DECISOES, nunca resultado do motor. Guarda
# também a leitura Busca e os filtros; o motor continua rerodando. O motor
# reroda do zero a cada clique (1,9 a 37,6 ms por arquivo, medido), entao nao ha
# o que invalidar. Chave por ARQUIVO e CONTA: uma razao traz N contas e cada uma
# tem seu balde.
_PREFIXO = "aloc::"


def _chave_alocacoes(arquivo: str, conta: str) -> str:
    return f"{_PREFIXO}{arquivo}::{conta}"


def _alocacoes_do_arquivo(arquivo: str) -> dict[str, list]:
    """{chave da conta: alocacoes} lido do estado ANTES de processar -- e por
    isso que a chave carrega o codigo da conta (com _2, _3 quando o codigo se
    repete no arquivo): aqui ainda nao se leu o arquivo."""
    prefixo = f"{_PREFIXO}{arquivo}::"
    return {chave[len(prefixo):]: list(valor)
            for chave, valor in st.session_state.items()
            if chave.startswith(prefixo) and valor}


def _clique_protegido(lugar):
    """Erro num clique (on_click/on_change) não derruba a página: vai pro registro e a frase da ação aparece
    na execução seguinte NO LUGAR da tela onde a ação aconteceu (`lugar(*args)` = o ponto; ver `_erro_da_acao`):
    a frase no topo ficava fora da área visível quando o clique era dentro de um item (medido pelo revisor)."""
    def decorador(funcao):
        @functools.wraps(funcao)
        def protegida(*args, **kwargs):
            try:
                return funcao(*args, **kwargs)
            except Exception:
                registrar_excecao(_log, "erro inesperado na acao (%s)", funcao.__name__)
                st.session_state["erro::acao"] = lugar(*args)
        return protegida
    return decorador


def _erro_da_acao(lugar: str) -> None:
    """A frase da ação que falhou, no ponto `lugar`. A marca NÃO é consumida aqui: Listar contas e Buscar redesenham a
    tela com `st.rerun()` logo depois, e a frase sumia com o desenho interrompido; quem consome é o fim do corpo."""
    if st.session_state.get("erro::acao") == lugar:
        st.session_state["erro::acao::desenhada"] = True
        st.error(markdown_seguro(ERRO_CLIQUE))


@_clique_protegido(lambda chave, item_id, widget, *_: f"item::{widget}")
def _aplicar_alocacao(chave_estado: str, item_id: str, widget: str,
                      por_rotulo: dict, sugestao=None) -> None:
    """on_click: muta o estado ANTES do rerun (no corpo do script a decisao se
    perderia). A tela nao valida nada -- quem recusa destino e o core.

    O seletor guarda TEXTO, nao a Opcao: estado de widget com objeto e' fragil
    (o proprio AppTest nao consegue reproduzir a interacao). O mapa rotulo ->
    Opcao vem por args, capturado no render que desenhou este botao.

    A alocacao sai marcada quando o contador CONFIRMOU a proposta (a opcao
    escolhida e a que veio sugerida). Escolheu outra linha -> sem marca. E
    registro do que ele decidiu NESTE clique, nao derivacao viva: numa execucao
    seguinte o motor pode sugerir outra coisa, e isto nao se reescreve."""
    opcao = por_rotulo[st.session_state[f"destino::{widget}"]]
    rotulo = texto_digitado(st.session_state.get(f"rotulo::{widget}", ""))
    st.session_state.setdefault(chave_estado, []).append(
        AlocacaoManual(item_id=item_id, destino=opcao.destino,
                       alvo=opcao.alvo, rotulo=rotulo.strip(),
                       criterio_sugerido=(sugestao.criterio if opcao.sugerida
                                          else None)))


@_clique_protegido(lambda chave, indice: f"decisoes::{chave}")
def _desfazer_alocacao(chave_estado: str, indice: int) -> None:
    """Desfazer nao reverte nada: tira da lista e o motor reroda sem ela."""
    alocacoes = st.session_state.get(chave_estado, [])
    if 0 <= indice < len(alocacoes):
        del alocacoes[indice]


def _processar_upload_excel(uploaded, chave: str | None = None
                            ) -> ResultadoProcessamento:
    """Salva o upload num arquivo temporario (o parser le caminho, nao bytes) e
    devolve o resultado do motor. I/O e' papel da casca; o core nao toca disco.
    O nome do upload vai ao parser pelo parametro `nome`, e e' ele que as
    mensagens de erro mostram; o temporario tem nome curto."""
    tmp = tempfile.NamedTemporaryFile(delete=False)   # nome curto
    caminho = tmp.name
    try:
        with tmp:                     # escreve e fecha o handle
            tmp.write(uploaded.getbuffer())
        return processar_excel(caminho, _alocacoes_do_arquivo(chave or uploaded.name),
                               nome=pathlib.Path(uploaded.name).name)
    finally:
        os.unlink(caminho)            # limpa mesmo se o write falhar


# === Zona 2 — Veredito ======================================================
def _zona_veredito(res: ResultadoConferencia) -> None:
    severidade, titulo = status_conta(res.achados)
    if severidade == FECHA:
        # a resposta no lugar do veredito tecnico -- "quanto e do que"
        # a resposta leva 2+ "R$" -> escapa, senao vira LaTeX
        st.success(markdown_seguro(resposta_conferido(res) or titulo), icon="✅")
    elif severidade == INCOMPLETO:
        st.warning(markdown_seguro(titulo), icon="🪣")
        contexto = contexto_incompleto_texto(res.achados, res.ponte)
        if contexto:                # traduz o amarelo: qual gap e quem o explica
            st.caption(markdown_seguro(contexto))
    else:  # DIVERGENCIA
        st.error(markdown_seguro(titulo), icon="❌")


# column_config EXPLICITO. Largura None = "sized to fit the cell contents"
# (doc 1.58) — coluna do tamanho do que esta escrito; moeda alinhada a
# DIREITA (conferente le coluna de dinheiro pela virgula). Valores ja chegam
# FORMATADOS do apresentacao.py (strings) -- aqui so' se distribui espaco.
def _col_conteudo(alinhamento="left"):
    return st.column_config.TextColumn(width=None, alignment=alinhamento)


# a composicao tem LARGURA FIXA em pixels, e nao por conteudo, porque
# o TOTAL e' uma segunda grade logo abaixo e duas grades so' alinham coluna a
# coluna com a mesma largura nas duas. Com width="stretch" a sobra da tela e'
# repartida igual entre as colunas (doc 1.58) -- igual nas duas grades.
# larguras COMPACTAS, pelo cabecalho e pelo maior conteudo
# da visao padrao -- rotulo do TOTAL na NF ("Total em aberto"), moeda
# ate a casa do milhao. Alvo: 1200px com a sidebar aberta, sem rolagem
# lateral. NF mais longa que isso (transferencia) pode sair cortada; o
# Excel traz o texto inteiro.
_LARGURAS_COMPOSICAO = {
    "NF": 168, "Data NF": 82, "Valor compra": 92, "Total pago": 92,
    "Retido": 92, "Baixa adiant.": 92, "Alocado à mão": 92,
    "EM ABERTO": 92, "Última quitação": 90, "Pago antes da NF no razão": 90,
    "Idade (dias)": 56,
}
_DIREITA = {"Valor compra", "Total pago", "Retido", "Baixa adiant.",
            "Alocado à mão", "EM ABERTO", "Idade (dias)"}
def _config_composicao(variaveis: dict[str, int], ajuda_nf: str | None = None) -> dict:
    """NF, "Antes da NF" e Idade com a largura do maior texto visivel
    desta tabela (larguras_composicao); as demais, as fixas acima. UMA config
    pras duas grades (tabela e TOTAL), senao as colunas desalinham."""
    larguras = {**_LARGURAS_COMPOSICAO, **variaveis}
    return {
        nome: st.column_config.TextColumn(
            ROTULO_CURTO.get(nome),          # curto so' na tela
            width=largura, alignment="right" if nome in _DIREITA else "left",
            # tooltip sem jargao; na grade do TOTAL, a NF
            # explica o escopo do rotulo curto
            help=(ajuda_nf if nome == "NF" and ajuda_nf else ajuda_coluna(nome)))
        for nome, largura in larguras.items()
    }


# === Zona 2.5 — Placar =====================================================
# Usuario: colaborador SEM experiencia contabil (premissa fixa). Os
# rotulos seguem o trabalho -- compor ate bater com o Dominio: o ALVO, ONDE
# ESTOU, O QUE FALTA. ("Composicao / Dominio (a
# pagar) / Delta" nomeava os dados, nao o trabalho.) A contagem de itens saiu
# do placar: como quarta metrica ela truncava ("0 em revisao · 5 d...") e nao e
# dinheiro -- virou a linha pequena logo abaixo.
def _zona_placar(res: ResultadoConferencia, banco: bool = False) -> None:
    placar = placar_composicao(res)
    alvo, montada, falta = st.columns(3)
    alvo.metric(rotulo_saldo(banco), f"R$ {placar['dominio']}")
    # o nome do que e' -- a soma das notas em aberto
    montada.metric("Total das notas em aberto", f"R$ {placar['composicao']}")
    falta.metric(placar["rotulo_delta"], f"R$ {placar['delta']}")
    pendente = f"{placar['itens']} em revisão"
    if placar["delta_extra"]:                         # balde misto
        pendente += f" · {placar['delta_extra']}"
    if placar["decisoes"]:
        pendente += f" · {placar['decisoes']} decidido(s)"
    st.caption(markdown_seguro(pendente))
    # o verde daqui e a CONQUISTA do trabalho manual, nao um segundo veredito:
    # conta que ja fechava sozinha nao ganha duas caixas verdes dizendo o mesmo
    if placar["fechada"] and placar["decisoes"]:
        st.success(markdown_seguro(composicao_fechada_texto(banco)),
                   icon="✅")
    elif placar["ressalva"]:
        st.caption(markdown_seguro(
            ressalva_composicao_texto(placar['ressalva'], banco=banco)))


# === Zona 3 — Composicao ====================================================
# o TOTAL e' COMPONENTE PROPRIO, logo abaixo da tabela. Dentro dela ele
# ficava no fim da rolagem interna (invisivel na pratica) e entrava na
# ordenacao por clique -- e a 1.58 nao tem linha fixa nem como desligar o sort
# (doc conferida). Fundo cinza translucido: soma nao e' boa nem ruim, e o
# translucido le igual no tema claro e no escuro.
_FUNDO_TOTAL = "background-color: rgba(128, 128, 128, 0.18)"


# linha que nao e' nota ((saldo anterior), (transferencia...),
# (pago a maior lote X)) em CINZA -- o cinza le nos dois temas, como o fundo
# do TOTAL. Italico nao: o grid da 1.58 ignora font-style (visto na tela)
_ESTILO_SEM_NOTA = "color: rgba(128, 128, 128, 0.95)"


def _com_linhas_sem_nota(tabela: list[dict], itens):
    """A tabela pronta com o estilo nas linhas que nao sao nota. Sem nenhuma,
    vai a lista crua, como sempre."""
    marcas = linhas_sem_nota(itens)
    if not any(marcas):
        return tabela
    return pd.DataFrame(tabela).style.apply(
        lambda l: [_ESTILO_SEM_NOTA if marcas[l.name] else ""] * len(l), axis=1)


def _zona_composicao(res: ResultadoConferencia, chave: str = "", banco: bool = False) -> None:
    st.markdown("**Composição do saldo**")
    st.caption(markdown_seguro(saldo_dominio_texto(res.conta, banco=banco)))
    # por padrao, so' o que esta EM ABERTO -- e' o que responde "do que e'
    # o saldo". As quitadas (a foto completa) ficam atras do toggle, e
    # o TOTAL acompanha o que esta visivel, com o escopo no rotulo.
    rotulo_toggle = rotulo_toggle_quitadas(res)
    com_quitadas = bool(rotulo_toggle) and st.toggle(
        markdown_seguro(rotulo_toggle), value=False, key=f"quitadas_{chave}")
    if com_quitadas:
        linhas, totais = itens_da_tabela(res), res.totais_tabela
        rotulo_total = ROTULO_TOTAL_COM_QUITADAS
    else:
        linhas, totais = res.itens_em_aberto, res.totais_em_aberto
        rotulo_total = ROTULO_TOTAL_EM_ABERTO
    tabela = composicao_linhas(linhas, juros=nfs_com_possivel_juros(res.achados))
    # coluna sem dado em nenhuma linha visivel sai da tela -- nas
    # DUAS grades, pela mesma lista (column_order), pra o TOTAL continuar
    # alinhado. O Excel mantem todas. A "Idade" so' com o toggle.
    escondidas = [c for c in colunas_visiveis(linhas)
                  if c in SO_COM_TODAS_AS_COLUNAS]
    todas = bool(escondidas) and st.toggle(
        "Mostrar todas as colunas", value=False, key=f"colunas_{chave}")
    visiveis = colunas_da_tela(linhas, todas)
    larguras = larguras_composicao(tabela, rotulo_total)
    config = _config_composicao(larguras)
    # height="content": a tabela inteira na pagina, sem rolagem interna -- o
    # TOTAL fica colado na ultima linha e nenhuma barra de rolagem rouba
    # largura de uma grade e nao da outra
    st.dataframe(_com_linhas_sem_nota(tabela, linhas), hide_index=True,
                 width="stretch", height="content",
                 column_config=config, column_order=visiveis)
    if tabela and totais is not None:                # soma pronta do core
        total = pd.DataFrame([total_linha(totais, rotulo_total)])
        st.dataframe(total.style.apply(lambda l: [_FUNDO_TOTAL] * len(l), axis=1),
                     hide_index=True, width="stretch",
                     column_config=_config_composicao(
                         larguras, ajuda_total(rotulo_total)),
                     column_order=visiveis)
    # do total ao Dominio numa linha, sem abrir a ponte. O texto
    # comeca com + ou -: a barra escapa, senao o markdown faz item de lista
    curta = ponte_curta_do_total(res, banco=banco)
    if tabela and curta:
        st.caption(md_ja_escapado("\\" + markdown_seguro(curta)))
    # ex.: baixa parcial, desempate; sem a do saldo anterior
    for nota in notas_composicao_texto(linhas, linha_anterior=False):
        st.caption(f"ℹ️ {markdown_seguro(nota)}")
    _zona_ponte(res, chave, banco=banco)


# === Zona 3.1 — Ponte do saldo ==============================================
# Usuario: colaborador SEM experiencia contabil (premissa fixa).
# Tabela markdown e nao st.dataframe: sao poucas linhas fixas
# de leitura, sem ordenar nem filtrar, e o markdown deixa a ponte do tamanho
# do conteudo (o dataframe esticaria pra largura da tela). O UNICO ponto de
# cor e' a marca da ultima linha (verde so' com balde vazio) -- o
# resto e' movimento neutro; os (=) vao em
# negrito porque sao onde a conta para.
def _zona_ponte(res: ResultadoConferencia, chave: str = "", banco: bool = False) -> None:
    if res.ponte is None:
        return
    severidade, texto = status_ponte(res)
    # amarelo = a cor do st.warning do veredito INCOMPLETO
    cor = {PONTE_OK: "green", PONTE_PENDENTE: "yellow"}.get(severidade, "red")
    # expander FECHADO, com o resultado no titulo -- a ponte e' a prova,
    # nao a resposta (a resposta esta no topo). ABRE sozinho quando diverge:
    # ai ela e' o que explica o problema.
    with st.expander(markdown_seguro(titulo_ponte(res)),
                     expanded=severidade == PONTE_DIVERGE):
        todas = st.toggle("Mostrar todas as linhas", value=False,
                          key=f"ponte_{chave}")
        linhas = ponte_linhas_tela(res, todas, banco=banco)
        tabela = ["| Movimento | R$ | Conferência |", "|:--|--:|:--|"]
        for i, linha in enumerate(linhas):
            rotulo = markdown_seguro(linha["Linha"])
            valor = markdown_seguro(linha["Valor"])
            ultima = i == len(linhas) - 1
            if e_subtotal(linha["Linha"]) or ultima:
                rotulo, valor = f"**{rotulo}**", f"**{valor}**"
            marca = ""
            if ultima:
                # o status vem do VEREDITO; so' o rotulo curto em negrito
                cabeca, _, resto = markdown_seguro(texto).partition(" ")
                marca = f":{cor}[**{cabeca}**{' ' + resto if resto else ''}]"
            tabela.append(f"| {rotulo} | {valor} | {marca} |")
        st.markdown(md_ja_escapado("\n".join(tabela)))   # celula a celula
        # o TOTAL da tela agora diz o escopo, mas "Total pago"
        # ainda pode ficar abaixo de "(-) Pagamentos casados" (pagamento que
        # consumiu o saldo anterior) -- a nota fica, so' que DENTRO da ponte
        nota = nota_fora_da_tabela(res.totais_tabela)
        if nota:
            st.caption(f"ℹ️ {markdown_seguro(nota)}")
    _zona_fechado(res)


# === Zona 3.2 — Fechado por saldo zero ======================================
# Usuario: colaborador SEM experiencia contabil. Expander FECHADO: na
# maioria das vezes e' um pagamento sem nota que bate exato com as notas e
# nao pede nada -- a frase diz isso. ABRE sozinho quando algum trecho nao
# bate (ai e' pendencia de verdade). Nada daqui e' alocavel. Tabelas enxutas:
# NF | Data | Valor e Lote | Data | Valor | Historico.
def _zona_fechado(res: ResultadoConferencia) -> None:
    fechado = res.fechado
    if fechado is None or not fechado.tem_conteudo:
        return
    anterior = nota_anterior_fechado(fechado)
    blocos = fechado.blocos
    if not blocos:
        # so' a linha do saldo anterior, zerada (a baixa de um caso): nao e'
        # pendencia, mas nao some
        if anterior:
            st.caption(f"ℹ️ {markdown_seguro(anterior)}")
        return
    with st.expander(markdown_seguro(titulo_fechado(fechado)),
                     expanded=abrir_fechado(fechado)):
        for bloco in blocos:
            st.markdown(markdown_seguro(frase_bloco(bloco)))
            # tabela HTML propria de leitura -- o historico QUEBRA
            # LINHA em vez de cortar e o Valor fica a direita, como toda
            # coluna de dinheiro da tela (o st.table ignorava o alinhamento).
            # tabela_html escapa HTML e cifrao celula a celula.
            if bloco.itens:
                st.markdown(md_ja_escapado(tabela_html(bloco_linhas_nfs(bloco))),
                            unsafe_allow_html=True)
            if bloco.balde:
                st.markdown(md_ja_escapado(tabela_html(bloco_linhas_sem_nf(bloco))),
                            unsafe_allow_html=True)
        if anterior:
            st.caption(markdown_seguro(anterior))


# === Zona 4 — Balde + Divergencias (duas secoes SEPARADAS) ==================
# Balde em LARGURA TOTAL: e' a fila de trabalho do revisor e o historico e' a
# evidencia -- meia coluna truncava.
# === Zona 3.5 — Decisoes desta sessao =======================================
def _zona_decisoes(res: ResultadoConferencia, chave: str) -> None:
    alocacoes = st.session_state.get(chave, [])
    if not alocacoes:
        return
    linhas = decisoes_linhas(alocacoes, res)
    st.markdown(f"#### ✍️ Decisões desta sessão ({len(linhas)})")
    _erro_da_acao(f"decisoes::{chave}")
    for linha in linhas:
        texto, botao = st.columns([9, 1])
        # lote/valor/destino sao dado do arquivo e texto do contador -> escapa
        texto.markdown(markdown_seguro(decisao_texto(linha)))
        if linha["erro"]:
            texto.markdown(f":red[{markdown_seguro(linha['erro'])}]")
        botao.button("Desfazer", key=f"desfazer::{chave}::{linha['indice']}",
                     on_click=_desfazer_alocacao, args=(chave, linha["indice"]))


def _controle_de_alocacao(res: ResultadoConferencia, det: dict,
                          chave: str) -> None:
    """O seletor + aplicar dentro da caixinha do item. A tela NAO decide: monta
    a AlocacaoManual e entrega ao motor, que valida e recusa."""
    widget = f"{chave}::{det['item_id']}"
    sugestao = det["sugestao"]
    opcoes = opcoes_de_alocacao(res.itens, det["quantia"], sugestao)
    por_rotulo = {o.rotulo: o for o in opcoes}
    # a evidencia vem ANTES do seletor: o contador le por que o motor propos
    # aquilo e so' entao olha pro campo ja preenchido
    if det["sugestao_frase"]:
        st.caption("Sugestão do motor: "
                   + markdown_seguro(det["sugestao_frase"]))
    escolha, acao = st.columns([5, 1])
    escolhido = escolha.selectbox("Alocar em", list(por_rotulo),
                                  index=indice_sugerido(opcoes),
                                  key=f"destino::{widget}",
                                  placeholder="linha de destino")
    opcao = por_rotulo.get(escolhido)
    if opcao is not None and opcao.pede_rotulo:
        st.text_input(
            "Justificativa" if opcao.rotulo_obrigatorio else "Nome da linha",
            key=f"rotulo::{widget}",
            placeholder=("por que não pertence a esta composição"
                         if opcao.rotulo_obrigatorio
                         else "opcional — em branco usa o lote"))
    acao.button("Aplicar", key=f"aplicar::{widget}", disabled=opcao is None,
                on_click=_aplicar_alocacao,
                args=(chave, det["item_id"], widget, por_rotulo, sugestao))
    _erro_da_acao(f"item::{widget}")


# === Zona 4 — Balde + Divergencias (duas secoes SEPARADAS) ==================
def _zona_balde_e_divergencias(res: ResultadoConferencia, chave: str, banco: bool = False,
                               rotulo_numero: str = "Lote") -> None:
    # o mesmo nome da planilha e do veredito ("itens sem destino")
    st.markdown("#### 🪣 Itens sem destino")
    if res.balde:                             # ItemRevisao sempre tem lancamentos
        # o placar nao e sticky de proposito (nao dobrar a divida de CSS preso a
        # data-testid): esta linha repete o essencial onde o olho esta
        st.caption(f"**{markdown_seguro(resumo_do_trabalho(res))}**")
        # triagem DENTRO do balde: onde comecar (materialidade) e o que
        # ha (contagem por motivo). A ORDEM da tabela nao muda -- segue
        # cronologica; estas linhas so apontam o peso.
        materialidade = frase_materialidade(res.balde,
                                            gap_incompleto(res.achados))
        if materialidade:                     # so com 3+ itens e gap conhecido
            st.caption(markdown_seguro(materialidade))    # embute R$: escapa
        contagem = frase_contagem_motivos(res.balde)
        if contagem:
            st.caption(markdown_seguro(contagem))
        # quanto do balde ja vem com destino proposto. Fica AQUI, junto das
        # outras frases de triagem, pra o conferente saber o tamanho do trabalho
        # antes de abrir a primeira caixinha.
        sugeridos = frase_sugestoes(res.balde)
        if sugeridos:
            st.caption(markdown_seguro(sugeridos))
        # UMA caixinha por item, em ordem cronologica. Decisao de produto:
        # a tabela HTML que ficava aqui em cima MORREU — ela e as caixinhas
        # diziam a mesma coisa, e so' a caixinha carrega o historico integral e
        # o seletor de alocacao. O rotulo da caixinha (valor, data, motivo,
        # inicio do historico) e' a varredura; por isso elas comecam FECHADAS,
        # revertendo o default aberto de antes.
        for det in balde_detalhes(res.balde, contexto_de_avisos(res), banco=banco,
                                  rotulo_numero=rotulo_numero):
            # key ESTAVEL por item (+ on_change) -- e o que poe o estado de
            # expansao no servidor. Sem ela o `expanded` e constante e o estado
            # so' vive no browser, preso a identidade (rotulo + posicao): alocar
            # encolhe a lista, as posicoes deslizam e todas as caixinhas
            # remontam com o default. Com a key presa ao
            # item_id, tirar um item nao perturba a expansao dos outros.
            with st.expander(md_ja_escapado(det["titulo"]), expanded=False,
                             key=f"cx::{chave}::{det['item_id']}",
                             on_change="rerun"):
                # balde_detalhes ja escapa estes campos na origem
                st.caption(md_ja_escapado(det["localizacao"]))
                st.markdown(md_ja_escapado(det["motivo"]))
                # pagamento datado antes da emissao da NF que o item cita
                # ou que o motor sugere. Contexto de DECISAO -- por isso aqui,
                # colado no motivo, e nao no painel de alertas a tres secoes
                # daqui. Nao muda destino e nao rotula de adiantamento.
                if det["aviso"]:
                    st.warning(md_ja_escapado(det["aviso"]), icon="⚠️")
                # historico e' CRU no dict (evidencia); citacao HTML de
                # texto literal (o markdown faria titulo, link, emoji e icone)
                st.markdown(md_ja_escapado("**Histórico integral:**\n"
                                           + historico_html(det["historico"])),
                            unsafe_allow_html=True)
                if det["aloca"]:
                    _controle_de_alocacao(res, det, chave)
    else:
        # fato. "Todo pagamento casou com sua NF" era falso quando
        # o periodo zerado compensou pagamento sem nota
        st.caption("Nenhum item sem destino.")

    linhas = divergencias(res.achados)
    # o X vermelho so' quando HA divergencia -- com "Nenhuma." ele
    # assustava. Sem divergencia, icone neutro (cinza, mesma altura)
    st.markdown(md_ja_escapado(titulo_divergencias(bool(linhas))))   # constante
    if linhas:
        st.dataframe(linhas, hide_index=True, width="stretch")
    else:
        st.caption("Nenhuma.")

    # o alerta do periodo zerado ja abre a secao propria, logo
    # abaixo da ponte -- aqui ele so' repetiria (a planilha e a triagem o tem)
    proprios = [a for a in res.achados
                if a.codigo != "periodo_zerado_com_pendencia"]
    # o que o motor NAO decidiu fica em caixa, como antes; o que ele
    # decidiu por regra aprovada e' prova -- expander FECHADO, com a contagem
    observacoes = observacoes_tela(proprios)      # juros agrupados
    registrados = frases_alertas(alertas_registrados(proprios))
    if observacoes or registrados:
        # titulo PROPRIO. Coladas em "Divergências — Nenhuma.", as
        # caixas azuis liam como divergencia e contradiziam o "Nenhuma".
        st.markdown("#### ℹ️ Observações")
    for obs in observacoes:
        # a frase embute R$/lote de celula: escapa (senao par de R$ vira
        # LaTeX e come o cifrao); formato BR vem da apresentacao.
        # A lista escapa item a item (markdown_seguro tira a quebra)
        texto = markdown_seguro(obs.frase) + "".join(
            f"\n- {markdown_seguro(item)}" for item in obs.lista)
        st.info(md_ja_escapado(texto), icon="ℹ️")
    if registrados:
        with st.expander(markdown_seguro(f"{REGISTRADO} ({len(registrados)})"),
                         expanded=False):
            for frase in registrados:
                st.markdown(markdown_seguro(f"- {frase}"))


def _render_conta(res: ResultadoConferencia, arquivo: str | None = None,
                  chave_arquivo: str = "", chave_conta: str = "", banco: bool = False,
                  em_lote: bool = False, rotulo_numero: str = "Lote",
                  ancora: str | None = None) -> None:
    """`chave_arquivo` e a chave do arquivo no lote: o nome do UPLOAD, com
    sufixo (_2, _3) quando o nome se repete (sempre presente); `arquivo` so'
    vai pro titulo quando ha lote. A chave do estado nao pode depender de
    estar em lote ou nao, senao a alocacao se perde ao trocar de modo."""
    # no lote a borda do container ja separa as contas -- a
    # divisoria so' abria espaco vazio antes do titulo
    if arquivo is None and not em_lote:
        st.divider()
    # nome do fornecedor + nome do arquivo sao dado externo -> titulo_conta
    # escapa
    if ancora is not None:
        # Destino nativo do link; o heading do Streamlit não remonta neste id.
        st.html(f'<span id="{ancora}" style="position:absolute"></span>')
    st.subheader(md_ja_escapado(titulo_conta(res.conta, arquivo)),
                 anchor=f"titulo-{ancora}" if ancora is not None else None)
    chave = _chave_alocacoes(chave_arquivo, chave_conta or res.conta.codigo)
    _zona_veredito(res)
    _zona_placar(res, banco=banco)
    _zona_composicao(res, chave, banco=banco)
    _zona_decisoes(res, chave)
    _zona_balde_e_divergencias(res, chave, banco=banco, rotulo_numero=rotulo_numero)


# === Zona 1 — Upload (lote) =================================================
# Entrada SO Excel. PDF fica fora de escopo: o PDF que o Dominio exporta e'
# lossy (imagem/OCR, colunas embaralhadas); o Excel e' a fonte estruturada e
# confiavel, do mesmo clique no Dominio.

# Teto do lote: cada arquivo vira secoes inteiras na pagina e o processamento
# compete por RAM no servidor compartilhado do escritorio. Acima do teto a tela
# pede pra dividir e NAO processa nada — nunca "so os 10 primeiros" em
# silencio (lote parcial invisivel e' pior que recusa clara).
MAX_ARQUIVOS_POR_LOTE = 10
# Contas desenhadas por vez na pagina (o total da PAGINA, dividido entre os arquivos do lote):
# pagina grande demais enche a fila de envio do Streamlit e o navegador recebe a tela cortada, sem erro.
MAX_CONTAS_NA_TELA = 10


@dataclass
class _EntradaLote:
    """Uma entrada do lote (upload ou Busca): resultados OU mensagem de erro
    amigavel. Fiacao de tela, zero logica. (A anotacao de reparo saiu da
    tela — reparo com self-check verde e' arquivo normal pro colaborador; o
    rastro tecnico e' o logging.info do parser.)

    `dados` sao os BYTES do upload, guardados porque a aba fiel da exportacao
    se abre DELES — copia do arquivo, nunca reconstrucao do parseado."""
    nome: str
    resultados: list | None = None
    erro: str | None = None
    dados: bytes | None = None
    chave: str = ""   # nome unico no lote (chave do estado da tela)
    rotulo_numero: str = "Lote"


def _frase_do_teto(arquivo: str, e: ArquivoAcimaDoLimite) -> FraseAcimaDoLimite:
    if len(e.contas_acima) == 0:
        return FraseAcimaDoLimite(arquivo_com_contas_demais_texto(arquivo, e.total_contas, MAX_CONTAS_POR_ARQUIVO))
    if len(e.contas_acima) == 1:
        codigo, n = e.contas_acima[0]
        return FraseAcimaDoLimite(arquivo_com_conta_grande_texto(arquivo, codigo, n, MAX_LANCAMENTOS_POR_CONTA))
    codigo, n = max(e.contas_acima, key=lambda c: c[1])
    return FraseAcimaDoLimite(arquivo_com_contas_grandes_texto(
        arquivo, len(e.contas_acima), codigo, n, MAX_LANCAMENTOS_POR_CONTA))


def _processar_lote(arquivos) -> list[_EntradaLote]:
    """Processa cada arquivo em try PROPRIO: falha NAO derruba o lote — vira
    entrada de erro (linha na triagem) e os demais processam. O tempfile e'
    criado e removido DENTRO de _processar_upload_excel (no finally):
    mesmo falhando no meio do lote, nada vaza."""
    entradas: list[_EntradaLote] = []
    chaves = nomes_sem_colisao([u.name for u in arquivos])
    for uploaded, chave in zip(arquivos, chaves):
        try:
            proc = _processar_upload_excel(uploaded, chave)
        except ErroLeituraExcel as e:
            # mensagem ja e' pra humano: diz arquivo/conta/linha e o que fazer
            entradas.append(_EntradaLote(nome=uploaded.name, erro=str(e),
                                         chave=chave))
        except ArquivoAcimaDoLimite as e:         # teto de entrada: o arquivo inteiro e' recusado, o lote segue
            entradas.append(_EntradaLote(nome=uploaded.name, erro=_frase_do_teto(uploaded.name, e), chave=chave))
        except Exception:                         # inesperado -> nao quebra o lote
            # classe e texto cru da excecao (com traceback) so' no log
            registrar_excecao(_log, "erro inesperado processando o arquivo %s", hash_curto(uploaded.getbuffer()))
            entradas.append(_EntradaLote(
                nome=uploaded.name,
                erro=(f"Erro inesperado processando '{uploaded.name}'; nenhum "
                      f"resultado foi gerado pra este arquivo."), chave=chave))
        else:
            entradas.append(_EntradaLote(nome=uploaded.name,
                                         resultados=proc.resultados,
                                         dados=bytes(uploaded.getbuffer()),
                                         chave=chave, rotulo_numero=proc.rotulo_numero))
    return entradas


def _limpar_cache_do_upload(chaves: list[str]) -> None:
    """Solta exportações de uploads que saíram do lote, só nesta sessão."""
    prefixo = "upload::excel::"
    atuais = {prefixo + chave for chave in chaves}
    fora = [chave for chave in st.session_state
            if chave.startswith(prefixo) and chave not in atuais]
    for chave in fora:
        del st.session_state[chave]
    if fora:
        st.session_state.pop("exportacao::zip", None)


def _excel_do_upload(entrada: _EntradaLote) -> bytes:
    """Foto por valor na sessão, incluindo bytes enviados e decisões da conta."""
    chave = f"upload::excel::{entrada.chave or entrada.nome}"
    cache = st.session_state.get(chave)
    if cache is None:
        cache = {"trava": Lock(), "assinatura": None, "dados": None}
        st.session_state[chave] = cache
    assinatura = (entrada.nome, sha256(entrada.dados).digest(), entrada.resultados)
    with cache["trava"]:
        if cache["assinatura"] != assinatura:
            dados = gerar_excel(entrada.resultados, entrada.dados, entrada.nome)
            # Só publica após sucesso; falha aparece no desenho e permite nova tentativa.
            cache["assinatura"] = deepcopy(assinatura)
            cache["dados"] = dados
        return cache["dados"]


def _zip_do_lote(downloads: list[tuple[str, str, bytes]]) -> bytes:
    """A ordem, os nomes e o conteúdo das planilhas identificam o ZIP da sessão."""
    chave = "exportacao::zip"
    cache = st.session_state.get(chave)
    if cache is None:
        cache = {"trava": Lock(), "assinatura": None, "dados": None}
        st.session_state[chave] = cache
    assinatura = tuple((nome, sha256(dados).digest()) for _, nome, dados in downloads)
    with cache["trava"]:
        if cache["assinatura"] != assinatura:
            dados = zip_relatorios([(nome, dados) for _, nome, dados in downloads])
            cache["assinatura"] = assinatura
            cache["dados"] = dados
        return cache["dados"]


def _downloads_do_lote(lote: list[_EntradaLote], falhas: list | None = None
                       ) -> list[tuple[str, str, bytes]]:
    """Download da foto válida; entrada banco pendente não exporta a foto antiga.
    Cada planilha num try PRÓPRIO; a que falha vai pro registro e pra `falhas` (se dada) e o
    resto segue. Sem o argumento a lista volta como sempre, mas a falha não propaga."""
    _limpar_cache_do_upload([e.chave or e.nome for e in lote])
    downloads = []
    for entrada in lote:
        if not entrada.resultados:
            continue
        try:
            dados = _excel_do_upload(entrada)
            nome = nome_excel(entrada.nome)
        except Exception:
            registrar_excecao(_log, "erro inesperado gerando a planilha do arquivo %s", hash_curto(entrada.dados))
            if falhas is not None:
                falhas.append(entrada)
            continue
        downloads.append((entrada.nome, nome, dados))
    return downloads


def _ordem_da_triagem(lote: list[_EntradaLote]) -> list[str]:
    """Ordem em que os ARQUIVOS aparecem na triagem (problemas primeiro):
    primeira ocorrencia de cada arquivo nas linhas ja ordenadas. Fonte unica
    da ordenacao e' a propria triagem_linhas -- nada se reordena aqui."""
    ordem: list[str] = []
    for linha in triagem_linhas([(e.nome, e.resultados, e.erro) for e in lote]):
        if linha["Arquivo"] not in ordem:
            ordem.append(linha["Arquivo"])
    return ordem


def _sidebar_exportar(lote: list[_EntradaLote]) -> None:
    """Exportacao vive na SIDEBAR: com N arquivos, N+1 botoes
    empilhavam na pagina principal. ZIP no topo (so com 2+ processados,
    montado em MEMORIA), depois um botao por arquivo na MESMA ordem da
    triagem. on_click='ignore' (doc 1.58): o download acontece SEM rerun --
    clicar num botao nao reprocessa o lote inteiro."""
    falhas: list[_EntradaLote] = []
    downloads = _downloads_do_lote(lote, falhas)
    for falha in falhas:                       # o fato fica na PÁGINA (visível nos 2 modos e nos 2 temas)
        st.error(markdown_seguro(erro_planilha_do_arquivo(falha.nome)))
    resumo = []
    if len(lote) > 1:
        acima = sum(isinstance(e.erro, FraseAcimaDoLimite) for e in lote)
        resumo = resumo_envio_texto(
            len(lote), sum(bool(e.resultados) for e in lote),
            sum(e.erro is not None for e in lote) - acima,
            sum(not e.resultados and e.erro is None for e in lote),
            len(downloads), acima_do_limite=acima)
    if not downloads and not resumo:
        return
    ordem = _ordem_da_triagem(lote)
    downloads.sort(key=lambda d: ordem.index(d[0]) if d[0] in ordem else len(ordem))
    with st.sidebar:
        st.markdown("### Exportar")
        # Só anuncia o ZIP depois de seus bytes estarem prontos (O5.5b).
        pacote = _zip_do_lote(downloads) if len(downloads) > 1 else None
        for linha in resumo:
            st.caption(markdown_seguro(linha))
        if len(downloads) > 1:
            st.download_button("📦 Baixar todos (ZIP)", data=pacote,
                               file_name="conferencias.zip",
                               mime="application/zip", key="excel_zip_todos",
                               on_click="ignore", width="stretch")
        for i, (origem, nome, dados) in enumerate(downloads):
            # rotulo interpola o nome do upload (dado externo) -> escapa,
            # mesma classe do subheader
            st.download_button(f"📊 Baixar Excel — {markdown_seguro(origem)} → {markdown_seguro(nome)}",
                               data=dados, file_name=nome, mime=MIME_XLSX,
                               key=f"excel_arquivo_{i}", on_click="ignore",
                               width="stretch")


def _zona_triagem(lote: list[_EntradaLote]) -> None:
    st.markdown("### 🗂️ Triagem do lote")
    st.caption("Uma linha por conta — problemas primeiro.")
    linhas = triagem_linhas([(e.nome, e.resultados, e.erro) for e in lote])
    itens = ordem_do_lote([(e.nome, e.resultados, e.erro) for e in lote])
    janelas = _janelas_das_contas(lote, itens, desenhar=False)
    vistas: dict[int, int] = {}
    ancoras: list[str | None] = []
    for idx, res in itens:
        ancora = None
        if res is not None:
            pos_na_tela = vistas[idx] = vistas.get(idx, -1) + 1
            if idx not in janelas or janelas[idx][0] <= pos_na_tela < janelas[idx][1]:
                pos = next(i for i, r in enumerate(lote[idx].resultados) if r is res)
                ancora = f"conta-{idx}-{pos}"
        ancoras.append(ancora)
    # tabela HTML de leitura -- quebra linha em vez de rolar de
    # lado; tabela_triagem escapa HTML e cifrao celula a celula
    tabela = tabela_triagem(linhas, ancoras=ancoras)
    st.markdown(md_ja_escapado(tabela), unsafe_allow_html=True)


def _janelas_das_contas(lote: list[_EntradaLote], itens: list[tuple[int, object]], *,
                       desenhar: bool = True) -> dict[int, tuple[int, int]]:
    """Janela [inicio, fim) de contas desenhadas por arquivo, na ordem da triagem; um seletor por arquivo que
    passa dela. A pagina inteira desenha no maximo MAX_CONTAS_NA_TELA contas: a janela de cada arquivo e' a
    divisao do total pelos arquivos que tem conta."""
    totais: dict[int, int] = {}
    for idx, res in itens:
        if res is not None:
            totais[idx] = totais.get(idx, 0) + 1
    janela = max(1, MAX_CONTAS_NA_TELA // max(1, len(totais)))
    janelas: dict[int, tuple[int, int]] = {}
    for idx, total in totais.items():
        if total <= janela:
            continue
        opcoes = [contas_na_tela_texto(i + 1, min(i + janela, total), total) for i in range(0, total, janela)]
        chave = f"janela::{lote[idx].chave}"
        rotulo = (CONTAS_NA_TELA if len(totais) == 1
                  else f"{CONTAS_NA_TELA} — {markdown_seguro(sem_link_automatico(lote[idx].nome))}")
        escolhida = (st.selectbox(rotulo, opcoes, key=chave) if desenhar
                     else st.session_state.get(chave, opcoes[0]))
        k = opcoes.index(escolhida) if escolhida in opcoes else 0
        janelas[idx] = (k * janela, min((k + 1) * janela, total))
    return janelas


# Detalhe em lote: TUDO ABERTO em sequencia, um container com borda por
# conta. st.expander por conta foi avaliado e descartado: a doc manda nao
# aninhar expanders e o balde JA usa expansao por item dentro da secao —
# a triagem no topo e' o indice; o conferente desce direto na conta que quer.
def _render_lote(lote: list[_EntradaLote], em_lote: bool) -> None:
    # o detalhe desce na MESMA ordem da triagem (problemas
    # primeiro) -- a ordem vem pronta de ordem_do_lote, fonte unica
    itens = ordem_do_lote([(e.nome, e.resultados, e.erro) for e in lote])
    janelas = _janelas_das_contas(lote, itens)
    vistas: dict[int, int] = {}
    for idx, res in itens:
        entrada = lote[idx]
        if res is not None and idx in janelas:       # conta fora da janela do arquivo: nao e desenhada
            pos = vistas[idx] = vistas.get(idx, -1) + 1
            if not janelas[idx][0] <= pos < janelas[idx][1]:
                continue
        chave_conta = ""                 # posicao por IDENTIDADE (conta
        if res is not None:              # emendada 2x e' igual campo a campo)
            pos = next(i for i, r in enumerate(entrada.resultados) if r is res)
            chave_conta = chaves_das_contas([r.conta for r in entrada.resultados])[pos]
        if res is None and entrada.erro is not None:
            # erro embute nome do upload + texto de excecao/celula: escapa
            st.error(markdown_seguro(entrada.erro))
        elif res is None:
            # arquivo lido ok mas SEM nenhuma conta: nunca fica em branco em
            # silencio. Mensagem generica de proposito -- a coluna
            # Arquivo da triagem ja diz qual foi; interpolar o nome aqui
            # reintroduziria a classe de escape do nome externo.
            st.warning("Nenhuma conta de fornecedor encontrada no arquivo: "
                       "ele não tem o formato da razão de fornecedores do "
                       "Domínio.")
        elif em_lote:
            with st.container(border=True):
                _render_conta(res, arquivo=entrada.nome,
                              chave_arquivo=entrada.chave,
                              chave_conta=chave_conta,
                              em_lote=True, rotulo_numero=entrada.rotulo_numero,
                              ancora=f"conta-{idx}-{pos}")
        else:                       # 1 arquivo / 1 conta: a tela de sempre
            _render_conta(res, chave_arquivo=entrada.chave,
                          chave_conta=chave_conta,
                          rotulo_numero=entrada.rotulo_numero)


try:
    st.title("Conferência de Razão de Fornecedores")
    _reserva_da_acao = st.empty()          # onde a frase cai se o ponto da ação nao foi desenhado
    arquivos = st.file_uploader(
        f"Razões do Domínio (Excel) — até {MAX_ARQUIVOS_POR_LOTE} por lote",
        type=["xls", "xlsx"], accept_multiple_files=True)

    # Também roda sem arquivos: o lote vazio não passa por _downloads_do_lote.
    _limpar_cache_do_upload(nomes_sem_colisao([u.name for u in arquivos or []]))
    if arquivos:
        if len(arquivos) > MAX_ARQUIVOS_POR_LOTE:
            st.error(markdown_seguro(f"Lote com {len(arquivos)} arquivos — o limite é "
                     f"{MAX_ARQUIVOS_POR_LOTE} por vez; nenhum arquivo foi "
                     f"processado."))
        else:
            lote = _processar_lote(arquivos)
            contas_no_lote = sum(len(e.resultados or []) for e in lote)
            # triagem so quando ha o que triar: com 1 conta e sem erro, o resumo
            # de 1 linha e' redundante com o veredito logo abaixo — a tela fica
            # IGUAL a de sempre no caso comum de 1 arquivo / 1 conta
            em_lote = contas_no_lote > 1 or any(e.erro for e in lote)
            if em_lote:
                _zona_triagem(lote)
            _sidebar_exportar(lote)
            _render_lote(lote, em_lote)

    if st.session_state.get("erro::acao"):         # o corpo foi até o fim: a frase vale por esta execução e acaba aqui
        if not st.session_state.pop("erro::acao::desenhada", False):      # o ponto da ação não foi desenhado: no topo
            _reserva_da_acao.error(markdown_seguro(ERRO_CLIQUE))
        st.session_state.pop("erro::acao")
except FragmentHandledException:         # o Streamlit já mostrou o erro do fragmento
    raise
except Exception:
    registrar_excecao(_log, "erro inesperado montando a tela")
    st.error(markdown_seguro(ERRO_TELA))
