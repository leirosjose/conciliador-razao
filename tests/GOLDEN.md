# Golden sintético e cenários de exemplo

Sete razões de fornecedor no layout do relatório Razão do Domínio, todas inventadas
(empresas e fornecedores com FICTICIA/FICTICIO no nome, CNPJ 00.000.000/0000-00).
São geradas por `tests/fixtures/gerar_sinteticas.py`, que produz os mesmos bytes a
cada execução, e conferidas por `tests/test_cenarios.py`. O teste roda cada planilha
pelo mesmo caminho da tela e da planilha exportada (`app.pipeline.processar_excel`)
e compara com os valores abaixo. Nenhum valor é recalculado no teste.

Valores em R$. "Aberto" = compra − pago − retido, NF a NF. O saldo do Domínio é
credor (negativo na planilha). A conta fecha quando o total em aberto é igual a
|saldo final|.

Nas NFs quitadas, o teste confere compra, pago, retido, aberto e baixado.
Em todas elas, aberto e baixado são 0,00. Exceto o IRRF indicado no cenário 1,
o retido é zero e o pago é igual à compra.

## Golden sintético — `golden_sintetico.xls`

A razão de referência da suíte: 12 lançamentos, sem nada fora do padrão.

| NF | compra | pago | aberto |
|---|---:|---:|---:|
| 618204 | 4.700,00 | 1.880,00 (4 × 470,00) | 2.820,00 |
| 274591 | 2.400,03 | 959,94 (240,03 + 239,85 + 240,03 + 240,03) | 1.440,09 |

- **Prova:** pagamento parcial que cita a NF casa por número, inclusive a parcela que
  ficou 0,18 abaixo das outras. O saldo anterior (429,26) é pago por 2 × 214,63 de uma
  NF antiga (512309): o saldo zera ali, o trecho até esse ponto fica fechado por saldo
  zero e sai da tabela.
- **Esperado:** FECHA. Total em aberto 4.260,09 = |saldo final −4.260,09|; balde vazio;
  só os 5 self-checks OK.
- **Por quê:** 2.820,00 + 1.440,09 = 4.260,09. A planilha traz no fim a composição
  manual do contador, com o artefato de float de conta feita no Excel (1440.090000000001),
  e o fornecedor aparece como "SA" nas compras e "S.A." nos pagamentos.

## Cenário 1 — conciliado (`cenario_1_conciliado.xls`)

- **Prova:** o caso comum. Tudo casa por número; uma NF é quitada com retenção (IRRF).
- **Esperado:** FECHA. NF 791306: compra 4.316,80, pago 2.877,86 (2 × 1.438,93),
  aberto 1.438,94. NF 793018 quitada (2.912,99 pagos + 44,36 de IRRF = 2.957,35).
  Total 1.438,94 = |saldo final|; balde vazio.
- **Por quê:** o saldo anterior (1.873,46) é quitado pelo pagamento da NF 784512; só a
  791306 continua em aberto.

## Cenário 2 — centavo (`cenario_2_centavo.xls`)

- **Prova:** parcelas sem número da NF no histórico casam por valor, e uma diferença de
  centavo dentro da tolerância vira nota, não alerta.
- **Esperado:** FECHA. NF 802741: compra 2.853,47, pago 2.853,48 (3 × 951,16), aberto
  −0,01, com a nota "NF 802741: quitada com arredondamento de 0,01 (dentro da tolerância
  de centavos)". NF 805396: aberto 1.586,90. Total 1.586,89 = |saldo final|; sem alerta
  de juros.
- **Por quê:** 3 × 951,16 passa 0,01 da nota; a tolerância é de 1 centavo por parcela.
  1.586,90 − 0,01 = 1.586,89.

## Cenário 3 — sem par (`cenario_3_sem_par.xls`)

O exemplo do README (`exemplos/razao_exemplo_sem_par.xls` é cópia deste arquivo).

- **Prova:** um pagamento sem NF e sem valor de parcela não é encaixado à força: vai pro
  balde, e a conta fica INCOMPLETA com a diferença explicada ao centavo.
- **Esperado:** INCOMPLETO (self-check da composição), não ERRO. NF 889457: aberto
  3.419,65. NF 886120 quitada (compra e pago 5.827,40; 2 × 2.913,70).
  Balde: 1 item SEM_VINCULO, o boleto de
  1.264,38. Placar: composição 3.419,65 × Domínio 2.155,27.
- **Por quê:** 3.419,65 − 1.264,38 = 2.155,27. A diferença entre a tabela e o Domínio
  é exatamente o que está no balde, esperando alocação.

## Cenário 4 — estorno (`cenario_4_estorno.xls`)

- **Prova:** uma baixa de adiantamento lançada por engano e estornada depois se anula:
  o par sai da composição e do balde e vira alerta.
- **Esperado:** FECHA, com ALERTA `estorno_pareado`. NF 915270: compra 2.608,09, pago
  1.304,05, aberto 1.304,04. NF 912604 quitada (compra e pago 3.684,27).
  Total 1.304,04 = |saldo final|; balde vazio.
- **Por quê:** baixa e estorno têm o mesmo valor (1.947,52) e a mesma contrapartida, e o
  estorno é posterior e declara o que reverte. O motor só pareia o estorno de baixa de
  adiantamento contra a baixa que caiu no balde; um estorno genérico iria para o balde
  como estorno sem par.

## Cenário 5 — duplicidade (`cenario_5_duplicidade.xls`)

- **Prova:** a mesma NF lançada duas vezes é sinalizada, sem que o motor apague a cópia.
- **Esperado:** FECHA, com ALERTA `possivel_compra_repetida`. NF 931582: compra 4.327,88
  (2 × 2.163,94), pago 2.163,94, aberto 2.163,94. NF 934027 quitada
  (compra e pago 1.478,61). Total 2.163,94 =
  |saldo final|.
- **Por quê:** a composição mostra o que a razão diz (a NF com o dobro e metade em aberto),
  porque o saldo do Domínio também conta as duas compras; quem decide se a segunda é
  erro é quem confere.

## Cenário 6 — pago a maior (`cenario_6_pago_a_maior.xls`)

- **Prova:** um pagamento que cita duas NFs e passa da soma delas quita as duas, e a
  sobra vira uma linha própria da composição.
- **Esperado:** FECHA, com ALERTA `pago_a_maior`. NFs 947215 (1.837,26) e 947216 (966,43)
  quitadas; linha "(pago a maior lote 3133419)" com aberto −177,38; NF 952608: compra
  4.105,72, pago 2.052,86, aberto 2.052,86. Total 1.875,48 = |saldo final|.
- **Por quê:** 2.981,07 − (1.837,26 + 966,43) = 177,38, e 2.052,86 − 177,38 = 1.875,48.
  Só pagamento que cita duas ou mais NFs gera esse alerta; uma NF única paga acima do
  valor vira possível juros.

## Regras dos dados

- NFs, lotes e valores de um cenário não se repetem em outro (`conferir_unicidade` no
  gerador). Dentro do cenário, a repetição é o próprio caso testado.
- O saldo corrente nunca zera: zerar ativaria o corte por saldo zero, que não é o que
  estes exemplos mostram.
- Para mudar um cenário: edite o gerador, regere, rode `tests/test_cenarios.py` e
  atualize esta página com o novo esperado.
