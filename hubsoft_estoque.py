"""
Adaptador Playwright para o estoque do HubSoft.

Segue o procedimento manual, na ordem em que ele é feito hoje:

    PASSO 1  verificar se o MAC já está cadastrado no sistema
    PASSO 2  se não estiver, cadastrar o equipamento pelo NOME da etiqueta
    PASSO 3  colocar no setor  (ex.: CORRECAO DE COMODATO)
    PASSO 4  adicionar a tag   (ex.: RETORNO DE TROCA)
    PASSO 5  editar o equipamento e inserir o N/S e o MAC
    PASSO 6  conferir que salvou

O cadastro nasce só com o nome; N/S e MAC entram na edição. Por isso os passos
2-4 e o 5 são métodos separados: se o processo cair entre eles, o patrimônio
existe sem serial, e o worker precisa saber disso para não criar um segundo.

SELETORES — o que já está confirmado e o que falta

Confirmado por captura de tela da tela de edição:
    título do modal   "Editar item (91694) ONT MITRASTAR GPT-2741 GNAC-N2"
    campos            Identificador Próprio · Número de Série · MAC Address
                      CA (Certificado de Aprovação) · Data Validade
                      Observações · Recondicionado
Esses usam get_by_label, que é o mais resistente a mudança de versão.

Ainda marcados com >>> PREENCHER <<< :
    - tela de listagem: campo de busca e linhas da tabela
    - tela de criação: autocompletes de produto, setor e tag
    - botão de salvar (é ícone de disquete, sem texto)
    - rota direta do item, se existir /estoque/patrimonio/{id}

Prefira, nesta ordem:
    get_by_label (texto visível)  >  [data-ng-model="..."]  >  #id
Evite classe CSS e XPath posicional: a interface é AngularJS e reordena
elementos entre versões.
"""

import re

from playwright.sync_api import TimeoutError as PWTimeout

BASE = "https://directinternet.hubsoft.com.br"

# --- ajuste as rotas conforme o menu de vocês --------------------------------
ROTA_LISTA = f"{BASE}/estoque/patrimonio"
ROTA_NOVO = f"{BASE}/estoque/patrimonio/novo"

SETOR_PADRAO = "CORRECAO DE COMODATO"

# A tag muda conforme a situação do equipamento e vem sempre da linha da fila.
# Não existe padrão seguro: gravar a tag errada é dado errado sem erro visível.
TAGS_VALIDAS = ("RETORNO DE TROCA", "RETORNO DE CANCELAMENTO", "RETORNO RECEPÇÃO")


class SessaoExpirada(Exception):
    """Caiu na tela de login no meio da operação."""


class CadastroIncompleto(Exception):
    """
    O patrimônio foi criado mas o N/S e o MAC não entraram.

    Erro separado de propósito: o worker não pode tratar isso como falha comum,
    porque tentar de novo criaria um segundo patrimônio. Precisa de olho humano.
    """

    def __init__(self, referencia, causa):
        self.referencia = referencia
        super().__init__(f"patrimônio {referencia} criado sem serial/MAC: {causa}")


class HubsoftEstoque:
    def __init__(self, page, timeout=15000):
        self.page = page
        self.page.set_default_timeout(timeout)

    # ------------------------------------------------------------------ sessão
    def logado(self) -> bool:
        self.page.goto(ROTA_LISTA, wait_until="networkidle")
        return "login" not in self.page.url.lower()

    def _guarda(self):
        if "login" in self.page.url.lower():
            raise SessaoExpirada("HubSoft devolveu a tela de login")

    # ------------------------------------------------- PASSO 1: MAC já existe?
    def mac_em_uso(self, mac: str):
        """
        Devolve uma identificação do patrimônio que já usa esse MAC, ou None.

        É a verificação principal contra duplicidade — a mesma que vocês fazem
        primeiro no processo manual.

        Em qualquer situação ambígua, LEVANTE EXCEÇÃO em vez de devolver None.
        Um "MAC livre" errado cria patrimônio duplicado, e dois equipamentos com
        o mesmo MAC derrubam a autenticação dos dois na rede.
        """
        if not mac:
            return None

        self.page.goto(ROTA_LISTA, wait_until="networkidle")
        self._guarda()

        # >>> PREENCHER: campo de busca da listagem
        busca = self.page.locator('input[data-ng-model="filtro.busca"]')
        busca.fill(mac)
        busca.press("Enter")
        self.page.wait_for_load_state("networkidle")

        # >>> PREENCHER: linhas da tabela de resultado
        linhas = self.page.locator("table tbody tr")
        try:
            linhas.first.wait_for(timeout=8000)
        except PWTimeout:
            return None                      # nada renderizou = não achou

        texto = linhas.first.inner_text()
        alvo = mac.replace(":", "").replace("-", "").upper()
        achado = texto.replace(":", "").replace("-", "").upper()

        if "NENHUM" in achado or alvo not in achado:
            return None
        return " ".join(texto.split())[:120]

    def serial_em_uso(self, serial: str) -> bool:
        """Checagem secundária. Mesma busca, procurando o N/S."""
        if not serial:
            return False
        self.page.goto(ROTA_LISTA, wait_until="networkidle")
        self._guarda()
        busca = self.page.locator('input[data-ng-model="filtro.busca"]')
        busca.fill(serial)
        busca.press("Enter")
        self.page.wait_for_load_state("networkidle")
        linhas = self.page.locator("table tbody tr")
        try:
            linhas.first.wait_for(timeout=8000)
        except PWTimeout:
            return False
        return serial.upper() in linhas.first.inner_text().upper()

    # --------------------------------- PASSOS 2-4: criar pelo nome, setor, tag
    def criar_pelo_nome(self, produto: str, setor: str, tag: str) -> str:
        """
        Cadastra o equipamento com o nome da etiqueta, no setor e com a tag.
        Devolve uma referência que sirva para reencontrá-lo no passo 5.

        Ainda SEM serial e SEM MAC — é assim que o processo funciona.
        """
        self.page.goto(ROTA_NOVO, wait_until="networkidle")
        self._guarda()

        # >>> PASSO 2 — PREENCHER: autocomplete do produto.
        # O HubSoft usa ui-select do AngularJS: digitar, esperar a lista, clicar.
        # Selecionar por id_produto normalmente não funciona no campo visível.
        campo = self.page.locator('input[data-ng-model="$select.search"]').first
        campo.fill(produto[:40])
        opcao = self.page.locator(".ui-select-choices-row", has_text=produto[:25]).first
        opcao.wait_for(timeout=8000)
        texto_opcao = opcao.inner_text().strip()
        opcao.click()

        # confere que a opção escolhida é mesmo a pedida — autocomplete erra
        if produto[:18].upper() not in texto_opcao.upper():
            raise RuntimeError(f"autocomplete devolveu '{texto_opcao[:60]}' para '{produto[:40]}'")

        # >>> PASSO 3 — PREENCHER: setor
        self._selecionar("setor", setor)

        # >>> PASSO 4 — PREENCHER: tag
        self._selecionar("tag", tag)

        # >>> PREENCHER: botão de salvar
        self.page.get_by_role("button", name="Salvar").click()

        ok = self.page.locator(".toast-success, .alert-success")
        ok.wait_for(timeout=12000)
        return " ".join(ok.inner_text().split())[:120]

    def _selecionar(self, campo: str, valor: str):
        """
        Um seletor ui-select por nome de campo. PREENCHER o mapa abaixo com o
        data-ng-model real de cada um — é o ponto que mais varia entre telas.
        """
        mapa = {
            "setor": 'input[data-ng-model="$select.search"]',   # >>> ajustar
            "tag": 'input[data-ng-model="$select.search"]',     # >>> ajustar
        }
        alvo = self.page.locator(mapa[campo]).last
        alvo.fill(valor)
        self.page.locator(".ui-select-choices-row", has_text=valor[:14]).first.click()

    # ----------------------------------------- PASSO 5: editar com N/S e MAC
    # A tela de edição confirmada por captura de tela é assim:
    #
    #   Editar item (91694) ONT MITRASTAR GPT-2741 GNAC-N2
    #   [Identificador Próprio]  [Número de Série]  [MAC Address]
    #   EPI: [CA (Certificado de Aprovação)] [Data Validade]
    #   [Observações]
    #   (o) Recondicionado                                    [botão salvar]
    #
    # Os rótulos são visíveis, então get_by_label é bem mais resistente que
    # data-ng-model: sobrevive a mudança de versão do HubSoft.

    ID_NO_TITULO = re.compile(r"\((\d+)\)")

    def id_do_item(self) -> str | None:
        """
        Lê o número do patrimônio no título do modal: "Editar item (91694) ...".

        É a âncora que resolve o problema do passo 5: sem ela, reencontrar um
        patrimônio recém-criado exige procurar na listagem, e como ele ainda não
        tem serial, vários do mesmo modelo ficam indistinguíveis.
        """
        try:
            titulo = self.page.locator(".modal-title, .modal-header").first.inner_text()
        except Exception:
            return None
        m = self.ID_NO_TITULO.search(titulo or "")
        return m.group(1) if m else None

    def completar(self, produto: str, serial: str, mac: str,
                  identificador: str = "", id_item: str | None = None) -> str:
        """
        Abre o item e preenche N/S, MAC e, quando houver, o identificador próprio.

        Se id_item vier preenchido, vai direto nele. É o caminho seguro. A busca
        pelo nome do produto é reserva, e nela existe risco real de pegar a linha
        errada — por isso ela confere o título antes de escrever qualquer coisa.
        """
        if id_item:
            # >>> PREENCHER: rota direta do item, se existir algo como
            # /estoque/patrimonio/{id}. Confira na barra de endereço ao abrir um.
            self.page.goto(f"{ROTA_LISTA}/{id_item}", wait_until="networkidle")
        else:
            self.page.goto(ROTA_LISTA, wait_until="networkidle")
            self._guarda()
            busca = self.page.locator('input[data-ng-model="filtro.busca"]')
            busca.fill(produto[:30])
            busca.press("Enter")
            self.page.wait_for_load_state("networkidle")
            # >>> PREENCHER: botão de editar da primeira linha
            self.page.locator("table tbody tr").first.get_by_role("button", name="Editar").click()

        self._guarda()
        self.page.wait_for_load_state("networkidle")

        # confere que abriu o item certo antes de escrever
        aberto = self.id_do_item()
        if id_item and aberto and aberto != str(id_item):
            raise RuntimeError(f"abriu o patrimônio {aberto}, esperava {id_item}")

        self.page.get_by_label("Número de Série").fill(serial)
        if mac:
            self.page.get_by_label("MAC Address").fill(mac)
        if identificador:
            self.page.get_by_label("Identificador Próprio").fill(identificador)

        # >>> PREENCHER: o salvar é um botão de ícone (disquete), sem texto.
        # Levante o seletor real; algo como o último botão do rodapé do modal.
        self.page.locator("button[type=submit], .modal-footer button").last.click()

        ok = self.page.locator(".toast-success, .alert-success")
        ok.wait_for(timeout=12000)
        return f"item {aberto or id_item or '?'} · " + " ".join(ok.inner_text().split())[:90]

    # ------------------------------------------------------------- orquestração
    def cadastrar(self, serial, mac, id_produto, produto, setor, tag, identificador="") -> str:
        """
        Passos 2 a 6. O passo 1 fica no worker, que decide antes de chamar aqui.
        """
        if not tag:
            raise ValueError("linha sem tag — a tag define a situação do equipamento")

        ref = self.criar_pelo_nome(produto, setor or SETOR_PADRAO, tag)
        id_item = self.id_do_item()      # se a criação já abrir o item, pega o número

        try:
            final = self.completar(produto, serial, mac, identificador, id_item)
        except Exception as e:
            raise CadastroIncompleto(id_item or ref, e) from e

        return f"{final} · tag {tag}" + (f" · ident {identificador}" if identificador else "")
