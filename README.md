# Ambiente de Rotinas Automatizadas (Apache Airflow) — 4º CTA

Ambiente de homologação em que o Apache Airflow é o **agendador e painel central** das rotinas de automação da infraestrutura. Cada rotina é um script que roda no horário, deixa log completo, aparece verde ou vermelho no painel e **avisa por e-mail quando falha ou deixa de rodar**.

- Rotinas criadas, editadas, ativadas/desativadas e excluídas **pela tela "Rotinas"** do Airflow (apenas Admin), sem escrever DAG nem saber Python.
- Todo script roda no próprio servidor do Airflow. Quando precisa agir em outra VM ou equipamento, o **script abre o SSH** usando as funções de apoio e a chave do ambiente.
- Histórico de versões das rotinas em um repositório Git próprio (diretório de dados) e log de auditoria.
- Uma rotina "vigia" confere a cada 15 minutos se tudo rodou e avisa de problemas (falha silenciosa é fracasso).

Airflow 3.1.8, Docker Compose, LocalExecutor (sem Celery e sem Redis), fuso America/Manaus.

## Arquitetura

```
VM (vCenter) ───────────────────────────────────────────────┐
│ Docker Compose (rede "rotinas", sub-rede DOCKER_SUBNET)    │
│  ├─ postgres             banco de metadados do Airflow     │
│  ├─ airflow-apiserver    interface + API + tela "Rotinas"  │
│  ├─ airflow-scheduler    LocalExecutor: roda os scripts    │
│  ├─ airflow-dag-processor  lê os YAMLs e gera os DAGs      │
│  └─ [profile teste] mailpit, ssh-teste                     │
│                                                            │
│ Volumes: dags/ plugins/ logs/ backups/ ssh/                │
│          dados (rotinas/ + scripts/, com Git próprio)      │
└───────────────┬────────────────────────────────────────────┘
                │ o script abre SSH (chave da Connection ssh_padrao)
                ▼
   VMs / equipamentos-alvo (usuário de serviço airflow-svc)
```

Fluxo: `rotinas/<nome>.yaml` + `scripts/...` → `dags/gerador_rotinas.py` cria um DAG por rotina → o scheduler executa no horário → falha esgotando as tentativas = e-mail. `dags/vigia_rotinas.py` confere tudo a cada 15 minutos.

## Documentação

| Documento | Para quê |
|---|---|
| [docs/instalacao.md](docs/instalacao.md) | Requisitos, instalação, primeiro login, SMTP, firewall, procedimento offline, proxy |
| [docs/preparar-alvo.md](docs/preparar-alvo.md) | Preparar uma VM Linux ou equipamento de rede para receber o SSH do ambiente |
| [docs/criar-rotinas.md](docs/criar-rotinas.md) | Criar rotinas pela tela e pelo YAML; como escrever os scripts |
| [docs/operacao.md](docs/operacao.md) | Dia a dia: painel, logs, avisos da vigia, backup/restauração, atualização, produção |
| [docs/homologacao.md](docs/homologacao.md) | Roteiro de homologação com os resultados obtidos |
| [docs/superpowers/specs/2026-11-10-airflow-rotinas-design.md](docs/superpowers/specs/2026-11-10-airflow-rotinas-design.md) | Especificação do projeto |

## Início rápido (homologação)

```bash
sudo mkdir -p /opt/airflow-rotinas && sudo chown "$USER": /opt/airflow-rotinas
./instalar.sh                 # cria o .env com segredos aleatórios e o diretório de dados
docker compose up -d --build  # sobe o ambiente (primeira vez demora: constrói a imagem)
scripts_base/gerar_chave_ambiente.sh   # gera a chave SSH do ambiente
```

Abra `http://IP-DA-VM:8080` e entre com o usuário e a senha mostrados ao final do `./instalar.sh`. Detalhes em [docs/instalacao.md](docs/instalacao.md).

## Rotinas de exemplo

| Rotina | O que faz |
|---|---|
| `backup_banco_airflow` | `pg_dump` do banco do Airflow, mantendo os 7 últimos |
| `verifica_servicos_http` | Confere se uma lista de URLs responde 200 |
| `backup_etc_servidor_teste` | Via SSH, compacta o `/etc` do servidor de teste e guarda os 7 últimos |
| `exemplo_falha_proposital` | Sempre falha, para demonstrar o alerta (instalada inativa) |

## Estrutura do repositório

```
docker-compose.yml  Dockerfile  .env.example  instalar.sh
dags/               gerador_rotinas.py, vigia_rotinas.py
plugins/            rotinas_core (regras) e rotinas_web (tela "Rotinas")
scripts_base/       gerar_chave_ambiente.sh, cadastrar_alvo.sh, instalar_exemplos.sh,
                    lib/ (ssh.sh, ssh_util.py), exemplos/
teste/ssh/          servidor SSH de teste (profile teste)
tests/              testes automatizados (pytest)
docs/               esta documentação
```

Os dados das rotinas (`rotinas/` e `scripts/`) ficam **fora** do repositório, em `DADOS_HOST_DIR` (padrão `/opt/airflow-rotinas/dados`), com Git próprio. O `.env`, as chaves e o `known_hosts` nunca vão para o Git do projeto.

## Testes

```bash
docker compose --profile teste run --rm testes pytest -v
```

Os testes que dependem do `ssh-teste`, do `mailpit` e do Airflow no ar usam o profile `teste`.

## O que fica fora deste projeto

Backup de VMs (Veeam/ExaGrid), alta disponibilidade, login LDAP/AD (passo futuro) e os scripts reais de backup e de criação de serviços do 4º CTA, que serão cadastrados depois neste ambiente.
