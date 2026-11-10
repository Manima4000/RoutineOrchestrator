# Roteiro de homologação

Roteiro para validar o ambiente de ponta a ponta, com o resultado da execução feita em **10/11/2026**.

- **Ambiente:** Airflow 3.1.8, Docker Compose com o profile `teste` (Mailpit e servidor `ssh-teste`), na máquina de desenvolvimento; fuso America/Manaus; rotinas de exemplo instaladas em `./dados-dev`.
- **Execução:** todas as rotinas rodaram no Airflow real (scheduler em container). Os passos da tela "Rotinas" foram executados por **requisições HTTP autenticadas** (como Admin) contra o plugin, **não em navegador**; itens que dependem de navegador estão marcados na tabela e permanecem para conferência manual.
- **Legenda do resultado:** OK = executado e conferido; OK (HTTP) = conferido só por HTTP; PENDENTE = precisa de navegador.

## Preparação (roteiro)

1. `./instalar.sh --teste` e `docker compose --profile teste up -d --build`.
2. `scripts_base/gerar_chave_ambiente.sh` (gera a chave, grava a Connection `ssh_padrao` e `ssh/id_ambiente.pub`).
3. Recriar o `ssh-teste` para aceitar a chave e cadastrar a chave do servidor no `known_hosts` ([instalacao.md](instalacao.md#ambiente-de-teste-profile-teste)).
4. `scripts_base/instalar_exemplos.sh` (o `./instalar.sh --teste` já faz) e conferir as quatro rotinas no painel.

Resultado: OK. Reexecutar o `instalar_exemplos.sh` mostra "Já existe, mantida" e não cria commit novo. O serviço `airflow-init` cria a Connection `postgres_airflow` (idempotente). Impressão digital ED25519 do `ssh-teste` conferida com a do container antes de cadastrar.

## Checklist do roteiro (spec, seção 11)

| # | Passo | Resultado em 10/11/2026 |
|---|---|---|
| 1 | Subir o ambiente com o profile `teste` | OK. Serviços `postgres`, `airflow-apiserver`, `airflow-scheduler`, `airflow-dag-processor`, `mailpit`, `ssh-teste` no ar |
| 2 | Rotinas de exemplo executam | OK, ver tabela abaixo |
| 3 | Criar pela web uma rotina simples, com upload | OK (HTTP). `POST /rotinas-app/nova` com `ola.sh`: redirecionou (303) para a lista; criou `rotinas/homolog_web_simples.yaml` e `scripts/rotinas/homolog_web_simples/ola.sh`; o DAG apareceu em cerca de 30 s. Formulário no navegador: PENDENTE |
| 4 | Criar uma rotina com SSH | OK pelas rotinas de exemplo: `backup_etc_servidor_teste` usa `remoto`/`copiar_de` com a chave do ambiente (detalhes abaixo). Criar uma rotina com SSH pelo formulário no navegador: PENDENTE |
| 5 | Disparar manualmente; conferir log e status | OK. `homolog_web_simples` terminou em `success` e o log tem "Olá da rotina criada pela web" |
| 6 | Forçar falha: retentativa e e-mail no Mailpit | OK. `exemplo_falha_proposital`: log "Falha proposital para demonstração"; 1 retentativa após 1 min; e-mail `[Rotinas] FALHA: exemplo_falha_proposital` no Mailpit, **um por execução e só depois de esgotar as tentativas** |
| 7 | Quebrar um YAML e conferir o aviso da vigia | OK. YAML com agendamento inválido e script inexistente: o gerador criou o DAG `rotina_invalida__homolog_quebrada` (erro visível no painel; a lista "Import errors" do Airflow fica vazia por desenho). A vigia (disparada manualmente) enviou `[Rotinas] Vigia: 2 problema(s)` listando o arquivo com os dois motivos. A carência de 10 min da vigia vale só para DAG ausente, não para YAML inválido |
| 8 | Corrigir o YAML e ver o "resolvido" | OK. E-mail `[Rotinas] Vigia: 0 problema(s), 2 resolvido(s)` |
| 9 | Editar o horário | OK (HTTP). Diário 04:30 para semanal, segunda 07:15: YAML `15 7 * * 1`; o Airflow mostra "At 07:15, only on Monday". Pré-visualização das próximas execuções na tela: PENDENTE |
| 10 | Desativar | OK (HTTP). YAML com `ativa: false` e DAG pausado no Airflow |
| 11 | Excluir | OK (HTTP). YAML e script removidos; commits "Cria/Atualiza/Desativa/Exclui rotina homolog_web_simples" no Git dos dados; `auditoria.log` com as quatro ações (usuário `admin`) |
| 12 | Acesso sem login ao plugin | OK. `401` em `/rotinas-app/` |
| 13 | Divergência ativa/pausa (extra, não planejado) | OK. Ao despausar `exemplo_falha_proposital` (YAML `ativa: false`), a vigia avisou "inativa no YAML, mas ativa no Airflow" |
| 14 | Mensagens de validação ao lado dos campos, uso do menu "Rotinas" na interface (iframe) | PENDENTE (precisa de navegador) |
| 15 | Acesso negado a usuário não Admin (403) | Coberto pelos testes automatizados; não repetido nesta execução |

## Rotinas de exemplo (disparo manual)

| Rotina | Resultado | Evidência |
|---|---|---|
| `backup_banco_airflow` | Sucesso | Log: "Gerando backup de airflow em postgres..." e "Backup criado: .../airflow-db/airflow-2026...sql.gz (28K)"; arquivo em `backups/airflow-db/` |
| `verifica_servicos_http` | Sucesso | Log: `OK      http://airflow-apiserver:8080/api/v2/monitor/health` |
| `backup_etc_servidor_teste` | Sucesso (após cadastrar o host) | A primeira execução (automática, ao criar o DAG) falhou antes do cadastro: "No ED25519 host key is known for ssh-teste and you have requested strict checking. Host key verification failed." e "ERRO: tar remoto falhou (código 255)". A retentativa (`tentativas: 2`) teve sucesso depois do cadastro: "Backup criado: .../etc-ssh-teste/etc-ssh-teste-...tar.gz (132K)". Comprova a verificação estrita do host e a retentativa |
| `exemplo_falha_proposital` | Falha (esperado) | Ver item 6 |

## Achados da homologação

- **Execução automática ao criar:** ao criar um DAG ativo o Airflow executa uma vez o último intervalo agendado; por isso apareceram execuções `scheduled` logo depois da instalação, além do disparo manual. Documentado em [criar-rotinas.md](criar-rotinas.md).
- **Mascaramento de segredos:** quando host, usuário e banco ("postgres", "airflow") eram segredos, o log mascarava palavras comuns (`/opt/***/backups`). Por isso, no `backup_banco_airflow`, só `PGPASSWORD` é segredo; host, usuário e banco são argumentos.
- **Erro de YAML:** aparece como DAG `rotina_invalida__<arquivo>`, e não na lista de erros de importação do Airflow.
- **SSH só na porta 22** nas bibliotecas de apoio (limitação conhecida).
- **Observação de ambiente:** `docker compose exec -T ... > arquivo` perdeu a saída na máquina de desenvolvimento; use `| cat > arquivo`.

## Não coberto

- Uso do formulário e do menu no navegador (itens PENDENTE acima).
- Restauração completa do backup em VM nova ([operacao.md](operacao.md#restaurar-vm-nova-ou-perda-de-dados)) e atualização de versão do Airflow.
- Proxy reverso com HTTPS (exigência de `Host`/`Origin` descrita em [operacao.md](operacao.md#recomendações-para-produção)).
- Alvos reais (VMs de produção e equipamentos de rede).

## Estado final deixado

Quatro exemplos instalados em `dados-dev`; `exemplo_falha_proposital` inativa (`ativa: false`) e pausada; demais ativas; DAGs e YAMLs temporários removidos; Mailpit limpo.
