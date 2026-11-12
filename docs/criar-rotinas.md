# Criar e gerenciar rotinas

Uma **rotina** é um script mais um agendamento. Você a cadastra na tela **Rotinas** (menu lateral do Airflow, visível só para Admin) ou editando um arquivo YAML. Nos dois casos o resultado é o mesmo: um arquivo `rotinas/<nome>.yaml` no diretório de dados, e o Airflow cria um DAG com o mesmo nome em até cerca de 30 segundos.

> Capturas de tela podem ser acrescentadas aqui depois; por ora cada tela é descrita em texto.

## Avisos importantes

- **Uma rotina nova e ativa roda uma vez logo depois de criada.** O Airflow agenda o último intervalo previsto ao detectar um DAG novo. Se a rotina faz algo que não deve ser repetido fora de hora, crie-a **inativa**, confira e ative depois.
- **Ativar e desativar só pela tela "Rotinas".** O botão nativo de pausa do Airflow não altera o YAML; a vigia aponta a divergência por e-mail.
- **Editar regrava o YAML inteiro**: o formulário envia todos os campos. Edições feitas à mão no YAML são sobrescritas pelos valores do formulário ao salvar (e o que o formulário não conhece não é mantido).
- O nome não pode ser alterado depois (é o `dag_id`). Para renomear, crie outra rotina e exclua a antiga.

## A tela "Rotinas"

### Lista

Tabela com uma linha por rotina:

| Coluna | Conteúdo |
|---|---|
| Nome | Link para o DAG no Airflow (histórico e logs) e a descrição |
| Horário | Em linguagem legível ("Diário às 02:00", "Semanal, segunda-feira às 07:15", "Mensal, dia 1 às 03:00"), ou `Cron: ...` |
| Situação | Selo **Ativa** ou **Inativa** (o que está no YAML) |
| Status no Airflow | "Ativo", "Pausado", "Aguardando o Airflow carregar" (acabou de criar) ou "indisponível" (API fora). Se divergir do YAML aparece "Diverge do YAML — use os botões desta tela" |
| Última execução | "Sucesso em dd/mm/aaaa hh:mm", "Sem sucesso registrado" ou "Nunca executou" |
| Próxima execução | Data e hora, ou "— (inativa)" |
| Ações | **Editar**, **Ativar/Desativar**, **Excluir** |

No topo: botão **Nova rotina**. Acima da tabela aparecem, quando existirem, a caixa vermelha "Arquivos de rotina com erro" (YAMLs inválidos, com o motivo) e avisos amarelos (por exemplo, quando não foi possível aplicar a pausa no Airflow).

### Nova rotina / Editar

O formulário tem cinco blocos:

1. **Identificação**: *Nome* (3 a 64 caracteres: letras minúsculas, dígitos e `_`; somente leitura ao editar), *Descrição* e a caixa *Rotina ativa (roda no horário)*.
2. **Horário**: *Frequência* com **Diário**, **Semanal**, **Mensal** ou **Avançado (cron)**.
   - Diário: *Hora* e *Minuto*. Semanal: mais *Dia da semana*. Mensal: mais *Dia do mês* (1 a 28, para existir em todos os meses).
   - Avançado: *Expressão cron* de 5 campos (`minuto hora dia mês dia-da-semana`, ex.: `*/15 * * * *`) ou `@hourly`, `@daily`, `@weekly`, `@monthly`.
   - O fuso é America/Manaus. A área **Próximas execuções** mostra as três próximas datas enquanto você preenche; erro de horário aparece ali e ao lado do campo.
3. **Script**: *Enviar arquivo* (do computador onde está o navegador), *Usar um script já existente* (lista dos scripts que já estão na pasta `scripts/` do diretório de dados, na VM do Airflow; para um script aparecer ali, copie-o para `DADOS_HOST_DIR/scripts/`, por exemplo `cp meu.py /opt/airflow-rotinas/dados/scripts/exemplos/`) e, ao editar, *Manter o atual*. Em *Argumentos*, um argumento por linha. **Nunca coloque senhas nos argumentos.**
4. **Segredos**: botão **Adicionar segredo**; cada linha é `NOME_DA_VARIAVEL ← Variable | Connection`. Para Variable, informe o nome da Variable do Airflow; para Connection, o nome da Connection e o campo (`login`, `password`, `host`, `port`, `schema` ou `extra`). O script recebe o valor como variável de ambiente `NOME_DA_VARIAVEL`. A tela nunca mostra os valores. Cadastre antes a Variable/Connection em **Admin > Variables** ou **Admin > Connections**.
5. **Execução e avisos**: *Novas tentativas* (padrão 1; 0 = não repetir), *Intervalo entre tentativas (min)* (padrão 5), *Tempo máximo (min)* (padrão 60), a caixa *Avisar por e-mail quando falhar* e *E-mails extras para aviso* (separados por vírgula ou um por linha, além dos destinatários padrão).

Botões **Salvar** e **Cancelar**. Ao salvar com sucesso, volta para a lista; com erro, o formulário reaparece com a mensagem em português ao lado de cada campo e uma caixa vermelha no topo. Se o envio do arquivo falhar por qualquer motivo, a tela pede para escolher o arquivo de novo (o navegador não o guarda).

**Regras do upload do script:** até **1 MB**, arquivo de texto, primeira linha começando com `#!` (ex.: `#!/bin/bash`). Quebras de linha do Windows (CRLF) são convertidas para LF. O arquivo é gravado em `scripts/rotinas/<nome>/<arquivo>`. O envio é recusado se **outra rotina já usa o mesmo caminho de arquivo**; envie com outro nome.

### Ativar, desativar, excluir

- **Ativar/Desativar** grava `ativa` no YAML e pausa/despausa o DAG no Airflow. Se a pausa não puder ser aplicada na hora, aparece um aviso amarelo e a vigia acompanha a divergência.
- **Excluir** abre uma página de confirmação que explica o que será removido: o YAML, e o script apenas se tiver sido enviado pela tela (`rotinas/<nome>/...`) e nenhuma outra rotina o usar. O histórico de execuções permanece no Airflow e a versão anterior permanece no Git dos dados.

## Referência do YAML

Arquivo `rotinas/<nome>.yaml` no diretório de dados (`DADOS_HOST_DIR/rotinas/`). Exemplo completo:

```yaml
nome: backup_etc_servidor_teste        # obrigatório; vira o dag_id
descricao: Compacta o /etc do servidor de teste via SSH e guarda os 7 últimos
ativa: true
agendamento: "0 2 * * *"               # cron de 5 campos, horário de Manaus
script: exemplos/backup_etc_servidor_teste.sh   # relativo à pasta scripts/
argumentos: ["ssh-teste", "7"]         # lista de TEXTOS (números entre aspas)
tentativas: 2
intervalo_tentativa_min: 5
timeout_min: 15
avisar_falha: true
emails_aviso: ["infra@exemplo.mil.br"]
segredos:
  DB_SENHA: { variavel: senha_banco_x }
  PGPASSWORD: { conexao: postgres_airflow, campo: password }
criado_por: admin                      # preenchidos pela tela
atualizado_em: "2026-11-10T14:00:00-04:00"
```

| Campo | Obrigatório | Padrão | Regra |
|---|---|---|---|
| `nome` | sim | — | `^[a-z0-9_]{3,64}$`; único; é o `dag_id` |
| `agendamento` | sim | — | Cron de 5 campos ou `@hourly`, `@daily`, `@weekly`, `@monthly`; fuso America/Manaus |
| `script` | sim | — | Caminho relativo a `scripts/`; deve existir e não pode sair dessa pasta (sem `..` nem caminho absoluto) |
| `descricao` | não | vazio | Texto |
| `ativa` | não | `true` | `false` = DAG pausado |
| `argumentos` | não | `[]` | Lista de textos |
| `tentativas` | não | `1` | Inteiro >= 0: quantas **novas tentativas** após uma falha |
| `intervalo_tentativa_min` | não | `5` | Inteiro >= 1 |
| `timeout_min` | não | `60` | Inteiro >= 1; ao estourar, o script (e seus filhos) é encerrado e a tarefa falha |
| `avisar_falha` | não | `true` | Envia e-mail quando a rotina falha de vez |
| `emails_aviso` | não | vazio | Lista; se vazia, usa `AVISO_DESTINATARIOS` do `.env` |
| `segredos` | não | `{}` | Mapa `NOME: referência`. `NOME` segue `^[A-Z_][A-Z0-9_]*$`. Referência: `{ variavel: X }` ou `{ conexao: Y, campo: Z }` com campo em `login`, `password`, `host`, `port`, `schema`, `extra` |
| `criado_por`, `atualizado_em` | não | — | Preenchidos pela tela |

Campos desconhecidos são recusados. Um YAML inválido **não derruba as demais rotinas** e não some em silêncio:

- na tela "Rotinas" aparece na caixa "Arquivos de rotina com erro";
- no painel do Airflow aparece um DAG chamado `rotina_invalida__<arquivo>` (tag `erro`), com uma tarefa que falha mostrando o erro. Ele **não** aparece na lista "Import errors" do Airflow;
- a vigia envia e-mail (próximo ciclo de 15 minutos).

Para editar à mão: altere o YAML (e o script em `scripts/`) no diretório de dados e, depois, registre no Git dos dados (`git -C /opt/airflow-rotinas/dados add -A && git -C /opt/airflow-rotinas/dados commit -m "descrição"`). As alterações feitas pela tela já são registradas sozinhas.

## Como o script é executado

1. O Airflow copia o script para um diretório temporário exclusivo, torna-o executável e o roda **respeitando o `#!`** (bash, python3...), com os `argumentos`. A entrada padrão é vazia e o diretório atual é o temporário (não use caminhos relativos ao local do script).
2. O ambiente do processo tem `PATH`, `HOME`, `LANG` e:

   | Variável | Conteúdo |
   |---|---|
   | seus `segredos` | valores resolvidos (Variable/Connection) |
   | `SSH_CHAVE` | caminho de um arquivo temporário (modo 600) com a chave privada da Connection `ssh_padrao`; apagado ao final |
   | `SSH_USUARIO` | login da Connection `ssh_padrao` (padrão `airflow-svc`) |
   | `SSH_KNOWN_HOSTS` | `known_hosts` do ambiente |
   | `ROTINAS_LIB`, `PYTHONPATH` | pasta das bibliotecas de apoio (`/opt/rotinas/lib`) |
   | `BACKUPS_DIR` | pasta `backups/` (volume persistente) |
   | `ROTINA_NOME`, `ROTINA_EXECUCAO` | nome da rotina e id da execução, para logs e nomes de arquivo |

3. **Sucesso = código de saída 0.** Qualquer outro código é falha. Se passar de `timeout_min`, o processo recebe `SIGTERM`, depois de 10 s `SIGKILL`, e a tarefa falha.
4. Saída padrão e de erro vão para o log da tarefa, linha a linha.
5. Os valores dos `segredos` e a chave SSH são **mascarados** no log (`***`) e retirados das linhas enviadas por e-mail.
6. Ao final (com sucesso ou não) o diretório temporário e a chave são apagados.
7. Esgotadas as tentativas, vai um e-mail `[Rotinas] FALHA: <nome>` com horário, erro, as últimas 30 linhas do log e o link para o log completo (para `emails_aviso`, ou os destinatários padrão).

O script roda dentro do container, como usuário `airflow`, com as ferramentas da imagem: `bash`, `python3`, `ssh`/`scp`, `rsync`, `curl`, `psql`/`pg_dump`, `tar`, `gzip`, `git`, e em Python `paramiko` e `netmiko`, mais o que estiver listado em `ferramentas/sistema.txt` (pacotes do sistema: `ping`, `dig`, `nc`, `snmpwalk`, `nmap`...) e `ferramentas/python.txt` (bibliotecas Python). Faltou uma ferramenta? Acrescente o pacote no arquivo correspondente, faça commit e reconstrua na VM do Airflow (`git pull && docker compose up -d --build`). As instruções estão no início de cada arquivo.

## Guia para escrever scripts

> Resumo de uma página, com checklist e esqueletos: [padrao-de-scripts.md](padrao-de-scripts.md).

### Regras de ouro

- **Falhou, saia com código diferente de 0.** Em bash, comece com `set -euo pipefail`. Sem isso o Airflow mostra verde para uma rotina que falhou.
- **Primeira linha `#!`** (`#!/bin/bash` ou `#!/usr/bin/env python3`); sem ela a execução falha.
- **Escreva mensagens úteis no log**: o que está fazendo, em qual alvo, o que concluiu (`echo "Compactando /etc em $HOST..."`). Erros em `>&2` com a causa.
- **Seja idempotente**: rodar duas vezes (retentativa, *Trigger*, execução automática ao criar) não pode causar dano. Grave em arquivo temporário e renomeie ao final; limpe com `trap`; nunca deixe arquivo parcial.
- **Nada de senha ou chave dentro do script, do YAML ou nos argumentos.** Use `segredos` e leia da variável de ambiente (`"${PGPASSWORD:?}"`).
- **Prefira segredos longos**: o mascaramento troca o valor por `***` em todo o log. Um segredo curto (por exemplo, a palavra `airflow`) apagaria palavras comuns do log (`/opt/***/backups`). Informações que não são secretas (host, usuário, nome do banco) passe como `argumentos`.
- **Valide as entradas** (`[[ "$HOST" =~ ^[A-Za-z0-9._-]+$ ]]`) e use aspas em todas as variáveis.
- **Retenção e espaço**: ao gerar arquivos, apague os antigos (como os exemplos, que mantêm os N últimos).

### Scripts em bash: `ssh.sh`

```bash
#!/bin/bash
set -euo pipefail
source "${ROTINAS_LIB:?}/ssh.sh"

HOST="${1:?Uso: meu_script.sh HOST}"
remoto "$HOST" uname -a                              # roda no alvo e mostra no log
copiar_de "$HOST" /var/backups/dump.sql /tmp/dump.sql   # alvo -> local
copiar_para "$HOST" ./relatorio.txt /tmp/relatorio.txt   # local -> alvo
```

Funções: `remoto HOST COMANDO...`, `copiar_para HOST ORIGEM_LOCAL DESTINO_REMOTO`, `copiar_de HOST ORIGEM_REMOTA DESTINO_LOCAL`. Usam `SSH_CHAVE`, `SSH_USUARIO` (ou `SSH_USUARIO_ALVO`, se definida), `SSH_KNOWN_HOSTS`, sempre com `StrictHostKeyChecking=yes`, `BatchMode` e tempo limite de conexão de 15 s. O código de saída remoto é devolvido.

**Dois modos de `remoto`:**

| Chamada | O que acontece |
|---|---|
| `remoto HOST "cd /var/log && ls \| tail -3"` (**1** argumento após o host) | A string é enviada como está e **interpretada pelo shell do alvo** (pipes, `&&`, redirecionamentos, `~` funcionam) |
| `remoto HOST touch "arquivo com espaço"` (**2 ou mais** argumentos) | Cada argumento é protegido (`printf %q`) e chega **literalmente**: nenhum `$(...)`, `;` ou `*` é interpretado |

Consequência de segurança: no modo de 1 argumento, qualquer variável que você interpolar na string (`remoto "$HOST" "rm -rf $DIR"`) é código para o alvo. **Valide ou use o modo de vários argumentos** quando o valor vier de argumento, arquivo ou de fora. Exemplo: `remoto "$HOST" rm -rf -- "$DIR"` é seguro mesmo que `$DIR` contenha `; reboot`.

Limitação: só porta 22 (ver [preparar-alvo.md](preparar-alvo.md#limitações-conhecidas)).

### Scripts em Python: `ssh_util`

```python
#!/usr/bin/env python3
import sys
from ssh_util import remoto, enviar, receber, ErroRemoto, conectar_equipamento

host = sys.argv[1]
try:
    r = remoto(host, "df -h /", timeout=60)   # Resultado(codigo, saida, erro); levanta ErroRemoto se codigo != 0
    print(r.saida)
    receber(host, "/var/backups/dump.sql", "/tmp/dump.sql")
    enviar(host, "/tmp/relatorio.txt", "/tmp/relatorio.txt")
except ErroRemoto as e:
    print(f"ERRO: {e}", file=sys.stderr)
    sys.exit(1)

# equipamento de rede (netmiko), com verificação estrita da chave do servidor:
with conectar_equipamento("10.0.0.1", "cisco_ios") as conexao:
    print(conexao.send_command("show version"))
```

`ssh_util` (em `ROTINAS_LIB`, que está no `PYTHONPATH`) usa paramiko com `RejectPolicy`: host que não está no `known_hosts` é recusado. `remoto(..., verificar=False)` devolve o resultado mesmo com código diferente de 0. Uma exceção não tratada em Python já termina o script com código 1 (falha), o que é o comportamento desejado.

### Segredos na prática

1. Cadastre a senha/token: **Admin > Variables** (valor único) ou **Admin > Connections** (login, senha, host...).
2. Na rotina, em *Segredos*, mapeie `API_TOKEN ← Variable api_token` (ou `← Connection api_x, campo password`).
3. No script: `curl -s -H "Authorization: Bearer ${API_TOKEN:?}" "$URL"`. Nunca ponha o valor na linha de comando de outro programa quando houver alternativa (variável de ambiente, arquivo temporário 600) e evite `set -x`, que imprime cada comando expandido no log.

### Os exemplos

Em `scripts_base/exemplos/scripts/`. Os quatro das rotinas de exemplo são instalados em `scripts/exemplos/` pelo `instalar_exemplos.sh`: `backup_banco_airflow.sh` (segredo `PGPASSWORD` por Connection, retenção, arquivo parcial + renomear), `backup_etc_servidor_teste.sh` (SSH com `remoto`/`copiar_de`, `trap` de limpeza), `verifica_servicos_http.py` (lista de URLs como argumentos, código 1 se alguma falhar) e `exemplo_falha_proposital.sh`.

Os demais (SSH em Python, saúde de VMs, relatório remoto, `sudo` restrito, backup cifrado com segredo) estão descritos em [padrao-de-scripts.md](padrao-de-scripts.md#exemplos-prontos); para usá-los, copie para `scripts/exemplos/` do diretório de dados ou envie pela tela. Use-os como modelo.

## Conferir se deu certo

1. Na lista, clique no nome para abrir o DAG e use **Trigger** para disparar manualmente.
2. Na execução, abra a tarefa `executar` > **Logs** (não a aba "Audit Logs", que não mostra a saída do script).
3. Verde = código 0. Vermelho = leia as últimas linhas do log; as mensagens do seu script estão lá.
