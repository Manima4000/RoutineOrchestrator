#!/usr/bin/env python3
"""Envia 2 pings ao 8.8.8.8 e sai com código 1 se algum falhar.

Usa o comando `ping` quando existe. A imagem do Airflow não traz o `ping`;
nesse caso testa a conectividade abrindo conexão TCP na porta 53 (DNS) duas vezes.
"""
import shutil
import socket
import subprocess
import sys
import time

ALVO = "8.8.8.8"
QUANTIDADE = 2
TIMEOUT_S = 5


def com_ping() -> bool:
    proc = subprocess.run(
        ["ping", "-c", str(QUANTIDADE), "-W", str(TIMEOUT_S), ALVO],
        capture_output=True, text=True, timeout=QUANTIDADE * (TIMEOUT_S + 2),
    )
    print(proc.stdout, end="")
    print(proc.stderr, end="", file=sys.stderr)
    return proc.returncode == 0


def com_tcp() -> bool:
    print(f"'ping' não encontrado; testando TCP {ALVO}:53 ({QUANTIDADE} vezes)")
    ok = True
    for i in range(1, QUANTIDADE + 1):
        inicio = time.monotonic()
        try:
            with socket.create_connection((ALVO, 53), timeout=TIMEOUT_S):
                print(f"{i}: resposta de {ALVO} em {(time.monotonic() - inicio) * 1000:.1f} ms")
        except OSError as erro:
            print(f"{i}: FALHOU ({erro})")
            ok = False
    return ok


def main() -> int:
    ok = com_ping() if shutil.which("ping") else com_tcp()
    print("OK" if ok else f"FALHA: {ALVO} não respondeu a todos os testes")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
