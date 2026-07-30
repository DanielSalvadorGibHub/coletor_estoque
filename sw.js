/*
 * Service worker do Coletor de Estoque.
 *
 * Três políticas diferentes, de propósito:
 *
 *   Apps Script      -> só rede, NUNCA cache. É a fila e o status do cadastro;
 *                       servir resposta velha aqui mostraria "cadastrado" para
 *                       um equipamento que ainda está na fila.
 *   o próprio app     -> rede primeiro, cache como reserva. Assim uma versão
 *                       nova publicada no GitHub chega no próximo acesso, em vez
 *                       de o aparelho ficar preso na antiga para sempre.
 *   bibliotecas e ícones -> cache primeiro. Não mudam e são o que faz o app
 *                       abrir no galpão sem sinal.
 */

const CACHE = "coletor-v1";

const ESSENCIAIS = [
  "./",
  "./index.html",
  "./manifest.webmanifest",
  "./icon-192.png",
  "./icon-512.png",
  "./apple-touch-icon.png",
];

self.addEventListener("install", e => {
  e.waitUntil(
    caches.open(CACHE)
      // addAll falha inteiro se um item falhar; item a item é mais tolerante
      .then(c => Promise.allSettled(ESSENCIAIS.map(u => c.add(u))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;                    // POST da fila passa direto

  const url = new URL(req.url);

  // fila e status: sempre rede
  if (url.hostname.endsWith("google.com") || url.hostname.endsWith("googleusercontent.com")) {
    return;
  }

  const ehApp = req.mode === "navigate" || url.pathname.endsWith("index.html");

  if (ehApp) {
    e.respondWith(
      fetch(req)
        .then(r => {
          caches.open(CACHE).then(c => c.put(req, r.clone()));
          return r;
        })
        .catch(() => caches.match(req).then(r => r || caches.match("./index.html")))
    );
    return;
  }

  // bibliotecas, ícones, o resto
  e.respondWith(
    caches.match(req).then(hit => hit || fetch(req).then(r => {
      if (r.ok && (url.origin === location.origin || url.protocol === "https:")) {
        caches.open(CACHE).then(c => c.put(req, r.clone()));
      }
      return r;
    }))
  );
});
