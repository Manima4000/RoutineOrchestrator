#!/usr/bin/env python3
"""Reinicia um serviço systemd em uma VM e confirma que voltou a ficar "active".

Uso: vm_reinicia_servico.py HOST SERVICO

Exige sudo restrito no alvo, uma linha por serviço permitido, com argumentos fixos:
    airflow-svc ALL=(root) NOPASSWD: /usr/bin/systemctl restart cron
Sem essa linha, o `sudo -n` falha na hora (sem pedir senha) e a rotina fica vermelha.
A permissão de verdade é a do sudoers da VM; este script só valida o nome do serviço.
"""
import re
import sys
import time

from ssh_util import remoto

_HOST = re.compile(r"^[A-Za-z0-9._-]+$")
_SERVICO = re.compile(r"^[A-Za-z0-9@._-]{1,64}$")


def main() -> int:
    if len(sys.argv) != 3 or not _HOST.match(sys.argv[1]) or not _SERVICO.match(sys.argv[2]):
        print("Uso: vm_reinicia_servico.py HOST SERVICO", file=sys.stderr)
        return 2
    host, servico = sys.argv[1:]

    antes = remoto(host, f"systemctl is-active {servico}", verificar=False).saida.strip()
    print(f"{host}: {servico} estava '{antes}'")

    print(f"Reiniciando {servico}...")
    r = remoto(host, f"sudo -n /usr/bin/systemctl restart {servico}", verificar=False, timeout=120)
    if r.codigo != 0:
        print(f"ERRO ao reiniciar (código {r.codigo}): {r.erro.strip() or r.saida.strip()}", file=sys.stderr)
        print("Confira a linha NOPASSWD do sudoers para este serviço no alvo.", file=sys.stderr)
        return 1

    for _ in range(10):  # até ~10 s para o serviço subir
        depois = remoto(host, f"systemctl is-active {servico}", verificar=False).saida.strip()
        if depois == "active":
            print(f"{host}: {servico} está 'active'. OK")
            return 0
        time.sleep(1)
    print(f"ERRO: {servico} ficou '{depois}' depois do restart", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
