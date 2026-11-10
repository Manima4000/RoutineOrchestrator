#!/usr/bin/env python3
"""Verifica se cada URL recebida como argumento responde 200 em até 10 s.

Sai com código 1 listando as que falharam; código 0 se todas responderam.
"""
import sys
import urllib.error
import urllib.request

TIMEOUT_S = 10


def verificar(url: str) -> str | None:
    """Devolve None se OK, ou o motivo da falha."""
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as resp:
            return None if resp.status == 200 else f"status {resp.status}"
    except urllib.error.HTTPError as e:
        return f"status {e.code}"
    except Exception as e:  # DNS, recusada, timeout etc.
        return f"{type(e).__name__}: {getattr(e, 'reason', e)}"


def main(urls: list[str]) -> int:
    if not urls:
        print("ERRO: informe ao menos uma URL como argumento.", file=sys.stderr)
        return 2
    falhas = []
    for url in urls:
        motivo = verificar(url)
        if motivo is None:
            print(f"OK      {url}")
        else:
            print(f"FALHOU  {url} ({motivo})")
            falhas.append(url)
    if falhas:
        print(f"{len(falhas)} de {len(urls)} serviço(s) não responderam 200:")
        for url in falhas:
            print(f"  - {url}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
