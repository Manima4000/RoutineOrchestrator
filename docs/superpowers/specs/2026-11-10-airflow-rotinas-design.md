# Ambiente de Rotinas Automatizadas com Apache Airflow — 4º CTA

**Data:** 2026-11-10
**Responsável:** Ten Al M. Ferreira
**Status:** rascunho para aprovação

---

## 1. Contexto e motivação

Tema 2 do 4º CTA: *Implementação de protocolos de automação nos processos relativos à gestão da rede e do ambiente de hospedagem.*

Hoje já existem scripts de automação executados de forma agendada (diária, semanal etc.), mas **não existe um ambiente onde se possa verificar se cada execução deu certo ou falhou**. Falhas passam despercebidas. Os scripts também estão espalhados pelos servidores, sem versão única nem histórico.

O objetivo é montar um ambiente de homologação com o Apache Airflow que seja o **agendador e painel central** dessas rotinas: um lugar onde se cadastra a rotina, ela roda no horário, e qualquer pessoa autorizada vê o histórico, o log e o resultado (sucesso/falha) — e recebe aviso quando algo falha.

Objetivos formais do tema (passados pela chefia):

- montar ambiente de homologação para testes de rotinas automatizadas;
- implantar o serviço de gestão de workflows (Apache Airflow);
- criar e homologar scripts relacionados a backup de sistemas;
- criar e homologar scripts relacionados à criação de novos serviços;
- ministrar instrução do novo serviço e documentar o que foi implantado.

## 2. Objetivos, não-objetivos e anti-objetivos

### Objetivos (este projeto)

1. Airflow rodando em Docker dentro de uma VM no vCenter do 4º CTA.
2. Rotinas agendadas em que **todo script roda no próprio servidor do Airflow**. Quando o script precisa agir em outra VM ou equipamento, **o próprio script se conecta por SSH** (com a chave assimétrica que o ambiente fornece). O Airflow não faz SSH por conta própria.
3. **Criação, edição, ativação/desativação e exclusão de rotinas pela interface web do Airflow**, por meio de um plugin (menu "Rotinas"), incluindo upload do script. Restrito a administradores.
4. Painel com histórico, log completo de cada execução, status verde/vermelho, retentativa automática e **aviso de falha** — incluindo rotinas que deixaram de rodar.
5. Rotinas de exemplo, incluindo uma que acessa outra máquina por SSH e uma que falha de propósito para demonstrar o alerta.
6. Documentação de instalação, de uso ("como criar uma rotina") e de operação, mais um roteiro para a instrução.

### Não-objetivos (fora deste projeto)

- Backup de VMs / integração com Veeam / ExaGrid (discutido e descartado).
- Modo de execução remota gerenciado pelo Airflow (SSHOperator/SFTP): descartado; o SSH fica a cargo do script.
- Alta disponibilidade, CeleryExecutor, múltiplos workers, Kubernetes.
- Login via LDAP/AD (passo futuro documentado; homologação usa usuários locais).
- Editor de código no navegador: o script é enviado por upload; para alterar, envia-se nova versão.
- Execução avulsa de scripts fora de uma rotina cadastrada. Qualquer rotina cadastrada pode, porém, ser disparada manualmente pelo botão *Trigger*.
- Os scripts **reais** de backup de sistemas e de criação de novos serviços do 4º CTA: dependem de levantamento com a equipe e serão cadastrados depois, usando este ambiente. Este projeto entrega o ambiente e exemplos.

### Anti-objetivos (seria fracasso mesmo "funcionando")

- Uma rotina falhar ou deixar de rodar e ninguém ser avisado (falha silenciosa).
- Exigir que a pessoa saiba Python ou escreva DAG para adicionar uma rotina.
- Senhas ou chave privada SSH em texto puro dentro de scripts, no repositório ou em arquivo legível por qualquer um.
- Usuário de serviço com root irrestrito nos servidores de destino.
- Qualquer usuário do painel conseguir subir e executar scripts (apenas administradores).

## 3. Restrições e suposições

| Item | Decisão / suposição | Origem |
|---|---|---|
| Hospedagem | VM no vCenter (VMware) do 4º CTA, com alcance de rede às VMs/equipamentos-alvo | Decidido pelo usuário |
| Execução do Airflow | Docker Compose dentro da VM | Decidido pelo usuário |
| Execução das rotinas | Sempre local, no ambiente do Airflow; SSH feito pelo script | Decidido pelo usuário |
| Criação de rotinas | Pela interface web (plugin) | Decidido pelo usuário |
| Executor | LocalExecutor (sem Celery/Redis) | Minha decisão |
| Versão do Airflow | Última 3.x estável no momento da implementação, versão fixada (pinned) | Minha decisão |
| Homologação × produção | Este projeto entrega o ambiente de **homologação** (objetivo formal). Deve ser promovível a produção sem reescrita; endurecimento de produção (HTTPS, backup fora da VM, procedimento de atualização) fica como recomendação documentada | Minha decisão |
| SO da VM | **Suposição:** Ubuntu Server 24.04 LTS | A confirmar com a equipe |
| Internet na VM | **Suposição:** há acesso durante a instalação. Documentar procedimento offline (`docker save`/`docker load`) caso não haja | A confirmar |
| Proxy / rede Docker | Suporte a proxy HTTP via build args no Dockerfile. Sub-rede do Docker configurável no `.env` e fixada no compose, para não colidir com faixas internas | Minha decisão; faixas e proxy a confirmar |
| Envio de e-mail | **Suposição:** existe servidor SMTP interno; parâmetros via `.env`. Na homologação, um container **Mailpit** (profile `teste`) captura os e-mails | Minha decisão; SMTP a confirmar |
| Git interno | Não presumido. Sincronização com GitLab/Gitea fica para depois | A confirmar |
| Fuso horário | America/Manaus em agendamentos e na interface | Minha decisão |
| Idioma | Interface do plugin, documentação, campos do YAML e mensagens em português | Minha decisão |

## 4. Arquitetura

```
VM (vCenter) ──────────────────────────────────────────────┐
│ Docker Compose                                            │
│  ├─ postgres          (banco de metadados do Airflow)     │
│  ├─ airflow-apiserver (UI + API + plugin "Rotinas")       │
│  ├─ airflow-scheduler (LocalExecutor: roda os scripts)    │
│  ├─ airflow-dag-processor                                 │
│  └─ [profile teste] mailpit, servidor-ssh-teste           │
│                                                           │
│ Volumes: dags/ plugins/ logs/ + diretório de dados        │
│          (rotinas/, scripts/) + ssh/known_hosts           │
└───────────────┬───────────────────────────────────────────┘
                │ o script abre SSH (chave do ambiente)
                ▼
      VMs / equipamentos-alvo (usuário de serviço airflow-svc)
```

Os nomes exatos dos serviços seguem o que a versão 3.x escolhida exigir; o essencial é: sem Celery, sem Redis.

**Imagem própria** (`Dockerfile` baseado na imagem oficial), com as ferramentas que os scripts usam: `openssh-client`, `rsync`, `curl`, `postgresql-client`, `tar`, `gzip`, e em Python `paramiko` e `netmiko` (para scripts que falam com equipamentos de rede). Adicionar ferramentas = editar o Dockerfile e reconstruir.

### Estrutura

```
ORF/                          # repositório do projeto (código)
├── docker-compose.yml
├── Dockerfile
├── .env.example              # variáveis (sem segredos reais)
├── dags/
│   ├── gerador_rotinas.py    # lê rotinas/*.yaml e cria um DAG por rotina
│   └── vigia_rotinas.py      # detecta rotinas que não rodaram / com erro
├── plugins/rotinas/          # plugin da interface web "Rotinas"
├── scripts_base/
│   ├── lib/                  # bibliotecas de apoio para os scripts (SSH etc.)
│   └── exemplos/             # scripts de exemplo (copiados para os dados na instalação)
├── tests/
└── docs/

/opt/airflow-rotinas/dados/   # DADOS (fora do repositório do projeto; Git próprio)
├── rotinas/                  # um YAML por rotina
└── scripts/                  # scripts enviados pelo plugin
```

## 5. Definição de uma rotina (arquivo YAML)

Uma rotina = um arquivo `rotinas/<nome>.yaml`. É o formato único: o plugin web lê e grava esses arquivos, e quem preferir pode editá-los diretamente.

```yaml
nome: backup_etc_servidor_teste        # obrigatório; único; [a-z0-9_]; vira o dag_id
descricao: Compacta o /etc do servidor de teste
ativa: true                            # false = DAG pausado
agendamento: "0 2 * * *"               # cron, horário de Manaus
script: rotinas/backup_etc_servidor_teste/backup_etc.sh  # relativo a scripts/
argumentos: ["10.0.0.15", "7"]         # opcional; lista de strings
tentativas: 2                          # opcional; padrão 1 (= 1 nova tentativa após falha)
intervalo_tentativa_min: 5             # opcional; padrão 5
timeout_min: 60                        # opcional; padrão 60
avisar_falha: true                     # opcional; padrão true
emails_aviso: ["infra@exemplo.mil.br"] # opcional; padrão = destinatários globais do .env
segredos:                              # opcional; injetados como variáveis de ambiente
  DB_SENHA: { variavel: senha_banco_x }          # Variable do Airflow
  API_TOKEN: { conexao: api_x, campo: password } # campo de uma Connection
criado_por: admin                      # preenchido pelo plugin
atualizado_em: "2026-11-10T14:00:00-04:00"  # preenchido pelo plugin
```

### Regras de validação (aplicadas pelo plugin **e** pelo gerador)

- `nome` único, `^[a-z0-9_]{3,64}$`.
- `agendamento` cron válido (ou preset do Airflow como `@daily`).
- `script` deve existir em `scripts/` e não pode sair dessa pasta (bloquear `..` e caminhos absolutos).
- `segredos`: nomes de variável `^[A-Z_][A-Z0-9_]*$`; cada referência deve apontar para Variable/Connection existente (verificado no plugin; no gerador/execução, falha com mensagem clara).

Um YAML inválido **não pode sumir em silêncio**: o gerador registra o erro de forma que apareça no painel (erro de importação, com o nome do arquivo e o motivo) e a rotina vigia avisa (§7). Um YAML inválido não impede que os demais sejam carregados.

## 6. Execução das rotinas

### Gerador de DAGs (`dags/gerador_rotinas.py`)

- Lê todos os `rotinas/*.yaml` e cria **um DAG por rotina**, `dag_id = nome`.
- Cada DAG: `schedule = agendamento`, `catchup = False`, `max_active_runs = 1`, tags `["rotina"]`, `description = descricao`, pausado na criação se `ativa: false`.
- Uma única tarefa (`executar`) com `retries`, `retry_delay` e `execution_timeout` vindos do YAML.

### Como o script é executado

1. Copia o script para um diretório temporário exclusivo da execução e o torna executável.
2. Monta o ambiente do processo:
   - os `segredos` da rotina, como variáveis de ambiente (nunca na linha de comando);
   - `SSH_CHAVE` — caminho para um arquivo temporário (`chmod 600`) com a chave privada da Connection `ssh_padrao`, apagado ao final;
   - `SSH_KNOWN_HOSTS` — caminho para o `known_hosts` do ambiente;
   - `SSH_USUARIO` — usuário de serviço padrão (da Connection `ssh_padrao`);
   - `ROTINA_NOME`, `ROTINA_EXECUCAO` (id da execução) para uso em logs/nomes de arquivo.
3. Executa respeitando o shebang (bash, python etc.), com os argumentos, transmitindo stdout/stderr para o log da tarefa.
4. **Critério de sucesso:** código de saída 0. Qualquer outro código = falha. No timeout, o processo (e seus filhos) é encerrado e a tarefa falha.
5. Remove o diretório temporário e o arquivo da chave ao final (sucesso ou falha).
6. Valores de segredos são mascarados nos logs (mecanismo de máscara do Airflow).

### Bibliotecas de apoio para SSH (`scripts_base/lib/`)

Para que nenhum script precise reinventar a conexão nem afrouxar a segurança:

- **Bash** (`ssh.sh`, carregado com `source`): função `remoto HOST COMANDO...` e `copiar_para HOST ORIGEM DESTINO` / `copiar_de ...`, usando `SSH_CHAVE`, `SSH_USUARIO`, `SSH_KNOWN_HOSTS` e **sempre** `StrictHostKeyChecking=yes`, com timeout de conexão. Erros propagam código de saída.
- **Python** (`ssh_util.py`): equivalente com paramiko (comando remoto com código de saída, envio/recebimento de arquivo) e um atalho para netmiko (equipamentos de rede).
- As bibliotecas ficam acessíveis aos scripts num caminho fixo (ex.: `/opt/rotinas/lib`, exposto em `ROTINAS_LIB`) e no `PYTHONPATH`.

Scripts podem usar outro usuário/chave se precisarem (via `segredos`), mas o padrão documentado é a chave `ssh_padrao`.

### Aviso de falha

E-mail após esgotar as tentativas, com nome da rotina, horário, código de saída, últimas linhas do log e link para o log completo. O mecanismo de notificação fica isolado numa função para trocar/adicionar canal depois (Telegram, Rocket.Chat etc.).

## 7. Rotina "vigia" (falhas silenciosas)

"Falha silenciosa" inclui a rotina que **nem chega a rodar**. DAG `vigia_rotinas` (a cada 15 min) avisa quando:

- (a) existe erro de importação de algum YAML/DAG;
- (b) uma rotina ativa passou do horário previsto sem execução bem-sucedida (tolerância = timeout + tentativas × intervalo);
- (c) uma rotina com `ativa: true` está pausada no Airflow, ou vice-versa (divergência).

Cada problema gera **um** aviso até ser resolvido (sem repetir a cada 15 min) e um aviso de "resolvido" quando normalizar.

Scheduler ou VM fora do ar não podem ser detectados pelo próprio Airflow: fica documentada a recomendação de monitoramento externo do endpoint de saúde do Airflow (ex.: Zabbix, se existir). Não implementado aqui.

## 8. Plugin web "Rotinas"

Item de menu **"Rotinas"** na interface do Airflow, implementado como plugin do Airflow 3 (mecanismo da versão escolhida — ex.: app FastAPI + view integrada à UI). **Visível e utilizável apenas por usuários com papel Admin**; as rotas da API do plugin também exigem esse papel (não basta esconder o menu).

### Telas

- **Lista:** nome, descrição, horário em linguagem legível (ex.: "Diário às 02:00"), ativa/inativa, status e data da última execução, próxima execução (com link para o DAG). Ações: editar, ativar/desativar, excluir.
- **Nova / Editar rotina:** formulário com todos os campos do §5.
  - Horário: presets (diário; semanal com dia da semana; mensal com dia do mês — sempre com hora:minuto) **ou** campo cron avançado. Mostrar as próximas execuções previstas.
  - **Upload do script** (obrigatório ao criar; opcional ao editar — mantém o atual se nenhum for enviado). Opção de escolher um script já existente.
  - Segredos: lista de pares "nome da variável → Variable/Connection existente". O plugin nunca exibe valores.
  - Validação do §5 antes de salvar, com mensagens em português ao lado do campo.
- **Excluir:** pede confirmação; remove o YAML e o script (se nenhuma outra rotina o usa). O histórico de execuções permanece no Airflow e a versão anterior permanece no Git dos dados.

### Comportamento

- Salvar grava `rotinas/<nome>.yaml` e o script em `scripts/rotinas/<nome>/<arquivo>` de forma atômica (temporário + renomear). A rotina aparece no painel no próximo ciclo do dag-processor (configurar intervalo curto, ~30 s).
- Renomear não é permitido (o nome é o dag_id); para isso, cria-se outra.
- **Ativar/desativar — o YAML manda (minha decisão).** O plugin grava `ativa` no YAML **e** pausa/despausa o DAG pela API do Airflow. Divergências (alguém usou o botão nativo de pausa ou editou o YAML à mão) são apontadas pela vigia. A documentação orienta a ativar/desativar sempre pela tela "Rotinas".
- **Histórico de versões (minha decisão).** O diretório de dados é um repositório Git próprio: cada criação/edição/exclusão feita pelo plugin vira um commit, com o usuário do Airflow como autor e mensagem descritiva. Isso dá histórico, diff e retorno a versões anteriores (via linha de comando; tela de histórico desejável, mas opcional). Também há log de auditoria em arquivo (usuário, data/hora, ação, rotina).
- Upload: limite de tamanho (ex.: 1 MB) e apenas arquivos de texto.

## 9. Segurança

- **Chave SSH:** um par de chaves do ambiente; a privada fica na Connection `ssh_padrao` (criptografada pela chave Fernet), e só é materializada em arquivo temporário `600` durante a execução. Nunca no repositório.
- **Alvos:** usuário de serviço `airflow-svc`, login apenas por chave, `sudo` restrito aos comandos necessários. Documentar o passo a passo de preparação de uma VM (criar usuário, instalar chave pública, sudoers) e de um equipamento de rede (usuário local com privilégio mínimo).
- **known_hosts:** mantido no ambiente; verificação de host sempre ligada nas bibliotecas de apoio. Fornecer script auxiliar para cadastrar um alvo (`ssh-keyscan` + exibição da impressão digital para conferência manual).
- **Painel:** usuários locais com papéis do Airflow — `Admin` (gerencia rotinas, conexões e variáveis) e `Viewer`/`User` (acompanha e dispara). Porta do painel restrita à rede de gestão (documentar regra de firewall da VM). HTTPS via proxy reverso como recomendação documentada.
- **Segredos do ambiente:** `.env` fora do Git (há `.env.example`). Chave Fernet e senha do banco geradas na instalação.
- **Backup do próprio ambiente:** rotina de exemplo com `pg_dump` diário do banco de metadados; o diretório de dados (rotinas/scripts) e a chave Fernet entram no procedimento documentado de backup (sem a Fernet, Connections e Variables ficam ilegíveis).

## 10. Rotinas de exemplo (entregues)

| Nome | O que faz |
|---|---|
| `backup_banco_airflow` | `pg_dump` do banco do Airflow para um volume, mantendo os N últimos |
| `verifica_servicos_http` | Checa se uma lista de URLs responde 200; falha se alguma não responder |
| `backup_etc_servidor_teste` | Via SSH (biblioteca de apoio), compacta o `/etc` do servidor de teste, traz o arquivo para o volume de backups e mantém os N últimos |
| `exemplo_falha_proposital` | Sai com código 1, para demonstrar painel vermelho, retentativa e e-mail |

Para homologar sem depender de máquinas reais, o compose oferece no profile `teste` um **servidor SSH de teste** (container com `airflow-svc` e a chave pública configurada) e o **Mailpit**.

## 11. Testes e homologação

- **Testes automatizados** (pytest): validação de YAML (válidos e cada regra violada); geração de DAGs (parâmetros certos; YAML inválido não derruba os demais); execução (código ≠ 0 vira falha; timeout encerra o processo; segredos chegam como variáveis e não aparecem no log; temporários são apagados); plugin (validação, gravação atômica, commit no Git dos dados, bloqueio de `..`, acesso negado a não-Admin); vigia (cada condição a/b/c gera um único aviso).
- **Roteiro de homologação manual** (documento): subir o ambiente com profile `teste`; criar pela web uma rotina simples e uma com SSH; disparar manualmente; conferir log e status; forçar falha e conferir retentativa + e-mail no Mailpit; quebrar um YAML e conferir aviso da vigia; editar horário; desativar e excluir.

## 12. Documentação e instrução (entregues em `docs/`)

1. **Instalação:** requisitos da VM, preparação, `.env`, subida, criação do primeiro Admin, cadastro da Connection `ssh_padrao`, procedimento offline.
2. **Preparar um alvo** (VM Linux e equipamento de rede) para receber SSH do ambiente.
3. **Criar e gerenciar rotinas** (pela web e pelo YAML), com guia de escrita de scripts: sair com código ≠ 0 em erro (`set -euo pipefail` em bash), usar as bibliotecas de apoio para SSH, ler senhas de variáveis de ambiente (`segredos`), mensagens úteis no log, ser idempotente.
4. **Operação:** acompanhar o painel, ler logs, disparar manualmente, atualizar o Airflow, backup/restauração do ambiente.
5. **Roteiro da instrução:** sequência de demonstração usando as rotinas de exemplo.

## 13. Passos futuros (registrados, não implementados)

- Login via LDAP/AD.
- Sincronização do Git dos dados com Git interno (GitLab/Gitea).
- Outros canais de aviso (Telegram, Rocket.Chat, Zabbix).
- HTTPS com certificado interno; monitoramento externo da saúde do Airflow.
- Migração dos scripts reais hoje em cron para o Airflow, um a um.

## 14. Deixado a critério do implementador

- Versão exata 3.x do Airflow e o mecanismo de plugin correspondente.
- Tecnologia de front-end do plugin, desde que integrada ao menu do Airflow e em português.
- Layout das telas, nomes internos de módulos e funções.
- Bibliotecas de validação de cron e de YAML.
- Recursos mínimos da VM (documentar o que for medido; ponto de partida: 4 vCPU, 8 GB RAM, 50 GB disco).
