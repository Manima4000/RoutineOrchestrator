# Operação

Guia do dia a dia para quem administra o ambiente. Comandos `docker compose` são executados na pasta do projeto.

## Acompanhar o painel

- **Dags**: lista de todas as rotinas (tag `rotina`) e da vigia (`vigia_rotinas`, tag `sistema`). Verde = última execução com sucesso; vermelho = falhou.
- Clique no nome do DAG para ver o histórico de execuções; clique numa execução > tarefa `executar` > **Logs** para o log completo (também em `logs/` no host). **Não confunda com a aba "Audit Logs"**, que só registra ações de pessoas no painel (pausar, disparar) e costuma mostrar "No Event Found".
- **Tela Rotinas** (Admin): visão por rotina com horário, última execução com sucesso, próxima execução e divergências em relação ao YAML.
- DAGs chamados `rotina_invalida__<arquivo>` indicam um YAML com erro: abra a tarefa `erro` para ler o motivo, corrija o arquivo pela tela ou à mão e o DAG some no ciclo seguinte (você pode excluí-lo do painel depois, se quiser limpar o histórico).
- Estado do ambiente: `docker compose ps`, `docker compose logs -f airflow-scheduler` (ou `airflow-dag-processor`, `airflow-apiserver`).

## Disparar manualmente (*Trigger*)

Na página do DAG, botão **Trigger**. A execução manual segue as mesmas regras (tentativas, timeout, e-mail de falha). Qualquer usuário com papel User ou Admin pode disparar; Viewer só acompanha.

## Ativar, desativar, criar e excluir

Sempre pela tela **Rotinas** (ver [criar-rotinas.md](criar-rotinas.md)). Não use o botão de pausa nativo do Airflow: ele não altera o YAML e a vigia avisa de divergência. Uma rotina nova e ativa executa uma vez logo após ser criada.

## O que fazer com cada aviso da vigia

A vigia (`vigia_rotinas`) roda a cada 15 minutos e manda um e-mail `[Rotinas] Vigia: N problema(s), M resolvido(s)`. **Cada problema gera um único aviso** e, quando normaliza, entra na lista de "Resolvidos" do e-mail seguinte. (O estado fica na Variable `vigia_estado`.)

| Mensagem | Significado | O que fazer |
|---|---|---|
| `Arquivo X.yaml inválido: ...` | O YAML não passou na validação (campo errado, script inexistente, cron inválido...) | Corrigir pela tela (Editar) ou à mão. O motivo vem na mensagem |
| `Erro ao importar X: ...` | O Airflow não conseguiu carregar um arquivo de DAG | Ler a última linha do erro; em geral é problema no `dags/` ou nos plugins. Veja `docker compose logs airflow-dag-processor` |
| `DAG da rotina X não encontrado no Airflow.` | Existe o YAML, mas não o DAG | Dar tempo (a vigia espera **10 minutos** após criar ou editar antes de avisar). Persistindo: o dag-processor está parado ou com erro (`docker compose ps`, logs) |
| `Rotina X está ativa/inativa no YAML, mas pausada/ativa no Airflow.` | Alguém usou o botão nativo de pausa, ou editou o YAML à mão | Usar **Ativar/Desativar** na tela Rotinas para realinhar |
| `Rotina X atrasada: esperada às HH:MM de dd/mm/aaaa, última execução com sucesso: ...` | A rotina passou do horário previsto (mais tolerância) sem execução bem-sucedida | Ver o histórico do DAG: scheduler parado? execuções falhando? rotina presa? Corrigir e, se preciso, *Trigger*. A tolerância é `timeout + tentativas × intervalo + 5 min` |

Além disso, uma falha de execução gera o e-mail `[Rotinas] FALHA: <nome>` (após esgotar as tentativas). Se o e-mail não chega: confira `SMTP_*` e `AVISO_DESTINATARIOS` no `.env`, rode o [teste direto do SMTP](instalacao.md#smtp) e procure `Falha ao enviar o aviso` nos logs (`docker compose logs --tail 200 airflow-scheduler airflow-dag-processor | grep -i -E "aviso|smtp"`). Lembre que o e-mail só sai **depois da última tentativa**.

**A vigia não detecta Airflow ou VM fora do ar** (ela mesma depende do scheduler). Veja o monitoramento externo em [Recomendações para produção](#recomendações-para-produção).

## Histórico no Git dos dados

O diretório de dados (`DADOS_HOST_DIR`, padrão `/opt/airflow-rotinas/dados`) é um repositório Git. Cada criação, edição, ativação/desativação e exclusão feita pela tela vira um commit, tendo como autor o usuário do Airflow. Também existe `auditoria.log` (usuário, data/hora, ação, rotina), que fica fora do Git.

```bash
cd /opt/airflow-rotinas/dados
git log --oneline                          # tudo que mudou
git log -p -- rotinas/minha_rotina.yaml    # alterações de uma rotina
git show <commit>                          # detalhes de uma mudança

# voltar uma rotina a uma versão anterior (YAML e script)
git checkout <commit> -- rotinas/minha_rotina.yaml scripts/rotinas/minha_rotina
git commit -m "Volta minha_rotina para <commit>"

# recuperar uma rotina excluída (use o commit da exclusão e o pai dele: <commit>~1)
git checkout <commit>~1 -- rotinas/minha_rotina.yaml scripts/rotinas/minha_rotina
git commit -m "Recupera minha_rotina"
```

O DAG reaparece em cerca de 30 segundos. O histórico de execuções do Airflow não é afetado.

## Backup e restauração

### O que precisa de backup

| Item | Onde | Observação |
|---|---|---|
| **Chave Fernet** e `.env` | `.env` na pasta do projeto | **Sem a Fernet, Connections e Variables (inclusive a chave SSH `ssh_padrao`) ficam ilegíveis.** Guarde fora da VM, em local seguro |
| Banco de metadados | volume Docker `postgres-dados` | A rotina `backup_banco_airflow` faz `pg_dump` diário (1h) em `backups/airflow-db/`, mantendo os 7 últimos |
| Diretório de dados (rotinas, scripts, histórico Git) | `DADOS_HOST_DIR` | Copie a pasta inteira (inclui `.git`) |
| `ssh/` | `known_hosts` e `id_ambiente.pub` | A chave privada não está em arquivo: está na Connection (por isso o banco + Fernet) |
| `backups/` | pasta `backups/` | Os backups gerados pelas rotinas (banco, `/etc` dos alvos...) |

**Os backups precisam sair da VM** (outro servidor, fita, armazenamento do 4º CTA): a cópia em `backups/` na mesma VM não protege contra a perda da VM. Agende a cópia (por exemplo, uma rotina com `rsync` para outro servidor, usando SSH como nos exemplos).

Backup manual do banco, quando quiser:

```bash
docker compose exec -T postgres pg_dump -U airflow --no-owner airflow | gzip > airflow-$(date +%F).sql.gz
```

### Restaurar (VM nova ou perda de dados)

Este procedimento não foi exercitado na homologação; faça um ensaio num ambiente de teste antes de depender dele.

1. Instale o Docker e o projeto na VM nova ([instalacao.md](instalacao.md)), **mas não rode o `./instalar.sh`**: restaure o `.env` guardado (mesma Fernet, mesma senha do Postgres) e a pasta do projeto.
2. Restaure o diretório de dados em `DADOS_HOST_DIR` e a pasta `ssh/`.
3. Suba só o banco: `docker compose up -d postgres`.
4. Recrie o banco vazio e carregue o dump:
   ```bash
   docker compose exec -T postgres psql -U airflow -d postgres -c "DROP DATABASE IF EXISTS airflow" -c "CREATE DATABASE airflow"
   gunzip -c airflow-AAAA-MM-DD.sql.gz | docker compose exec -T postgres psql -U airflow -d airflow
   ```
5. Suba tudo: `docker compose up -d`. Entre no painel e confira rotinas, Connections (`ssh_padrao`, `postgres_airflow`) e Variables.

Sem a chave Fernet original, restaure o banco mesmo assim, mas recadastre as Connections e Variables e rode `scripts_base/gerar_chave_ambiente.sh` (a nova pública precisa ir para todos os alvos).

## Atualizar o Airflow

A versão é fixada: `ARG AIRFLOW_VERSION=3.1.8` no `Dockerfile` (aparece **duas vezes**, antes e depois do `FROM`). Para atualizar:

1. Faça backup (banco, `.env`, dados) e leia as notas de versão do Airflow.
2. Em ambiente de teste primeiro: troque a versão nas duas linhas do `Dockerfile`; confira se a constraint existe (`https://raw.githubusercontent.com/apache/airflow/constraints-<versão>/constraints-3.12.txt`).
3. `docker compose build` e `docker compose --profile teste run --rm testes pytest -v`. Os testes cobrem o plugin, que usa partes internas do Airflow (autenticação do usuário); mudanças de versão podem exigir ajuste.
4. Em produção: `docker compose up -d --build`. O serviço `airflow-init` roda `airflow db migrate` sozinho.
5. Confira o painel, a tela Rotinas e dispare uma rotina de exemplo.

Para voltar atrás, restaure o banco do backup e a versão anterior do `Dockerfile` (a migração do banco não é reversível).

## Rotinas de manutenção úteis

- Espaço em disco: `logs/` e `backups/` crescem. Acompanhe com `df -h` e mantenha retenção nos scripts de backup (como nos exemplos).
- Reconstruir após mudar o `Dockerfile`, o `requirements.txt` ou as listas de `ferramentas/` (`sistema.txt`, `python.txt`): `docker compose up -d --build`.
- Reiniciar um serviço: `docker compose restart airflow-scheduler`.
- Mudou o `.env`: `docker compose up -d` (recria o que for necessário).

## Recomendações para produção

Este projeto entrega o ambiente de **homologação**, promovível a produção sem reescrita. Antes de promover:

- **HTTPS por proxy reverso** (nginx, Apache, HAProxy) na frente da porta 8080, com certificado interno, e restrinja a porta 8080 ao proxy. Ajuste `AIRFLOW_UI_URL` no `.env` para a URL https (os links dos e-mails usam esse valor). **O proxy precisa preservar o cabeçalho `Host` e repassar o `Origin` do navegador** (`proxy_set_header Host $host;` no nginx). A tela Rotinas recusa todo `POST` (criar, editar, ativar, excluir) com erro 403 se a origem não bater com o endereço da requisição. Se mesmo assim as gravações derem 403 atrás do proxy, confira se o api-server enxerga o mesmo esquema/host que o navegador (cabeçalhos `X-Forwarded-*`); esse cenário não foi testado na homologação.
- **Monitoramento externo** do `GET /api/v2/monitor/health` (Zabbix ou similar), com alerta se não responder ou se `scheduler`/`dag_processor` não estiverem `healthy`: é o que cobre VM ou scheduler fora do ar.
- **Backup fora da VM** do banco, do `.env` (Fernet) e do diretório de dados, com teste periódico de restauração.
- **LDAP/AD** (passo futuro): hoje os usuários são locais. A integração usa o gerenciador de autenticação FAB; planeje a configuração com a equipe do diretório.
- **Firewall**: porta do painel só para a rede de gestão ([instalacao.md](instalacao.md#8-e-mail-smtp-e-firewall)); não use o profile `teste`.
- **SMTP real** e `AVISO_DESTINATARIOS` com uma caixa monitorada.
- **Limites conhecidos**: SSH das bibliotecas só na porta 22; segredos curtos são mascarados em todo o log (prefira segredos longos).
