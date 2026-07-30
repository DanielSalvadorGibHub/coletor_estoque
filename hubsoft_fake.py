"""
Adaptador FALSO do HubSoft — só para testes.

Serve para validar a corrente inteira (celular -> Apps Script -> planilha ->
worker -> status de volta no celular) antes de os seletores do HubSoft estarem
prontos. Nada aqui abre navegador nem toca no sistema real.

Use com:  python worker.py --simular

Gatilhos: o que você bipa (ou digita) decide o desfecho, então dá para ver as
cinco telas do celular sem depender de sorte.

    serial contendo  DUP   -> DUPLICADO   (N/S já existe)
    serial contendo  INC   -> REVISAR     (criado sem N/S e MAC)
    serial contendo  ERR   -> ERRO        (falha 3x e desiste)
    serial contendo  LENTO -> OK, mas leva 25s (testa a espera do celular)
    MAC começando    FF:FF -> CONFLITO    (MAC em uso por outro patrimônio)
    qualquer outro         -> OK em ~3s

Exemplo para digitar no coletor, no botão "Digitar código":
    TESTE0001          -> deve cadastrar
    TESTEDUP01         -> deve dar "já estava cadastrado"
    TESTEERR01         -> deve dar erro depois de 3 tentativas
    TESTELENTO1        -> deve cadastrar, testando a barra de espera
    e para CONFLITO, digite o MAC  FF:FF:11:22:33:44  junto de um serial novo
"""

import random
import time


class SessaoExpirada(Exception):
    """Existe só para o worker poder importar o mesmo nome dos dois adaptadores."""


class HubsoftFake:
    def __init__(self, page=None, timeout=None):
        self.cadastrados = {}   # serial -> mac, simula o que já existe no sistema
        self.macs = {}          # mac -> serial

    def logado(self) -> bool:
        return True

    def ja_cadastrado(self, serial: str) -> bool:
        time.sleep(1.2)                     # imita o carregamento da tela
        if "DUP" in serial.upper():
            return True
        return serial in self.cadastrados

    def mac_em_uso(self, mac: str):
        if not mac:
            return None
        time.sleep(1.2)
        if mac.upper().startswith("FF:FF"):
            return "PAT-9999 (simulado)"
        return self.macs.get(mac)

    def serial_em_uso(self, serial: str) -> bool:
        time.sleep(0.8)
        return "DUP" in serial.upper() or serial in self.cadastrados

    def cadastrar(self, serial, mac, id_produto, produto, setor, tag, identificador="") -> str:
        s = serial.upper()

        if "ERR" in s:
            raise RuntimeError("falha simulada ao salvar (gatilho ERR no serial)")

        if "INC" in s:
            from hubsoft_estoque import CadastroIncompleto
            raise CadastroIncompleto("PAT-SIM-0001", "gatilho INC no serial")

        time.sleep(25 if "LENTO" in s else random.uniform(2.0, 3.5))

        self.cadastrados[serial] = mac
        if mac:
            self.macs[mac] = serial
        extra = f" · ident {identificador}" if identificador else ""
        return f"SIMULADO · {produto[:30]} · tag {tag}{extra}"
