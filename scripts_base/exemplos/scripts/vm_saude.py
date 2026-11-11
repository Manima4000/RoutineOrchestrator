#!/usr/bin/env python3
"""Confere a saúde de uma ou mais VMs por SSH e falha se algum limite for ultrapassado.

Uso: vm_saude.py [--disco 85] [--mem 90] [--carga 1.5] [--servicos ssh,cron] HOST [HOST ...]

  --disco     % máxima de uso do disco (/)                         (padrão 85)
  --mem       % máxima de memória em uso (sem cache)               (padrão 90)
  --carga     carga média de 5 min dividida pelo nº de CPUs        (padrão 1.5)
  --servicos  serviços systemd que precisam estar "active"         (padrão ssh,cron)

Não exige sudo no alvo. Sai com código 1 se qualquer VM estiver fora dos limites
ou inacessível (a rotina fica vermelha e avisa por e-mail).
"""
import argparse
import re
import sys

from ssh_util import remoto

_HOST = re.compile(r"^[A-Za-z0-9._-]+$")
_SERVICO = re.compile(r"^[A-Za-z0-9@._-]+$")

# Um único comando por VM (uma conexão SSH só); seções separadas por marcadores.
_COMANDO = (
    "export LC_ALL=C; echo '##DISCO'; df --output=pcent / | tail -n1; "
    "echo '##MEM'; free -m | awk '/^Mem:/ {print $2, $7}'; "
    "echo '##CARGA'; cut -d' ' -f2 /proc/loadavg; nproc; "
    "echo '##SERVICOS'; for s in {servicos}; do echo \"$s $(systemctl is-active $s 2>&1)\"; done"
)


def _secoes(saida: str) -> dict[str, list[str]]:
    secoes: dict[str, list[str]] = {}
    atual = ""
    for linha in saida.splitlines():
        if linha.startswith("##"):
            atual = linha[2:]
            secoes[atual] = []
        elif atual and linha.strip():
            secoes[atual].append(linha.strip())
    return secoes


def verificar(host: str, lim_disco: float, lim_mem: float, lim_carga: float, servicos: list[str]) -> list[str]:
    """Devolve a lista de problemas (vazia = tudo certo). Imprime as medições."""
    cmd = _COMANDO.replace("{servicos}", " ".join(servicos))
    s = _secoes(remoto(host, cmd, timeout=60).saida)
    problemas = []

    disco = float(s["DISCO"][0].rstrip("%"))
    total, disponivel = (float(x) for x in s["MEM"][0].split())
    mem = 100 * (total - disponivel) / total
    carga5, cpus = float(s["CARGA"][0]), int(s["CARGA"][1])
    carga = carga5 / cpus
    print(f"  disco {disco:.0f}% (limite {lim_disco:.0f}) | memória {mem:.0f}% (limite {lim_mem:.0f}) "
          f"| carga {carga:.2f}/CPU (limite {lim_carga})")

    if disco > lim_disco:
        problemas.append(f"disco em {disco:.0f}%")
    if mem > lim_mem:
        problemas.append(f"memória em {mem:.0f}%")
    if carga > lim_carga:
        problemas.append(f"carga {carga:.2f} por CPU")
    for linha in s["SERVICOS"]:
        nome, _, estado = linha.partition(" ")
        print(f"  serviço {nome}: {estado}")
        if estado != "active":
            problemas.append(f"serviço {nome} está '{estado}'")
    return problemas


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("hosts", nargs="+")
    ap.add_argument("--disco", type=float, default=85)
    ap.add_argument("--mem", type=float, default=90)
    ap.add_argument("--carga", type=float, default=1.5)
    ap.add_argument("--servicos", default="ssh,cron")
    a = ap.parse_args()

    servicos = [x for x in a.servicos.split(",") if x]
    if not all(_HOST.match(h) for h in a.hosts) or not all(_SERVICO.match(x) for x in servicos):
        print("ERRO: host ou nome de serviço com caracteres inválidos", file=sys.stderr)
        return 2

    falhas = {}
    for host in a.hosts:
        print(f"===== {host} =====")
        try:
            problemas = verificar(host, a.disco, a.mem, a.carga, servicos)
        except Exception as erro:  # sem conexão, saída inesperada...
            problemas = [f"não foi possível verificar: {erro}"]
        if problemas:
            falhas[host] = problemas
            print(f"  PROBLEMA: {'; '.join(problemas)}")
        else:
            print("  OK")

    print(f"\n{len(a.hosts) - len(falhas)} de {len(a.hosts)} VM(s) dentro dos limites")
    for host, problemas in falhas.items():
        print(f"ATENÇÃO {host}: {'; '.join(problemas)}", file=sys.stderr)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
