# Publicar o Coletor — 15 minutos, uma vez

O objetivo é ter um endereço `https://` de verdade. É isso que libera a câmera
no Android e no iPhone, e o que permite instalar o app na tela de início.

Enquanto o endereço for `file://`, `content://` ou um IP com certificado próprio,
a câmera vai continuar dando trabalho.

## 1. Conta no GitHub

<https://github.com/signup> — grátis, só e-mail e senha.

## 2. Criar o repositório

- Botão **+** no topo direito → **New repository**
- Nome: `coletor-estoque`
- Marque **Public** (o GitHub Pages grátis exige repositório público)
- **Create repository**

> Público significa que qualquer pessoa pode ver o código. O que está no
> coletor: a interface e a lista dos 336 nomes de produtos. O que **não** está:
> a URL do Apps Script e o segredo — eles ficam salvos em cada celular, não no
> arquivo. Ainda assim, use um segredo difícil de adivinhar.

## 3. Subir os arquivos

Na página do repositório: **Add file** → **Upload files**.

Arraste **estes sete**, todos juntos, sem pasta:

```
index.html
manifest.webmanifest
sw.js
icon-192.png
icon-512.png
icon-maskable.png
apple-touch-icon.png
```

Depois **Commit changes**.

## 4. Ligar o Pages

- **Settings** (no menu do repositório) → **Pages** (menu da esquerda)
- Em *Source*, escolha **Deploy from a branch**
- Branch: **main**, pasta: **/ (root)** → **Save**

Espere de 1 a 3 minutos. A própria página vai mostrar o endereço:

```
https://SEU-USUARIO.github.io/coletor-estoque/
```

## 5. Instalar no celular

Abra esse endereço no celular. Vai aparecer uma faixa convidando a instalar.

- **Android / Chrome** — toque em **Instalar**
- **iPhone / Safari** — toque em **Compartilhar** e depois em
  **Adicionar à Tela de Início**. No iPhone precisa ser o Safari; o Chrome do
  iOS não instala.

Aí é só abrir pelo ícone: tela cheia, sem barra de endereço, e a câmera pede
permissão normalmente.

## 6. Configurar cada aparelho

Toque na engrenagem e preencha:

- URL do Apps Script
- o segredo
- o nome de quem usa aquele celular

Fica salvo no aparelho. Uma vez por celular.

## Atualizar depois

Suba o `index.html` novo no repositório (**Add file** → **Upload files**,
mesmo nome, *Commit*). Os celulares pegam a versão nova no próximo acesso —
ninguém precisa reinstalar.

Se um aparelho parecer preso na versão antiga: feche o app e abra de novo.

## O que continua igual

O `worker.py` no PC não tem nada a ver com isso. Ele conversa com a planilha,
não com o celular. Publicar no GitHub Pages não muda uma linha dele.

E o `servir.py` deixa de ser necessário — era só uma ponte enquanto não havia
endereço de verdade.

## Se preferir não usar GitHub

Qualquer hospedagem com HTTPS serve: Cloudflare Pages, Netlify, Vercel. Todas
têm plano grátis e o processo é o mesmo — subir os sete arquivos numa pasta.
