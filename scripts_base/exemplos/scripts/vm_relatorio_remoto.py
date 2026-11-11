#!/usr/bin/env python3
"""Envia um script para a VM, executa lá e guarda o relatório no servidor do Airflow.

Uso: vm_relatorio_remoto.py HOST [HOST ...]

Padrão "enviar -> executar -> limpar": o script embutido em SCRIPT_REMOTO é copiado por SFTP
para a VM (diretório temporário), roda com o usuário de serviço (sem sudo) e é apagado no fim.
O relatório é salvo em $BACKUPS_DIR/relatorios-vm/<HOST>-<data>.txt (mantém os 10 últimos por VM).

Para rodar OUTRO script nas VMs, troque SCRIPT_REMOTO (bash) pelo conteúdo desejado.
"""
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from ssh_util import enviar, receber, remoto

MANTER = 10
_HOST = re.compile(r"^[A-Za-z0-9._-]+$")

SCRIPT_REMOTO = r"""#!/bin/bash
set -u
echo "# Relatório de $(hostname) em $(date '+%d/%m/%Y %H:%M:%S')"
echo
echo "## Sistema"
. /etc/os-release 2>/dev/null && echo "SO: $PRETTY_NAME"
echo "Kernel: $(uname -r)"
echo "Ligada há: $(uptime -p)"
echo
echo "## Atualizações pendentes"
n=$(apt list --upgradable 2>/dev/null | grep -c upgradable || true)
echo "$n pacote(s) com atualização disponível"
echo
echo "## Portas em escuta (TCP)"
ss -tln | awk 'NR>1 {print $4}' | sort -u
echo
echo "## Últimos acessos"
last -n 5 -w 2>/dev/null | head -n 5 || echo "(indisponível)"
echo
echo "## Disco"
df -h -x tmpfs -x devtmpfs
"""


def relatorio(host: str, destino: Path) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
        f.write(SCRIPT_REMOTO)
        local = f.name
    nome = f"rel-{os.getpid()}-{datetime.now():%H%M%S%f}.sh"
    remoto_path = f"/tmp/{nome}"
    saida_remota = f"/tmp/{nome}.txt"
    try:
        enviar(host, local, remoto_path)
        try:
            remoto(host, f"chmod 700 {remoto_path} && {remoto_path} > {saida_remota}", timeout=120)
            receber(host, saida_remota, destino)
        finally:
            remoto(host, f"rm -f {remoto_path} {saida_remota}", verificar=False)  # sempre limpa
    finally:
        os.unlink(local)


def main() -> int:
    hosts = sys.argv[1:]
    if not hosts or not all(_HOST.match(h) for h in hosts):
        print("Uso: vm_relatorio_remoto.py HOST [HOST ...]", file=sys.stderr)
        return 2
    pasta = Path(os.environ["BACKUPS_DIR"]) / "relatorios-vm"
    pasta.mkdir(parents=True, exist_ok=True)

    falhas = 0
    for host in hosts:
        print(f"===== {host} =====")
        destino = pasta / f"{host}-{datetime.now():%Y%m%d-%H%M%S}.txt"
        try:
            relatorio(host, destino)
        except Exception as erro:
            print(f"FALHOU em {host}: {erro}", file=sys.stderr)
            falhas += 1
            continue
        print(destino.read_text(), end="")
        print(f"Relatório salvo em {destino}")
        for velho in sorted(pasta.glob(f"{host}-*.txt"))[:-MANTER]:
            velho.unlink()
            print(f"Removido relatório antigo: {velho.name}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
