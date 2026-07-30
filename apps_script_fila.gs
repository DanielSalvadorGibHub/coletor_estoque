/**
 * Fila de cadastro de equipamentos — celular <-> planilha <-> worker
 *
 * doPost  : o celular envia UM aparelho (serial, mac, produto)
 * doGet   : o celular pergunta em que pé está o cadastro daquele serial
 *
 * Publicar: Implantar > Nova implantação > App da Web
 *   Executar como: Eu   |   Quem tem acesso: Qualquer pessoa
 *   (a cada alteração no código, publique uma NOVA VERSÃO — senão a URL
 *    continua servindo o código antigo)
 *
 * Cabeçalho da aba "fila" (linha 1):
 *   serial | mac | id_produto | produto | setor | tipo | status | tentativas | mensagem | recebido_em | processado_em | operador | tag | identificador
 */

const ABA = 'fila';
const SEGREDO = 'troque-esta-string';   // o coletor manda o mesmo valor

// O setor e sempre o mesmo, independente da tag. Fica aqui e nao no celular
// para nao existir a chance de alguem digitar diferente.
const SETOR = 'CORRECAO DE COMODATO';

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    if (body.segredo !== SEGREDO) return json({ok: false, erro: 'nao autorizado'});

    const it = body.item;
    if (!it || !it.serial) return json({ok: false, erro: 'serial ausente'});

    const aba = SpreadsheetApp.getActive().getSheetByName(ABA);
    const lock = LockService.getScriptLock();
    lock.waitLock(20000);

    try {
      const achado = procurar(aba, it.serial);
      if (achado) {
        // reenvio do mesmo aparelho: devolve o status atual em vez de duplicar
        return json({ok: true, repetido: true, status: achado.status, mensagem: achado.mensagem});
      }
      aba.appendRow([it.serial, it.mac || '', it.id_produto || '', it.produto || '',
                     SETOR, it.tipo || 'entrada', 'PENDENTE', 0, '', new Date(), '',
                     it.operador || '?', it.tag || '', it.identificador || '']);
      return json({ok: true, status: 'PENDENTE'});
    } finally {
      lock.releaseLock();
    }
  } catch (err) {
    return json({ok: false, erro: String(err)});
  }
}

function doGet(e) {
  try {
    const p = e.parameter;
    if (p.segredo !== SEGREDO) return json({ok: false, erro: 'nao autorizado'});
    if (!p.serial) return json({ok: false, erro: 'serial ausente'});

    const achado = procurar(SpreadsheetApp.getActive().getSheetByName(ABA), p.serial);
    return achado
      ? json({ok: true, status: achado.status, mensagem: achado.mensagem})
      : json({ok: true, status: 'AUSENTE', mensagem: 'nao esta na fila'});
  } catch (err) {
    return json({ok: false, erro: String(err)});
  }
}

/** Varre de baixo para cima: o item recem-enviado costuma estar no fim. */
function procurar(aba, serial) {
  const ult = aba.getLastRow();
  if (ult < 2) return null;
  const dados = aba.getRange(2, 1, ult - 1, 9).getValues();
  const alvo = String(serial).trim().toUpperCase();
  for (let i = dados.length - 1; i >= 0; i--) {
    if (String(dados[i][0]).trim().toUpperCase() === alvo) {
      return {linha: i + 2, status: String(dados[i][6] || ''), mensagem: String(dados[i][8] || '')};
    }
  }
  return null;
}

function json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
