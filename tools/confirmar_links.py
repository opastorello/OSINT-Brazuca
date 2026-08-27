#!/usr/bin/env python3
"""Confirma em navegador real as URLs duvidosas do tools/checar_links.py.

Segunda passada, opcional: sites .gov.br devolvem 403 para robôs e alguns
404 são só bloqueio disfarçado. Este script abre cada URL no Camoufox
(Firefox com anti-detecção) e registra o status HTTP real, o título e a
URL final. Só as URLs marcadas como 'bloqueio' ou 'offline' na primeira
passada são visitadas, por padrão.

Requer o pacote camoufox, instalado à parte (não é dependência do projeto):
    pip install camoufox
    python3 -m camoufox fetch

Uso:
    python3 tools/checar_links.py --csv links.csv          primeira passada
    python3 tools/confirmar_links.py links.csv             confirma bloqueio e offline
    python3 tools/confirmar_links.py links.csv --situacoes offline --csv confirmados.csv
    python3 tools/confirmar_links.py --url https://exemplo.gov.br/consulta
"""

import argparse
import csv
import sys
import time
from collections import Counter

OK, BLOQUEIO, OFFLINE, ERRO = "ok", "bloqueio", "offline", "erro"
TIMEOUT_MS = 30000

# Títulos típicos de página de desafio anti-robô; o status pode até ser 200.
TITULOS_BLOQUEIO = ("just a moment", "attention required", "access denied", "acesso negado",
                    "human verification", "verificação humana", "cloudflare", "captcha", "403 forbidden")


def classifica(status, titulo, erro):
    if erro:
        return ERRO
    if status is None:
        return ERRO
    if any(t in (titulo or "").lower() for t in TITULOS_BLOQUEIO):
        return BLOQUEIO
    if status in (401, 403, 405, 429, 503):
        return BLOQUEIO
    if status >= 400:
        return OFFLINE
    return OK


def visita(page, url):
    inicio = time.monotonic()
    try:
        resposta = page.goto(url, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
        # Páginas de desafio (Cloudflare etc.) resolvem sozinhas em alguns segundos.
        page.wait_for_timeout(2500)
        status = resposta.status if resposta else None
        titulo = page.title().strip()
        if not titulo:
            # Desafios anti-robô costumam vir sem título; procura o texto no corpo.
            corpo = page.content()[:20000].lower()
            if any(t in corpo for t in TITULOS_BLOQUEIO):
                titulo = "(captcha ou desafio anti-robô no corpo da página)"
        return status, titulo, page.url, round(time.monotonic() - inicio, 1), ""
    except Exception as e:  # timeout, DNS, TLS, download em vez de página...
        msg = str(e).splitlines()[0][:100]
        return None, "", "", round(time.monotonic() - inicio, 1), msg


def carrega_urls(args):
    if args.url:
        return [(u, "", "") for u in args.url]
    situacoes = {s.strip() for s in args.situacoes.split(",")}
    with open(args.entrada, encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))
    return [(l["url"], l["situacao"], l["fontes"]) for l in linhas if l["situacao"] in situacoes]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("entrada", nargs="?", help="CSV gerado por tools/checar_links.py --csv")
    parser.add_argument("--url", action="append", help="URL avulsa (pode repetir); ignora o CSV")
    parser.add_argument("--situacoes", default="bloqueio,offline", help="situações do CSV a confirmar (padrão: bloqueio,offline)")
    parser.add_argument("--limite", type=int, help="visita só as N primeiras URLs")
    parser.add_argument("--csv", help="grava o resultado neste arquivo")
    parser.add_argument("--visivel", action="store_true", help="mostra a janela do navegador")
    args = parser.parse_args()
    if not args.url and not args.entrada:
        parser.error("informe o CSV de entrada ou --url")

    try:
        from camoufox.sync_api import Camoufox
    except ImportError:
        print("camoufox não instalado. Rode: pip install camoufox && python3 -m camoufox fetch", file=sys.stderr)
        return 2

    urls = carrega_urls(args)
    if args.limite:
        urls = urls[: args.limite]
    print(f"confirmando {len(urls)} URLs no navegador (sequencial, até {TIMEOUT_MS // 1000}s cada)...\n")

    resultados = []
    with Camoufox(headless=not args.visivel, i_know_what_im_doing=True) as navegador:
        page = navegador.new_page()
        page.set_default_timeout(TIMEOUT_MS)
        for i, (url, antes, fontes) in enumerate(urls, start=1):
            status, titulo, final, segundos, erro = visita(page, url)
            situacao = classifica(status, titulo, erro)
            resultados.append((situacao, antes, status or "", url, final, titulo, segundos, erro, fontes))
            marca = "  " if situacao == OK else "!!"
            print(f"{marca} [{i:3}/{len(urls)}] {antes or '-':8} -> {situacao:8} {status or '-':>4} {url[:70]}"
                  + (f"  '{titulo[:40]}'" if titulo else "") + (f"  ({erro})" if erro else ""))

    resumo = Counter(r[0] for r in resultados)
    print("\nresumo da confirmação")
    for chave in (OK, BLOQUEIO, OFFLINE, ERRO):
        print(f"  {chave:9} {resumo.get(chave, 0)}")
    print("\nok = abre no navegador; offline e erro aqui são candidatos fortes a link quebrado.")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["situacao", "situacao_anterior", "status", "url", "url_final", "titulo", "segundos", "erro", "fontes"])
            w.writerows(sorted(resultados))
        print(f"resultado gravado em {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
