"""
Worker de cadastro de equipamentos — AUTOMATO 0807 / Estoque

Roda continuamente no PC do estoque:
    planilha-fila (Sheets)  ->  confere no HubSoft  ->  cadastra  ->  marca status

Instalar:
    pip install gspread google-auth playwright
    playwright install chromium

Primeira execução:
    python worker.py --simular    # testa a fila sem tocar no HubSoft
    python worker.py --login      # abre o Chrome, você loga no HubSoft na mão
    python worker.py              # a partir daí roda sozinho

Windows: registre como Tarefa Agendada ("ao iniciar o computador", reiniciar em
caso de falha). Console aberto na mesa é fechado por engano mais cedo ou mais tarde.
"""

import argparse
import logging
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

from hubsoft_estoque import (HubsoftEstoque, SessaoExpirada,
                             CadastroIncompleto, SETOR_PADRAO, TAGS_VALIDAS)

# --------------------------------------------------------------------- config
PLANILHA = "ARMAZEM EQUIPAMENTOS TROCA E RETIRADA"   # nome da planilha no Drive
ABA = "fila"
CREDENCIAIS = "credenciais.json"    # service account com acesso à planilha
PERFIL_CHROME = Path(".perfil_chrome")
LEDGER = Path("processados.db")
INTERVALO_ATIVO = 2                 # operador esperando na frente do celular
INTERVALO_OCIOSO = 20               # fila vazia: poupa cota do Sheets
CICLOS_ATE_OCIOSO = 15              # varreduras vazias antes de desacelerar
MAX_TENTATIVAS = 3
LOTE_MAX = 25                       # itens por ciclo, para o log não virar bloco

COL = {"serial": 1, "mac": 2, "id_produto": 3, "produto": 4, "setor": 5,
       "tipo": 6, "status": 7, "tentativas": 8, "mensagem": 9,
       "recebido_em": 10, "processado_em": 11, "operador": 12, "tag": 13, "identificador": 14}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%d/%m %H:%M:%S",
    handlers=[logging.FileHandler("worker.log", encoding="utf-8"),
              logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("estoque")


# ---------------------------------------------------------------- registro local
class Ledger:
    """
    Segunda barreira contra duplicata. A planilha pode ser editada à mão, a
    conexão pode cair depois do cadastro e antes de marcar OK — este arquivo
    local guarda o que ESTE worker realmente cadastrou.
    """

    def __init__(self, caminho: Path):
        self.db = sqlite3.connect(caminho)
        self.db.execute("""CREATE TABLE IF NOT EXISTS feitos(
            serial TEXT PRIMARY KEY, quando TEXT, retorno TEXT)""")
        self.db.commit()

    def ja_fiz(self, serial: str) -> bool:
        cur = self.db.execute("SELECT 1 FROM feitos WHERE serial=?", (serial,))
        return cur.fetchone() is not None

    def marcar(self, serial: str, retorno: str):
        self.db.execute("INSERT OR REPLACE INTO feitos VALUES (?,?,?)",
                        (serial, datetime.now().isoformat(timespec="seconds"), retorno))
        self.db.commit()


# ------------------------------------------------------------------------ fila
def abrir_aba():
    escopo = ["https://www.googleapis.com/auth/spreadsheets"]
    cred = Credentials.from_service_account_file(CREDENCIAIS, scopes=escopo)
    return gspread.authorize(cred).open(PLANILHA).worksheet(ABA)


def pendentes(aba):
    """Devolve (numero_da_linha, dict) das linhas PENDENTE."""
    dados = aba.get_all_values()
    saida = []
    for i, linha in enumerate(dados[1:], start=2):
        if len(linha) < COL["status"]:
            continue
        if linha[COL["status"] - 1].strip().upper() != "PENDENTE":
            continue
        saida.append((i, {
            "serial": linha[COL["serial"] - 1].strip(),
            "mac": linha[COL["mac"] - 1].strip(),
            "id_produto": linha[COL["id_produto"] - 1].strip(),
            "produto": linha[COL["produto"] - 1].strip(),
            "setor": linha[COL["setor"] - 1].strip(),
            "tipo": linha[COL["tipo"] - 1].strip() or "entrada",
            "tentativas": int(linha[COL["tentativas"] - 1] or 0),
            "operador": (linha[COL["operador"] - 1].strip()
                         if len(linha) >= COL["operador"] else "?"),
            "tag": (linha[COL["tag"] - 1].strip()
                    if len(linha) >= COL["tag"] else ""),
            "identificador": (linha[COL["identificador"] - 1].strip()
                              if len(linha) >= COL["identificador"] else ""),
        }))
        if len(saida) >= LOTE_MAX:
            break
    return saida


def escrever_status(aba, linha, status, mensagem="", tentativas=None):
    aba.update_cell(linha, COL["status"], status)
    aba.update_cell(linha, COL["mensagem"], mensagem[:250])
    aba.update_cell(linha, COL["processado_em"],
                    datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
    if tentativas is not None:
        aba.update_cell(linha, COL["tentativas"], tentativas)


# ------------------------------------------------------------------ processamento
def processar(item, hub: HubsoftEstoque, ledger: Ledger):
    """Devolve (status, mensagem). Não escreve na planilha — quem faz isso é o laço."""
    serial = item["serial"]

    if not serial:
        return "ERRO", "linha sem número de série"

    # A tag decide a situação do equipamento. Sem ela, ou com uma desconhecida,
    # é melhor parar do que gravar a classificação errada no patrimônio.
    if item["tag"] not in TAGS_VALIDAS:
        return "REVISAR", f"tag inválida ou ausente: {item['tag'] or '(vazia)'}"

    # Parte dos modelos Intelbras só é aceita pelo HubSoft com o identificador
    # próprio preenchido. Parar aqui evita descobrir isso no meio do cadastro,
    # com o patrimônio já criado pela metade.
    if "INTELBRAS" in item["produto"].upper() and not item["identificador"]:
        return "REVISAR", "Intelbras sem identificador próprio"

    if item["tipo"] in ("retorno", "troca", "retirada"):
        # Essas três não criam patrimônio: o item já existe e a operação é uma
        # movimentação. Ficam paradas até serem implementadas no adaptador.
        return "REVISAR", f"{item['tipo']} precisa de tratamento manual"

    if ledger.ja_fiz(serial):
        return "OK", "já cadastrado por este worker (registro local)"

    # PASSO 1 do procedimento: o MAC é a verificação principal
    dono = hub.mac_em_uso(item["mac"])
    if dono:
        return "CONFLITO", f"MAC {item['mac']} já está em: {dono}"

    if hub.serial_em_uso(serial):
        return "DUPLICADO", "N/S já existe no HubSoft"

    # PASSOS 2 a 6: cria pelo nome, põe setor e tag, depois edita com N/S e MAC
    try:
        retorno = hub.cadastrar(serial, item["mac"], item["id_produto"],
                                item["produto"],
                                item["setor"] or SETOR_PADRAO, item["tag"],
                                item["identificador"])
    except CadastroIncompleto as e:
        # Criado sem N/S e MAC. Repetir criaria um segundo patrimônio, então
        # para aqui: alguém precisa completar na mão e marcar a linha como OK.
        ledger.marcar(serial, f"INCOMPLETO {e.referencia}")
        return "REVISAR", (f"patrimônio criado SEM N/S e MAC — completar à mão. {e}")[:240]

    ledger.marcar(serial, retorno)
    return "OK", retorno


def ciclo(aba, hub, ledger):
    fila = pendentes(aba)
    if not fila:
        return 0

    log.info("%d item(ns) na fila", len(fila))
    for linha, item in fila:
        serial = item["serial"]
        escrever_status(aba, linha, "PROCESSANDO")
        try:
            status, msg = processar(item, hub, ledger)
            escrever_status(aba, linha, status, msg)
            nivel = log.info if status in ("OK", "DUPLICADO") else log.warning
            nivel("linha %-4d %-10s %-16s %-10s %s",
                  linha, status, serial, item["operador"][:10], msg)

        except SessaoExpirada:
            escrever_status(aba, linha, "PENDENTE", "sessão do HubSoft expirou")
            raise

        except Exception as e:
            t = item["tentativas"] + 1
            if t >= MAX_TENTATIVAS:
                escrever_status(aba, linha, "ERRO", f"falhou {t}x: {e}", t)
                log.error("linha %-4d ERRO      %-16s %s", linha, serial, e)
            else:
                escrever_status(aba, linha, "PENDENTE", f"tentativa {t}: {e}", t)
                log.warning("linha %-4d retry %d   %-16s %s", linha, t, serial, e)

    return len(fila)


# ------------------------------------------------------------------------ main
def rodar(apenas_login=False, simular=False):
    aba = abrir_aba()
    log.info("fila conectada: %s / %s", PLANILHA, ABA)

    if simular:
        # Testa a corrente toda sem abrir navegador e sem tocar no HubSoft.
        from hubsoft_fake import HubsoftFake
        log.warning("MODO SIMULACAO — nada sera cadastrado no HubSoft de verdade")
        laco(aba, HubsoftFake(), Ledger(LEDGER))
        return

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PERFIL_CHROME),
            headless=False,          # deixe visível: sessão AngularJS quebra menos
            viewport={"width": 1600, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        hub = HubsoftEstoque(page)
        ledger = Ledger(LEDGER)

        if apenas_login:
            page.goto("https://directinternet.hubsoft.com.br")
            input("Faça login no navegador que abriu, depois aperte ENTER aqui...")
            log.info("sessão salva em %s", PERFIL_CHROME)
            ctx.close()
            return

        if not hub.logado():
            log.error("sem sessão válida. Rode:  python worker.py --login")
            ctx.close()
            return

        try:
            laco(aba, hub, ledger)
        finally:
            ctx.close()


def laco(aba, hub, ledger):
    """O laço infinito. Igual nos dois modos — só o adaptador muda."""
    log.info("worker no ar — %ds com fila, %ds ocioso. Ctrl+C para parar.",
             INTERVALO_ATIVO, INTERVALO_OCIOSO)
    vazios = 0
    try:
        while True:
            try:
                n = ciclo(aba, hub, ledger)
                vazios = vazios + 1 if n == 0 else 0
                espera = INTERVALO_OCIOSO if vazios > CICLOS_ATE_OCIOSO else INTERVALO_ATIVO
            except SessaoExpirada:
                log.error("sessão expirou — refaça o login e reinicie")
                break
            except Exception as e:
                log.exception("falha no ciclo: %s", e)
                espera = INTERVALO_OCIOSO
            time.sleep(espera)
    except KeyboardInterrupt:
        log.info("encerrado pelo operador")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true", help="abre o navegador para login manual")
    ap.add_argument("--simular", action="store_true",
                    help="usa o adaptador falso: testa a fila sem tocar no HubSoft")
    a = ap.parse_args()
    rodar(apenas_login=a.login, simular=a.simular)
