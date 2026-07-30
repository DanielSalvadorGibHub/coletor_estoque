# Cadastro de Equipamentos — Estoque

Automatiza o cadastro de ONU, ONT e roteadores no HubSoft. O operador bipa a
etiqueta pelo celular; um computador no estoque confere e cadastra.

## Por que existe

O cadastro é manual: digitar serial, MAC e modelo de dezenas de aparelhos por
lote. Consome tempo e gera erro de digitação.

## Restrição que define tudo

**Não temos acesso à API do HubSoft.** Foi solicitado e negado. Por isso o
cadastro é feito por automação da interface web (Playwright), não por API.

Se a API for liberada algum dia, só o `hubsoft_estoque.py` muda — o resto da
corrente continua igual.

## Arquitetura

```
celular (coletor-estoque.html)
    |  POST  — um aparelho por vez
    v
Apps Script (apps_script_fila.gs)  -->  planilha "FILA_ESTOQUE", aba "fila"
    ^                                       |
    |  GET  — celular pergunta o status      |  worker lê as linhas PENDENTE
    |                                        v
    +---------------------------------  worker.py  (PC do estoque)
                                             |
                                             v
                                    hubsoft_estoque.py (Playwright)
                                             |
                                             v
                                          HubSoft
```

## Arquivos

| Arquivo | O que é |
|---|---|
| `coletor-estoque.html` | App do celular. Abre no navegador, não precisa instalar. Os 336 produtos do HubSoft estão embutidos nele. |
| `apps_script_fila.gs` | Cola no Apps Script da planilha e publica como App da Web. `doPost` recebe, `doGet` devolve status. |
| `worker.py` | Laço infinito no PC. Lê a fila, chama o adaptador, escreve o status de volta. |
| `hubsoft_estoque.py` | Adaptador Playwright. **Os seletores ainda são placeholders.** |
| `EQUIPAMENTOS_COMCADASTRO.xlsx` | Catálogo de origem: `id` = `id_produto` do HubSoft. |

## Planilha — colunas da aba `fila`

```
serial | mac | id_produto | produto | local | tipo | status | tentativas |
mensagem | recebido_em | processado_em | operador
```

Status: `PENDENTE` → `PROCESSANDO` → `OK` | `DUPLICADO` | `CONFLITO` | `ERRO` | `REVISAR`

## Fluxo no celular

O app é uma PWA publicada no GitHub Pages, instalável no Android e no iPhone.
Não existe mais leitura ao vivo: tudo parte de foto.

1. "Fotografar etiqueta" abre a câmera nativa do celular
2. Cada foto passa por: códigos de barras (todos de uma vez) + OCR do texto
3. Podem ser várias fotos do mesmo aparelho — as leituras se somam
4. Confere a ficha e envia
5. Tela de acompanhamento, atualizada a cada 2s
6. "Cadastrar outro equipamento"

### Sistema de evidências

Cada leitura vale pontos, e valores repetidos somam:

    código de barras ................ 100   exato
    texto ao lado de MAC/SN .......... 60   contexto forte
    texto solto na etiqueta .......... 40
    escolha ou digitação do operador  200   encerra a discussão

Verde = 100+ (código de barras ou duas leituras concordando).
Âmbar = uma leitura de texto só, precisa conferência.
Vermelho = dois valores com força parecida; o envio trava até o operador
desempatar tocando no correto.

### Análise da imagem

A foto é dividida em 14 faixas horizontais e só as **escuras são invertidas**.
Resolve a etiqueta Intelbras, que tem faixa preta com texto branco junto de área
clara com texto escuro — inverter a foto inteira consertava uma metade e
destruía a outra.

Imagem limitada a 1800px no lado maior: o Tesseract fica pior e muito mais lento
com imagem gigante, e foto de celular tem 12 megapixels ou mais.

### Identificador próprio

Terceiro código impresso na etiqueta de alguns equipamentos. **Obrigatório só na
Intelbras**; nas demais marcas o campo nem aparece e o cadastro segue sem ele.
Ainda não se sabe com que rótulo aparece na etiqueta, então o app mostra os
códigos lidos que não viraram MAC nem serial e o operador toca no certo.

## Decisões tomadas (não refazer sem motivo novo)

- **Código de barras, não foto do equipamento.** Serial exato em 1s contra OCR
  incerto que exigiria conferência manual depois — que é o trabalho a eliminar.
- **OCR só para o modelo.** O código de barras traz serial e MAC, mas quase nunca
  o modelo, que vem impresso como texto.
- **Modelo vindo do OCR fica âmbar, não verde.** Modelo errado vira estoque errado
  e ninguém percebe até o inventário não fechar.
- **Um aparelho por vez.** O operador descobre o erro com o aparelho na mão.
- **Worker no PC, não tudo no celular.** Quando o HubSoft mudar de layout, é um
  lugar para consertar em vez de N celulares para atualizar.
- **Consulta de MAC além da de serial.** Dois equipamentos com o mesmo MAC
  derrubam a autenticação dos dois na rede.
- **Em dúvida, exceção.** Nas consultas do adaptador, um "não existe" errado cria
  patrimônio duplicado; um erro só faz a linha esperar.

## Estado atual

Funciona: coletor, Apps Script, worker (fila, status, retentativa, registro local
anti-duplicata, intervalo adaptativo 2s/20s, identificação do operador).

**Pendente e bloqueante:** os seletores reais em `hubsoft_estoque.py`. Levantar com
o F12 nas telas de patrimônio do HubSoft. Preferir `[data-ng-model]` > `#id` >
texto visível. Evitar classe CSS e XPath posicional — a interface é AngularJS e
reordena entre versões.

Pendente e não bloqueante:
- Modo retorno para no status `REVISAR`; falta implementar a movimentação
- Modo lote (vários aparelhos antes de enviar) existiu na v2 e foi retirado

## Ambiente

Windows 10/11, Python 3.12. `pip install gspread google-auth playwright` e
`playwright install chromium`.

Primeira vez: `python worker.py --login` (loga na mão, a sessão fica em
`.perfil_chrome`). Depois: `python worker.py`.

Em produção, registrar como Tarefa Agendada — console aberto na mesa é fechado
por engano.

## Ordem para colocar no ar

1. Planilha com as 12 colunas, script colado, `SEGREDO` trocado, publicado
2. Um celular configurado; bipa um aparelho e confirma que nasce `PENDENTE`
   (com o worker **desligado**)
3. Seletores do adaptador
4. `python worker.py --login`, depois `python worker.py`
5. Segundo celular, com o outro nome de operador

## Contexto do time

Dois operadores hoje. Se der certo, mais gente vai querer. O worker é serial
(~4 cadastros/min); quando passar disso, rodar dois workers com perfis de Chrome
separados dividindo a fila — não vale complicar o código antes.

## Projeto irmão

`AUTOMATO_0807` — importa ordens de serviço do HubSoft para o Google Sheets e
audita anexos via Playwright. Mesma stack; a sessão autenticada e o padrão de
navegação valem para os dois.
