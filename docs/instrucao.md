# Roteiro da instrução (cerca de 1h30)

Público: equipe de infraestrutura do 4º CTA (administradores Linux). Pré-requisitos do instrutor: ambiente de homologação no ar com o profile `teste` ([instalacao.md](instalacao.md)), as quatro rotinas de exemplo instaladas, `exemplo_falha_proposital` inativa, Mailpit aberto em `http://IP-DA-VM:8025` e o painel em `http://IP-DA-VM:8080`. Um usuário Admin para o instrutor e, se possível, um para cada aluno.

| Bloco | Tempo | Conteúdo |
|---|---|---|
| 1 | 10 min | Motivação |
| 2 | 10 min | Como o ambiente funciona |
| 3 | 25 min | Demonstração com as rotinas de exemplo |
| 4 | 30 min | Exercício guiado: criar uma rotina com SSH |
| 5 | 10 min | Ler um log de falha |
| 6 | 5 min | Dúvidas e próximos passos |

## 1. Motivação (10 min)

- Hoje: scripts em cron espalhados pelos servidores, sem versão única, sem histórico e **sem saber se deu certo**. Falhas passam despercebidas.
- Objetivo: um lugar central onde a rotina é cadastrada, roda no horário, deixa log e resultado (verde/vermelho) e **avisa quando falha ou deixa de rodar**.
- Princípios: ninguém precisa saber Python para cadastrar uma rotina; segredos nunca em texto no script; o SSH usa chave do ambiente, com verificação do servidor; só Admin cadastra rotinas.

## 2. Como funciona (10 min)

Mostre o diagrama do [README](../README.md): script roda **no servidor do Airflow**; quando precisa agir em outra máquina, o **próprio script** abre o SSH. Conceitos:

- Rotina = YAML + script ([criar-rotinas.md](criar-rotinas.md)); um DAG por rotina.
- Tentativas, tempo máximo, e-mail de falha.
- A vigia (a cada 15 minutos) pega o que não aparece como falha: rotina que não rodou, YAML quebrado, divergência de pausa.
- Git dos dados: tudo que a tela muda vira commit.

## 3. Demonstração com as rotinas de exemplo (25 min)

Roteiro sugerido, no painel:

1. **Visão geral (3 min).** Abra **Dags** e mostre as quatro rotinas e a `vigia_rotinas`. Abra o menu **Rotinas**: colunas, selos Ativa/Inativa, próxima execução.
2. **`verifica_servicos_http` (5 min).** Abra o DAG, dispare com **Trigger**, acompanhe a tarefa `executar` e abra os **Logs**: linhas `OK  http://...`. Mostre os argumentos (a URL) na tela Editar.
3. **`backup_banco_airflow` (5 min).** *Trigger*; no log, "Backup criado: ... (28K)". Mostre o arquivo em `backups/airflow-db/` na VM. Na tela Editar, mostre o bloco **Segredos** (`PGPASSWORD ← Connection postgres_airflow, campo password`) e explique que o valor nunca aparece, nem no log (`***`).
4. **`backup_etc_servidor_teste` (5 min).** *Trigger*; o log mostra "Compactando /etc em ssh-teste...", "Copiando..." e "Backup criado". Explique as peças: `source "$ROTINAS_LIB/ssh.sh"`, `remoto`, `copiar_de`, Connection `ssh_padrao`, `known_hosts`. Se quiser, demonstre a segurança: cadastre um alvo novo sem conferir e mostre que o SSH recusa "Host key verification failed".
5. **`exemplo_falha_proposital` (7 min).** Pela tela Rotinas, clique em **Ativar** (a rotina é instalada inativa) e dispare com **Trigger** (ao ativar, o Airflow também pode rodá-la sozinho uma vez). Mostre: tarefa vermelha, retentativa após 1 minuto, e o e-mail `[Rotinas] FALHA: exemplo_falha_proposital` chegando ao Mailpit (com as últimas linhas do log e o link). Depois clique em **Desativar**.

Pontos para repetir: *Trigger* não depende do horário; ativar/desativar só pela tela; **uma rotina nova e ativa roda uma vez ao ser criada**.

## 4. Exercício guiado: criar uma rotina com SSH (30 min)

Objetivo: cada aluno cria a rotina `ola_ssh_<seunome>` que entra no `ssh-teste` e mostra o nome da máquina e a data.

**Preparação (instrutor, antes da aula):** conferir que o `ssh-teste` está cadastrado no `known_hosts` e aceita a chave do ambiente (basta o `backup_etc_servidor_teste` ter dado sucesso).

**Passo 1 (5 min) — o script.** Cada aluno cria o arquivo `ola_ssh.sh` no seu computador:

```bash
#!/bin/bash
set -euo pipefail
source "${ROTINAS_LIB:?}/ssh.sh"

HOST="${1:?Uso: ola_ssh.sh HOST}"
echo "Conectando em $HOST como $SSH_USUARIO..."
remoto "$HOST" hostname
remoto "$HOST" "date; uname -a"
echo "Concluído."
```

Discutir: `set -euo pipefail`, uso de `remoto`, mensagens no log, nenhuma senha.

**Passo 2 (10 min) — cadastrar pela tela.** Menu **Rotinas** > **Nova rotina**:

- Nome: `ola_ssh_<seunome>`; Descrição: "Exercício da instrução".
- Deixe *Rotina ativa* marcada. Aviso à turma: como a rotina é nova e ativa, ela **roda uma vez sozinha logo depois de criada**; é o comportamento do Airflow e um bom momento para mostrar a primeira execução.
- Horário: **Diário**, hora e minuto à escolha; observe as **Próximas execuções**.
- Script: **Enviar arquivo** > `ola_ssh.sh`. Argumentos: `ssh-teste` (uma linha).
- Novas tentativas 0; Tempo máximo 5. Deixe *Avisar por e-mail* marcado.
- **Salvar**. Veja a rotina na lista e, depois de até 30 s, em **Dags**.

**Passo 3 (5 min) — executar e ler o log.** Abra o DAG, veja a execução automática da criação e dispare outra com **Trigger**; abra os Logs da tarefa `executar`. Resultado esperado: nome da máquina e data do `ssh-teste`.

**Passo 4 (5 min) — provocar um erro.** Edite a rotina, mude o argumento para `host-que-nao-existe`, salve e dispare. Discuta o log e o e-mail de falha: "Host key verification failed" / não resolve o nome. Volte o argumento para `ssh-teste`.

**Passo 5 (5 min) — ver o histórico e limpar.** Na VM, `git -C /opt/airflow-rotinas/dados log --oneline` (ou `dados-dev` na máquina de teste) mostra os commits das ações. Na tela, **Excluir** a rotina e leia a página de confirmação.

Variação para turmas adiantadas: criar a Variable `exercicio_token` (valor longo), mapear `TOKEN ← Variable exercicio_token` e fazer o script imprimir `echo "Token com ${#TOKEN} caracteres"` e `echo "$TOKEN"`; mostrar que o valor aparece como `***` no log.

## 5. Ler um log de falha (10 min)

Use a execução de falha do bloco 3 ou 4 e percorra, com os alunos, o método:

1. Qual rotina e qual horário? (assunto e corpo do e-mail)
2. Qual foi o erro final? (`O script terminou com código de saída N`, `Tempo limite de N min excedido`, `Segredo X: Variable 'Y' não encontrada`, `O script precisa começar com #!`)
3. Ler as últimas linhas do log: a mensagem do próprio script explica? Códigos comuns: 255 = falha do SSH (host não cadastrado, chave não instalada, rede); 127 = comando não encontrado; 126 = sem permissão/`#!` inválido.
4. Reproduzir: *Trigger* de novo depois de corrigir.
5. O que a vigia faria? Mostre o e-mail de problema/resolvido.

Casos para a turma diagnosticar (a partir de mensagens): `Host key verification failed`; `Permission denied (publickey)`; `sudo: a password is required`; `Segredo PGPASSWORD: Connection 'x' não encontrada`.

## 6. Dúvidas e próximos passos (5 min)

- Como migrar os scripts reais do cron: um a um, cada um com agendamento, tentativas e e-mail de falha ([criar-rotinas.md](criar-rotinas.md)).
- Preparar os alvos reais: [preparar-alvo.md](preparar-alvo.md).
- Operação e manutenção: [operacao.md](operacao.md). Limites: SSH só na porta 22; segredos curtos são mascarados no log inteiro.
- Passos futuros: LDAP/AD, HTTPS, monitoramento externo, Git interno, outros canais de aviso.

## Material para entregar aos alunos

README, [criar-rotinas.md](criar-rotinas.md) (principalmente "Guia para escrever scripts") e o script `ola_ssh.sh` deste roteiro.
