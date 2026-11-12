# Preparar um alvo para receber o SSH do ambiente

"Alvo" é a VM ou o equipamento em que um script da rotina vai agir. O script roda no servidor do Airflow e abre o SSH até o alvo com a chave do ambiente (Connection `ssh_padrao`). Cada alvo precisa de duas coisas:

1. um **usuário de serviço** (`airflow-svc`) que aceita a chave pública do ambiente e tem o mínimo de privilégio;
2. a **chave do servidor** (impressão digital) cadastrada no `known_hosts` do ambiente. O ambiente nunca aceita host desconhecido (`StrictHostKeyChecking=yes`).

Pré-requisito: a chave do ambiente já foi gerada (`scripts_base/gerar_chave_ambiente.sh`, ver [instalacao.md](instalacao.md#7-chave-ssh-do-ambiente-e-connection-ssh_padrao)). A chave pública está em `ssh/id_ambiente.pub`, no diretório do projeto.

## VM Linux

No Debian mínimo, confira antes que o alvo tem `sudo` e o servidor SSH: `sudo apt-get install -y sudo openssh-server` (sem `sudo`, faça como root com `su -`).

No alvo, como administrador (substitua o conteúdo de `CHAVE_PUBLICA` pelo texto de `ssh/id_ambiente.pub`):

```bash
# 1. usuário de serviço sem senha (login só por chave)
sudo useradd -m -s /bin/bash airflow-svc
sudo passwd -l airflow-svc

# 2. instalar a chave pública do ambiente
sudo install -d -m 700 -o airflow-svc -g airflow-svc /home/airflow-svc/.ssh
echo 'CHAVE_PUBLICA' | sudo tee -a /home/airflow-svc/.ssh/authorized_keys
sudo chown airflow-svc:airflow-svc /home/airflow-svc/.ssh/authorized_keys
sudo chmod 600 /home/airflow-svc/.ssh/authorized_keys
```

O `cadastrar_alvo.sh` (abaixo) imprime a chave pública pronta para colar. Se preferir, copie o arquivo `ssh/id_ambiente.pub` para o alvo e use `cat`.

### `sudo` restrito

Dê ao usuário de serviço **só** os comandos de que as rotinas precisam, sem senha e com os argumentos fixos. Exemplo para a rotina `backup_etc_servidor_teste`, que roda `sudo -n tar czf - -C / etc`:

```bash
echo 'airflow-svc ALL=(root) NOPASSWD: /usr/bin/tar czf - -C / etc' | sudo tee /etc/sudoers.d/airflow-svc
sudo chmod 440 /etc/sudoers.d/airflow-svc
sudo visudo -cf /etc/sudoers.d/airflow-svc    # valida a sintaxe
```

Evite liberar `tar` sem argumentos fixos (`NOPASSWD: /usr/bin/tar`): o `tar` consegue executar comandos como root (`--checkpoint-action`), o que na prática entrega root ao usuário de serviço. Fixando os argumentos, só aquele comando é possível. Nunca use `ALL`, `NOPASSWD: ALL` nem acesso a shells.

Outro exemplo, para reiniciar um serviço (usado por `vm_reinicia_servico.py`): uma linha por serviço, com o nome exato.

```bash
echo 'airflow-svc ALL=(root) NOPASSWD: /usr/bin/systemctl restart cron' | sudo tee -a /etc/sudoers.d/airflow-svc
sudo visudo -cf /etc/sudoers.d/airflow-svc
sudo -u airflow-svc sudo -n /usr/bin/systemctl restart cron && echo OK   # liberado
sudo -u airflow-svc sudo -n /usr/bin/systemctl restart ssh              # deve ser negado
```

No script, chame sempre `sudo -n` (falha na hora em vez de esperar senha, que travaria a rotina até o tempo máximo).

(O servidor `ssh-teste` do profile `teste` usa uma regra mais aberta, `NOPASSWD: /bin/tar, /usr/bin/tar`, apenas por ser descartável. Não copie para produção.)

### Endurecer o SSH do alvo (recomendado)

Em `/etc/ssh/sshd_config.d/airflow.conf`:

```
Match User airflow-svc
    PasswordAuthentication no
    AllowAgentForwarding no
    AllowTcpForwarding no
    X11Forwarding no
```

e `sudo systemctl reload ssh`. Se o ambiente tiver IP fixo, restrinja a chave com `from="IP-DA-VM-AIRFLOW" ` no início da linha do `authorized_keys`.

## Equipamento de rede (switch, roteador, firewall)

1. Crie um **usuário local** só para o ambiente (`airflow-svc`) com o menor nível de privilégio que permita os comandos da rotina (por exemplo, nível de leitura/`show` para backup de configuração, nunca administrador completo).
2. Cadastre a chave pública `ssh/id_ambiente.pub` nesse usuário, no formato do fabricante (em muitos equipamentos: importar a chave pública para o usuário local). Se o equipamento só aceita senha, guarde a senha em uma Variable ou Connection do Airflow e use `segredos` na rotina; nunca no script.
3. Habilite SSH versão 2 e restrinja o acesso de gerência ao IP da VM do Airflow.
4. Cadastre a chave do equipamento no `known_hosts` (próxima seção).
5. No script Python, use o atalho do netmiko: `ssh_util.conectar_equipamento(host, "cisco_ios")` (veja [criar-rotinas.md](criar-rotinas.md#scripts-em-python-ssh_util)).

Os comandos e a sintaxe de usuários/chaves variam por fabricante: consulte o manual do equipamento.

## Cadastrar a chave do servidor: `cadastrar_alvo.sh`

Na VM do Airflow, na pasta do projeto:

```bash
scripts_base/cadastrar_alvo.sh HOST
```

O script:

1. obtém as chaves do servidor com `ssh-keyscan` (a porta 22);
2. mostra as **impressões digitais** (`SHA256:...`);
3. pergunta *"As impressões digitais conferem com as do servidor? (s/N)"*. Só grava no `ssh/known_hosts` se você responder `s`;
4. imprime a chave pública do ambiente a instalar em `~airflow-svc/.ssh/authorized_keys` no alvo.

**Confira a impressão digital em outro canal.** Antes de responder `s`, rode no próprio alvo (console da VM, por exemplo):

```bash
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

e compare com a mostrada pelo script. Se não conferir, responda `N`: pode haver algo no caminho entre o Airflow e o alvo.

Rodar de novo para um alvo já cadastrado não duplica a entrada. A opção `--sim` pula a pergunta (só para testes).

## Testar

O jeito mais simples é uma rotina de teste (a chave só existe durante a execução de uma rotina). Crie, pela tela "Rotinas" ([criar-rotinas.md](criar-rotinas.md)), uma rotina com o script abaixo, o argumento `HOST` do alvo, dispare-a com *Trigger* e leia o log:

```bash
#!/bin/bash
set -euo pipefail
source "$ROTINAS_LIB/ssh.sh"
echo "Testando SSH em $1..."
remoto "$1" hostname
echo "OK"
```

Erros comuns no log (scripts em bash / em Python):

| Mensagem | Causa |
|---|---|
| `Host key verification failed` / `not found in known_hosts` | Falta cadastrar o alvo com `cadastrar_alvo.sh` |
| `Permission denied (publickey)` / `Authentication failed` | A chave pública não está no `authorized_keys` do `airflow-svc`, ou as permissões de `~/.ssh` (700) e `authorized_keys` (600) estão erradas |
| `Connection timed out` / `timed out` | Rede ou firewall entre a VM do Airflow e o alvo (porta 22) |
| `Connection refused` | `sshd` parado ou não instalado no alvo |
| `sudo: a password is required` | Falta a linha `NOPASSWD` exata no sudoers do alvo |

**Não dá para testar com `ssh` direto de dentro do container**: a chave privada não existe em arquivo (fica na Connection `ssh_padrao` e só vira arquivo durante a execução de uma rotina), e o `ssh` comum não usa o `known_hosts` do ambiente. Use sempre a rotina de teste.

## Limitações conhecidas

- As funções de apoio (`ssh.sh` e `ssh_util.py`) usam **somente a porta 22**. O `cadastrar_alvo.sh` aceita uma porta (`cadastrar_alvo.sh HOST PORTA`, grava como `[HOST]:PORTA`), mas as bibliotecas ainda não se conectam a portas diferentes. Para alvos em outra porta, o script da rotina precisa chamar o `ssh` por conta própria, com as mesmas opções de segurança.
- Uma chave de servidor trocada (reinstalação do alvo, por exemplo) faz o SSH falhar de propósito com "Host key verification failed". Remova a linha antiga (`ssh-keygen -R HOST -f ssh/known_hosts`) e cadastre de novo, conferindo a impressão digital.
