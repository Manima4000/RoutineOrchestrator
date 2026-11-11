#!/usr/bin/env python3
"""Entra por SSH em uma ou mais VMs e roda comandos de diagnóstico (hostname, uptime, disco, memória).

Uso: ssh_diagnostico_vm.py HOST [HOST ...]      (ex.: ssh-teste)
Sai com código 1 se alguma VM não responder ou algum comando falhar.

Usa a chave e o known_hosts do ambiente (scripts_base/lib/ssh_util.py). O alvo precisa estar
preparado e cadastrado antes (docs/preparar-alvo.md e scripts_base/cadastrar_alvo.sh).
Para rodar OUTRO script nas VMs, troque a lista COMANDOS ou use enviar() + remoto().
"""
import sys

from ssh_util import remoto

COMANDOS = [
    "hostname",
    "uptime",
    "df -h /",
    "free -m",
]


def diagnosticar(host: str) -> bool:
    print(f"===== {host} =====")
    try:
        for comando in COMANDOS:
            print(f"$ {comando}")
            print(remoto(host, comando, timeout=30).saida.rstrip())
    except Exception as erro:  # conexão recusada, host desconhecido, comando com erro...
        print(f"FALHOU em {host}: {erro}", file=sys.stderr)
        return False
    return True


def main() -> int:
    hosts = sys.argv[1:]
    if not hosts:
        print("Uso: ssh_diagnostico_vm.py HOST [HOST ...]", file=sys.stderr)
        return 2
    resultados = [diagnosticar(h) for h in hosts]  # continua nas demais VMs mesmo se uma falhar
    falhas = resultados.count(False)
    print(f"\n{len(hosts) - falhas} de {len(hosts)} VM(s) OK")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
