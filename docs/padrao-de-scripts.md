# Padrão para escrever scripts das rotinas

Guia de uma página para quem escreve os scripts que o Airflow vai executar. Detalhes e exemplos completos: [criar-rotinas.md](criar-rotinas.md#guia-para-escrever-scripts).

## O contrato

O Airflow copia o script para uma pasta temporária, torna-o executável, roda e olha **só o código de saída**.

| O Airflow faz | O que isso exige do script |
|---|---|
| Roda o arquivo respeitando o `#!` | Primeira linha `#!/bin/bash` ou `#!/usr/bin/env python3`. Sem ela, a execução (e o upload pela tela) é recusada |
| Código de saída **0 = sucesso**, qualquer outro = falha | Falhou, saia com código diferente de 0 |
| Entrada padrão vazia, diretório atual temporário | Nada interativo (`read`, `sudo` com senha) e nada de caminho relativo ao local do script |
| Passa os `argumentos` como texto | Converta e valide; trate argumento faltando |
| Entrega os `segredos` como variáveis de ambiente | Leia do ambiente; senha nunca no script, no YAML nem nos argumentos |
| Encerra o processo ao passar de `timeout_min` | O script precisa terminar; use `timeout` nos comandos remotos |
| Roda no container como usuário `airflow` | Só vale o que a imagem tem: o básico (bash, python3 com paramiko e netmiko, ssh/scp, rsync, curl, psql, tar, git) mais o listado em `ferramentas/sistema.txt` e `ferramentas/python.txt` |
| Guarda só `BACKUPS_DIR` entre execuções | Grave arquivos de saída ali; o resto some quando o container é recriado. Na VM do Airflow, é a pasta `backups/` do projeto |

## Checklist antes de entregar um script

1. [ ] Começa com `#!`.
2. [ ] Bash: `set -euo pipefail` na segunda linha. Python: termina com `sys.exit(0)` ou `sys.exit(1)`, sem engolir exceção.
3. [ ] Sem senha, token ou chave dentro do arquivo. Segredos vêm de "Segredos" da rotina.
4. [ ] Valida os argumentos (host, caminhos) antes de usá-los em comandos remotos: rejeita espaços, `;`, `$`, `..`.
5. [ ] Imprime o que faz e em qual alvo; erros vão para `stderr` com a causa.
6. [ ] Pode rodar duas vezes seguidas sem dano (Trigger, nova tentativa e execução automática ao criar a rotina).
7. [ ] Limpa o que criou, inclusive na VM remota, mesmo quando falha (`trap` em bash, `finally` em Python).
8. [ ] Se gera arquivos, apaga os antigos (retenção).
9. [ ] Termina em tempo finito.
10. [ ] Arquivo com quebras de linha Unix (LF). A tela converte o CRLF no upload, mas arquivos copiados direto para a pasta, não.

## Acessar outras VMs

- Use as funções de apoio, que já usam a chave e o `known_hosts` do ambiente e sempre verificam a chave do servidor:
  - Python: `from ssh_util import remoto, enviar, receber`
  - Bash: `source "$ROTINAS_LIB/ssh.sh"` (funções `remoto`, `copiar_para`, `copiar_de`)
- Não monte `ssh` na mão: perde-se a verificação do host e a chave.
- Comando que precisa de root no alvo exige uma linha `NOPASSWD` no sudoers da VM, com argumentos fixos. Use `sudo -n`, para falhar na hora em vez de esperar senha. Ver [preparar-alvo.md](preparar-alvo.md).
- Valor vindo de fora **nunca** entra direto numa string de comando remoto sem validação. Em bash, prefira `remoto "$HOST" cmd "$arg1" "$arg2"` (vários argumentos, cada um protegido).

## Outras linguagens e programas compilados

- **No servidor do Airflow**, a rotina aceita só **scripts de texto com `#!`** (até 1 MB). Vale qualquer linguagem interpretada cujo interpretador esteja na imagem (bash, Python; outra, acrescente em `ferramentas/sistema.txt`). **Binários compilados (Rust, Go, C...) não são aceitos pela tela.** É de propósito: o script fica legível no Git dos dados (dá para revisar o que mudou) e roda com acesso à chave SSH e aos segredos.
- **Programa compilado que roda numa VM-alvo**: instale-o **na VM**, pelo processo de quem a administra, compilado para ela. A rotina usa um script curto que só chama o programa pelo SSH:

  ```bash
  #!/bin/bash
  set -euo pipefail
  source "${ROTINAS_LIB:?}/ssh.sh"
  remoto "${1:?Uso: script.sh HOST}" /opt/ferramenta/meu_programa --modo diario
  ```

  O código de saída do programa decide verde/vermelho e a saída dele vai para o log. Se ele precisar de root, libere o caminho exato no sudoers. Se precisar de senha, passe-a de um segredo por variável de ambiente, nunca como argumento (ficaria visível no `ps` da VM).

## Esqueletos

Python:

```python
#!/usr/bin/env python3
"""Descrição curta. Uso: meu_script.py HOST"""
import re
import sys

from ssh_util import remoto

def main() -> int:
    if len(sys.argv) != 2 or not re.match(r"^[A-Za-z0-9._-]+$", sys.argv[1]):
        print("Uso: meu_script.py HOST", file=sys.stderr)
        return 2
    host = sys.argv[1]
    print(f"Verificando {host}...")
    try:
        print(remoto(host, "uptime", timeout=30).saida)
    except Exception as erro:
        print(f"ERRO em {host}: {erro}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

Bash:

```bash
#!/bin/bash
set -euo pipefail
HOST="${1:?Uso: meu_script.sh HOST}"
[[ "$HOST" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "ERRO: host inválido: $HOST" >&2; exit 2; }
source "${ROTINAS_LIB:?}/ssh.sh"
echo "Verificando $HOST..."
remoto "$HOST" uptime
```

## O que costuma dar problema

| Sintoma | Causa provável |
|---|---|
| Rotina fica verde, mas o trabalho não foi feito | Faltou `set -e` (bash) ou o script engoliu o erro e saiu com 0 |
| Rotina trava até estourar o tempo | O script esperou entrada (senha, confirmação) |
| `command not found` / `ModuleNotFoundError` | A ferramenta não existe na imagem. Veja [Ferramentas na imagem](#ferramentas-na-imagem) |
| Arquivo gerado desapareceu | Foi gravado fora de `BACKUPS_DIR` |
| `bad interpreter` / `^M` | Quebras de linha do Windows (CRLF) |
| `host key` / `not found in known_hosts` | A VM não foi cadastrada com `scripts_base/cadastrar_alvo.sh` |
| `Permission denied` na VM | O usuário `airflow-svc` não lê o caminho, ou falta a linha do sudoers |
| Valor sumiu do log e apareceu `***` | É um segredo curto sendo mascarado; use segredos longos |

## Ferramentas na imagem

O script só enxerga os comandos e bibliotecas da imagem do Airflow. Para acrescentar um:

1. **Comando do sistema** (`ping`, `snmpwalk`, `mysql`...): acrescente o **pacote Debian** em `ferramentas/sistema.txt`. O nome do pacote nem sempre é o do comando (`dig` vem de `dnsutils`); procure em <https://packages.debian.org/> (bookworm).
   **Biblioteca Python** (`import pandas`): acrescente em `ferramentas/python.txt`.
2. Uma linha por item, com um comentário dizendo qual rotina precisa dele. Faça commit.
3. Na VM do Airflow: `git pull && docker compose up -d --build`. Leva alguns minutos; as rotinas voltam a rodar quando os containers sobem.
4. Confira: `docker compose exec airflow-scheduler which <comando>` ou `docker compose exec airflow-scheduler python -c "import <modulo>"`.

Se uma linha for inválida ou o pacote não existir, o build para mostrando o motivo, e o ambiente antigo continua rodando. Em VM sem internet, a imagem é construída fora e levada para a VM ([instalacao.md](instalacao.md#9-procedimento-offline)).

Antes de pedir uma ferramenta nova, confira se o comando não pode rodar **na VM-alvo** pelo SSH: aí ela precisa existir só lá, não na imagem.

## Exemplos prontos

Em `scripts_base/exemplos/scripts/`:

| Script | Mostra |
|---|---|
| `ping_dns_google.py` | Script simples, com plano B quando falta uma ferramenta |
| `ssh_diagnostico_vm.py` | Primeiro SSH: comandos em várias VMs, continua se uma falhar |
| `vm_saude.py` | Argumentos com opções (`--disco`, `--mem`), várias VMs, limites |
| `vm_relatorio_remoto.py` | Padrão enviar, executar e limpar. Modelo para rodar um script próprio nas VMs |
| `vm_reinicia_servico.py` | Comando com `sudo` restrito e verificação do resultado |
| `vm_backup_diretorio_cifrado.py` | Argumentos, **segredo** (`BACKUP_SENHA`), cifragem e retenção |
| `backup_banco_airflow.sh`, `backup_etc_servidor_teste.sh` | Modelos em bash |

Só as quatro rotinas de exemplo originais são instaladas por `scripts_base/instalar_exemplos.sh`. Para usar os demais, copie o arquivo para `scripts/exemplos/` do diretório de dados (ou envie pela tela).
