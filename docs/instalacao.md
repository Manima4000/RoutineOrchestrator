# Instalação

Este guia leva uma VM Ubuntu limpa até o painel funcionando com as rotinas de exemplo.

## 1. Requisitos

| Item | Valor |
|---|---|
| Sistema | Debian 12 (bookworm), usado nas VMs do 4º CTA, ou Ubuntu Server 24.04 LTS. Outras distribuições com Docker funcionam |
| Recursos (ponto de partida) | 4 vCPU, 8 GB de RAM, 50 GB de disco |
| Software | Docker Engine e plugin Docker Compose, `git`, `openssh-client` (o `ssh-keygen` e o `ssh-keyscan` são usados fora do container) |
| Rede | Acesso da VM às VMs/equipamentos-alvo (porta 22) e a um servidor SMTP; acesso à internet na instalação (ou use o [procedimento offline](#9-procedimento-offline)) |
| Usuário | Um usuário comum no grupo `docker` (não rode o ambiente como root) |

Os recursos acima são um ponto de partida; ajuste depois de medir o uso real.

## 2. Instalar o Docker

**O Debian mínimo pode vir sem `sudo`.** Teste com `sudo -V`. Se não existir, como root (`su -`): `apt-get install -y sudo && usermod -aG sudo SEU_USUARIO`, e entre de novo na sessão.

Pelo repositório oficial da Docker, **Debian 12**:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git openssh-client
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"     # sair e entrar de novo na sessão
docker compose version
```

**Ubuntu 24.04** (o repositório da Docker é outro: `linux/ubuntu`):

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"     # sair e entrar de novo na sessão
docker compose version
```

Se a VM acessa a internet por proxy, configure-o também para o serviço do Docker (ver [Proxy](#10-proxy-e-rede-docker)).

## 3. Obter o projeto e preparar o diretório de dados

```bash
git clone <url-do-repositorio> airflow-rotinas   # ou copie a pasta do projeto para a VM
cd airflow-rotinas
sudo mkdir -p /opt/airflow-rotinas
sudo chown "$USER": /opt/airflow-rotinas
```

O diretório de dados (`rotinas/` e `scripts/`, com Git próprio) fica **fora** do projeto, em `/opt/airflow-rotinas/dados` por padrão. Para usar outro local, mude `DADOS_HOST_DIR` no `.env` depois do passo seguinte e rode `./instalar.sh` de novo. Sem o `mkdir`/`chown` acima, o `./instalar.sh` termina com "Permission denied".

## 4. `./instalar.sh`

```bash
./instalar.sh
```

O script é idempotente (pode ser repetido). Ele:

- cria o `.env` a partir do `.env.example` (permissão 600) e preenche com valores aleatórios `POSTGRES_PASSWORD`, `AIRFLOW__CORE__FERNET_KEY`, `AIRFLOW__API_AUTH__JWT_SECRET`, `AIRFLOW__API__SECRET_KEY`, `ADMIN_SENHA` e `AIRFLOW_API_SENHA` (só os que ainda estão como `CHANGEME`);
- define `AIRFLOW_UID` com o seu UID;
- cria `logs/`, `backups/`, `ssh/` (com `ssh/known_hosts`), `dags/` e as pastas `rotinas/` e `scripts/` do diretório de dados, iniciando o Git dele;
- mostra o usuário e a senha do Admin e a **chave Fernet**;
- pergunta se deve instalar as rotinas de exemplo (responda `s`; depois, `scripts_base/instalar_exemplos.sh` faz o mesmo).

> **Guarde a chave Fernet e o `.env` fora da VM** (por exemplo, em um cofre de senhas da seção). Sem a chave Fernet, as Connections e Variables cifradas no banco não podem ser lidas. Veja também [operacao.md](operacao.md#backup-e-restauração).

Antes de subir, revise o `.env`:

| Variável | Para quê |
|---|---|
| `DOCKER_SUBNET` | Sub-rede da rede Docker (padrão `172.30.0.0/24`). Mude se colidir com faixas internas |
| `BUILD_HTTP_PROXY`, `BUILD_HTTPS_PROXY` | Proxy usado só na construção da imagem |
| `DADOS_HOST_DIR` | Diretório de dados no host |
| `ADMIN_USUARIO`, `ADMIN_EMAIL` | Admin inicial (senha gerada em `ADMIN_SENHA`) |
| `AIRFLOW_API_USUARIO`, `AIRFLOW_API_SENHA` | Conta de serviço (Admin) que a vigia e a tela "Rotinas" usam para falar com a API |
| `AIRFLOW_UI_URL` | URL base usada nos links dos e-mails. **Troque `http://localhost:8080` pelo endereço real do painel** |
| `SMTP_*`, `AVISO_DESTINATARIOS` | E-mail (seção 8) |

A conta de serviço (`svc_rotinas`, por padrão) é criada com papel Admin só para uso interno; não a use para entrar no painel.

## 5. Subir o ambiente

```bash
docker compose up -d --build
docker compose ps
```

A primeira vez demora (construção da imagem). O serviço `airflow-init` aplica as migrações, cria o Admin e a conta de serviço e cria a Connection `postgres_airflow` (usada pelo `backup_banco_airflow`); depois sobem o `airflow-apiserver`, o `airflow-scheduler` e o `airflow-dag-processor`. Espere o `airflow-apiserver` ficar `healthy`.

## 6. Primeiro login e usuários

Abra `http://IP-DA-VM:8080` e entre com `ADMIN_USUARIO` e `ADMIN_SENHA` (do `.env`). Dentro de um minuto as quatro rotinas de exemplo aparecem em **Dags**, e o menu **Rotinas** aparece na barra lateral (visível só para Admin).

Para criar outros usuários:

```bash
# Admin (gerencia rotinas, Connections e Variables)
docker compose exec airflow-apiserver airflow users create \
  --username maria --firstname Maria --lastname Silva --email maria@exemplo.mil.br --role Admin
# Viewer (só acompanha) ou User (acompanha e dispara)
docker compose exec airflow-apiserver airflow users create \
  --username joao --firstname Joao --lastname Souza --email joao@exemplo.mil.br --role Viewer
```

O comando pede a senha. Também é possível criar usuários na interface (menu Segurança > Usuários). Apenas o papel **Admin** enxerga e usa a tela "Rotinas".

## 7. Chave SSH do ambiente e Connection `ssh_padrao`

Os scripts que acessam outras máquinas usam a Connection `ssh_padrao`. O script abaixo gera o par de chaves (ed25519), grava a chave **privada** direto na Connection (cifrada pela Fernet; nunca fica em arquivo) e salva só a **pública** em `ssh/id_ambiente.pub`:

```bash
scripts_base/gerar_chave_ambiente.sh              # usuário padrão: airflow-svc
scripts_base/gerar_chave_ambiente.sh outro-usuario  # opcional: outro usuário de serviço
```

Rode com o ambiente no ar, na VM do Airflow. Se a Connection já existir, é substituída (a chave antiga deixa de valer; reinstale a nova pública nos alvos). A saída mostra a chave pública e o que fazer com ela: instalá-la em cada alvo, como descrito em [preparar-alvo.md](preparar-alvo.md). Para conferir: **Admin > Connections** deve listar `ssh_padrao` (tipo `ssh`, login `airflow-svc`).

## 8. E-mail (SMTP) e firewall

### SMTP

Edite no `.env`:

```
SMTP_HOST=smtp.exemplo.mil.br
SMTP_PORTA=587
SMTP_TLS=true            # true = STARTTLS
SMTP_USUARIO=            # vazio = sem autenticação
SMTP_SENHA=
SMTP_REMETENTE=airflow@exemplo.mil.br
AVISO_DESTINATARIOS=infra@exemplo.mil.br,outro@exemplo.mil.br
```

Cuidados que costumam derrubar o envio:

- **`SMTP_TLS` combina com a porta:** `true` (STARTTLS) para 587, `false` para 25. A porta **465** (SSL direto) **não é suportada**.
- **`SMTP_REMETENTE` igual ao `SMTP_USUARIO`** (ou um endereço que a conta pode usar). Remetente diferente costuma ser recusado (`Sender address rejected`).
- **`AVISO_DESTINATARIOS`** com caixas reais e monitoradas; o padrão `admin@localhost` não entrega a ninguém.
- **Rede:** a VM do Airflow precisa alcançar o servidor SMTP. Serviços externos (Gmail etc.) costumam ser bloqueados em rede interna e exigem "senha de app"; prefira o relay SMTP interno da organização.

Aplique com `docker compose up -d` (recria os containers com o novo `.env`).

**Testar o SMTP direto** (manda um e-mail de teste para `AVISO_DESTINATARIOS` com as mesmas variáveis do Airflow; não imprime a senha). O `-T` é obrigatório por causa do `<<'PY'`:

```bash
docker compose exec -T airflow-scheduler python - <<'PY'
import os, smtplib
from email.message import EmailMessage
e = os.environ
para = [x.strip() for x in e["AVISO_DESTINATARIOS"].split(",") if x.strip()]
print(f"{e['SMTP_HOST']}:{e['SMTP_PORTA']} tls={e['SMTP_TLS']} de={e['SMTP_REMETENTE']} para={para}")
m = EmailMessage(); m["Subject"] = "Teste SMTP Rotinas"; m["From"] = e["SMTP_REMETENTE"]; m["To"] = ", ".join(para)
m.set_content("Se você recebeu isto, o SMTP está funcionando.")
with smtplib.SMTP(e["SMTP_HOST"], int(e["SMTP_PORTA"]), timeout=30) as s:
    if e["SMTP_TLS"].lower() in ("1", "true", "sim", "yes"): s.starttls()
    if e.get("SMTP_USUARIO"): s.login(e["SMTP_USUARIO"], e.get("SMTP_SENHA", ""))
    s.send_message(m)
print("ENVIADO")
PY
```

| Erro | Causa |
|---|---|
| `Network is unreachable`, `timed out`, `Connection refused` | Rede/firewall até o servidor SMTP, ou host/porta errados |
| `SMTPAuthenticationError` | Usuário ou senha (ou o servidor exige senha de app) |
| `STARTTLS extension not supported` | `SMTP_TLS=true` numa porta sem STARTTLS |
| `Sender address rejected` | Remetente não permitido para a conta | Cada rotina pode ter e-mails extras próprios (campo `emails_aviso`). Teste ativando a rotina `exemplo_falha_proposital` e disparando-a (veja [instrucao.md](instrucao.md)). Na homologação com o profile `teste`, o Mailpit (`http://IP-DA-VM:8025`) captura os e-mails sem enviá-los de verdade (`SMTP_HOST=mailpit`, porta 1025: valores do `.env.example`).

### Firewall

Libere a porta do painel (8080) só para a rede de gestão. Atenção: o Docker publica portas direto no iptables e **ignora regras do `ufw`**. Use a cadeia `DOCKER-USER`; o comando abaixo é um exemplo, ajuste a interface (`-i`) e a rede de gestão (`-s`):

```bash
sudo iptables -I DOCKER-USER -i ens160 -p tcp --dport 8080 ! -s 10.0.0.0/24 -j DROP
```

(torne a regra persistente com `iptables-persistent` ou o mecanismo da VM). Em produção, publique o painel por proxy reverso com HTTPS (veja [operacao.md](operacao.md#recomendações-para-produção)). O profile `teste` também publica as portas 8025 e 1025 (Mailpit): não use esse profile em produção.

## 9. Procedimento offline

Para uma VM sem internet, construa e exporte as imagens numa máquina com internet e leve para a VM:

```bash
# máquina com internet, na pasta do projeto
docker compose build
docker save rotinas-airflow:local postgres:16 | gzip > rotinas-imagens.tar.gz
# levar rotinas-imagens.tar.gz e a pasta do projeto para a VM (pen drive, scp...)

# na VM
gunzip -c rotinas-imagens.tar.gz | docker load
./instalar.sh
docker compose up -d        # sem --build: usa as imagens carregadas
```

A construção da imagem precisa de acesso ao `apt` e ao PyPI/GitHub (constraints do Airflow); por isso ela é feita fora. Na homologação com o profile `teste`, inclua também `axllent/mailpit:latest` no `docker save` e construa a imagem `ssh-teste` (`docker compose --profile teste build`). Atualizações repetem o processo.

## 10. Proxy e rede Docker

- **Proxy no build:** preencha `BUILD_HTTP_PROXY` e `BUILD_HTTPS_PROXY` no `.env` (ex.: `http://proxy.exemplo.mil.br:3128`). Valem só para `docker compose build`; não vão para os containers.
- **Proxy para baixar imagens:** configure o serviço do Docker (`/etc/systemd/system/docker.service.d/proxy.conf` com `Environment="HTTP_PROXY=..."`, `Environment="HTTPS_PROXY=..."` e `NO_PROXY`), depois `sudo systemctl daemon-reload && sudo systemctl restart docker`.
- **Sub-rede:** `DOCKER_SUBNET` no `.env` (padrão `172.30.0.0/24`) define a rede `rotinas`. Se essa faixa já existe na rede da instituição, troque **antes** do primeiro `up` (para mudar depois: `docker compose down` e suba de novo).

## 11. Conferência final

```bash
docker compose ps                                   # tudo "healthy"/"Up"
curl -s http://localhost:8080/api/v2/monitor/health # banco, scheduler e dag-processor "healthy"
```

No painel, as quatro rotinas de exemplo aparecem em Dags; `exemplo_falha_proposital` vem inativa (pausada). Dispare `verifica_servicos_http` e `backup_banco_airflow` (botão *Trigger*) e confira que ficam verdes. `backup_etc_servidor_teste` só funciona depois de ter um alvo `ssh-teste` (profile `teste`) ou de ajustar a rotina para um alvo real; veja [preparar-alvo.md](preparar-alvo.md).

Ao criar uma rotina ativa, o Airflow executa **uma vez logo após a criação** (ele agenda o último intervalo previsto). Por isso as rotinas de exemplo rodam sozinhas na primeira vez; é normal.

### Ambiente de teste (profile `teste`)

Para treinar sem alvos reais, use `./instalar.sh --teste` (usa `./dados-dev` como diretório de dados, gera a chave `teste/ssh/chave_teste` e instala os exemplos sem perguntar) e suba com `docker compose --profile teste up -d --build`. Isso adiciona o Mailpit e o `ssh-teste` (servidor SSH com o usuário `airflow-svc`). Depois de `scripts_base/gerar_chave_ambiente.sh`, recrie o `ssh-teste` (`docker compose --profile teste up -d --force-recreate ssh-teste`) para ele aceitar a chave do ambiente. Falta cadastrar a chave do servidor no `known_hosts`. O nome `ssh-teste` só resolve dentro da rede do Docker, então o `cadastrar_alvo.sh` (que roda no host) não o encontra; faça o `ssh-keyscan` de dentro da rede e confira a impressão digital:

```bash
docker compose exec -T airflow-apiserver ssh-keyscan ssh-teste 2>/dev/null | cat >> ssh/known_hosts
ssh-keygen -lf ssh/known_hosts                                  # impressões digitais cadastradas
docker compose exec ssh-teste ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub   # a do servidor: devem ser iguais
```
