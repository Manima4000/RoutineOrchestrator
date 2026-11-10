# Ambiente de Rotinas com Apache Airflow — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Airflow 3 em Docker numa VM, onde administradores cadastram pela web rotinas (script + horário) que rodam no próprio servidor do Airflow, com painel, logs, retentativa, aviso de falha e vigia de rotinas que não rodaram.

**Architecture:** Um pacote Python puro (`plugins/rotinas_core/`) concentra toda a lógica (validação do YAML, agenda, execução de script, segredos, notificação, vigia, armazenamento com Git). Ele é consumido por dois DAG files finos (`gerador_rotinas.py`, `vigia_rotinas.py`) e por um plugin FastAPI (menu "Rotinas"). As rotinas vivem como YAML + script num diretório de dados com Git próprio, fora do repositório do projeto.

**Tech Stack:** Apache Airflow 3.1.x (Python 3.12, LocalExecutor, FAB auth manager), PostgreSQL 16, Docker Compose, FastAPI + Jinja2 (plugin), PyYAML, croniter, paramiko, netmiko, pytest, Mailpit (testes), OpenSSH.

**Spec:** `docs/superpowers/specs/2026-11-10-airflow-rotinas-design.md`

## Global Constraints

- Airflow **3.1.x** fixado por versão exata (última patch no PyPI ao executar a Task 1), imagem `apache/airflow:<versão>-python3.12`. Nada de Celery, Redis ou workers extras.
- `AIRFLOW__CORE__EXECUTOR=LocalExecutor`; `AIRFLOW__CORE__DEFAULT_TIMEZONE=America/Manaus`; auth manager do provider FAB.
- Intervalo de leitura de DAGs ~30 s (`AIRFLOW__DAG_PROCESSOR__REFRESH_INTERVAL=30` ou equivalente da versão).
- Todo texto visível ao usuário (UI do plugin, mensagens de erro, e-mails, logs do sistema, docs) em **português**.
- Regex: `nome` = `^[a-z0-9_]{3,64}$`; nomes de segredo = `^[A-Z_][A-Z0-9_]*$`.
- Padrões do YAML: `tentativas=1`, `intervalo_tentativa_min=5`, `timeout_min=60`, `avisar_falha=true`, `ativa=true`.
- Segredos **nunca** na linha de comando; sempre por variável de ambiente; mascarados no log.
- SSH sempre com `StrictHostKeyChecking=yes` contra `SSH_KNOWN_HOSTS`; nunca aceitar host desconhecido.
- Plugin "Rotinas": toda rota exige papel **Admin** (não só esconder o menu).
- Upload de script: máx. **1 MB**, somente texto.
- Vigia roda a cada **15 min**; um aviso por problema até resolver, mais aviso de "resolvido".
- Segredos de ambiente (`.env`, chaves) nunca entram no Git do projeto.

**Variáveis de ambiente fixadas (dentro dos containers):**

| Variável | Valor |
|---|---|
| `ROTINAS_DIR` | `/opt/airflow/dados/rotinas` |
| `SCRIPTS_DIR` | `/opt/airflow/dados/scripts` |
| `DADOS_DIR` | `/opt/airflow/dados` (montado de `${DADOS_HOST_DIR}`, padrão `/opt/airflow-rotinas/dados`) |
| `SSH_KNOWN_HOSTS` | `/opt/airflow/ssh/known_hosts` |
| `ROTINAS_LIB` | `/opt/rotinas/lib` (copiado de `scripts_base/lib/` na imagem; também no `PYTHONPATH`) |
| `BACKUPS_DIR` | `/opt/airflow/backups` |
| `SMTP_HOST`, `SMTP_PORTA`, `SMTP_TLS`, `SMTP_USUARIO`, `SMTP_SENHA`, `SMTP_REMETENTE`, `AVISO_DESTINATARIOS` | do `.env` |
| `AIRFLOW_API_URL`, `AIRFLOW_API_USUARIO`, `AIRFLOW_API_SENHA` | conta de serviço usada pela vigia e pelo plugin para falar com a API REST |
| `AIRFLOW_UI_URL` | URL base usada nos links dos e-mails |

## Review Focus

1. **Script enviado com quebras de linha do Windows (CRLF)** — o shebang quebra ("bad interpreter"). Esperado: o plugin converte CRLF→LF ao salvar. Teste em Task 10.
2. **Script sem shebang** — esperado: o plugin recusa com "O script precisa começar com #! (ex.: #!/bin/bash)"; o executor também falha com mensagem clara. Testes em Tasks 4 e 10.
3. **Script que cria processos filhos ou ignora SIGTERM e estoura o timeout** — esperado: todo o grupo de processos é encerrado (SIGTERM, 10 s, SIGKILL) e a tarefa falha com "Tempo limite de N min excedido". Teste em Task 4.
4. **Criar rotina com nome que já existe** — esperado: erro "Já existe uma rotina com esse nome", nada sobrescrito. Teste em Task 10.
5. **Saída do script com bytes não-UTF-8 ou muito volumosa** — esperado: o log decodifica com substituição, não trava nem estoura memória (leitura linha a linha). Teste em Task 4.

---

## File Structure

```
ORF/
├── Dockerfile                      # imagem própria (Task 1)
├── docker-compose.yml              # serviços + profile teste (Task 1)
├── requirements.txt                # dependências extras pinadas (Task 1)
├── .env.example  .gitignore        # (Task 1)
├── pytest.ini                      # (Task 1)
├── instalar.sh                     # gera .env, prepara diretório de dados (Task 1)
├── teste/ssh/Dockerfile            # servidor SSH de teste (Task 1)
├── plugins/
│   ├── rotinas_core/
│   │   ├── __init__.py
│   │   ├── config.py               # leitura das variáveis de ambiente (Task 1)
│   │   ├── modelo.py               # Rotina, validação, carregar_rotinas (Task 2)
│   │   ├── agenda.py               # presets ↔ cron, descrição, próximas (Task 3)
│   │   ├── execucao.py             # roda script com timeout/log (Task 4)
│   │   ├── notificacao.py          # e-mail (Task 5)
│   │   ├── tarefa.py               # executar_rotina: segredos, chave, env (Task 6)
│   │   ├── api_airflow.py          # cliente REST do Airflow (Task 9)
│   │   ├── vigia.py                # avaliação de problemas (Task 9)
│   │   └── armazenamento.py        # repositório de rotinas com Git (Task 10)
│   └── rotinas_web/
│       ├── __init__.py             # AirflowPlugin (Task 11)
│       ├── app.py                  # FastAPI app e rotas (Task 11)
│       ├── seguranca.py            # exigir_admin, checagem de Origin (Task 11)
│       └── templates/*.html        # telas (Task 11)
├── dags/
│   ├── gerador_rotinas.py          # (Task 7)
│   └── vigia_rotinas.py            # (Task 9)
├── scripts_base/
│   ├── lib/ssh.sh  lib/ssh_util.py # bibliotecas de apoio (Task 8)
│   ├── cadastrar_alvo.sh           # ssh-keyscan + impressão digital (Task 8)
│   └── exemplos/                   # scripts + YAMLs de exemplo (Task 12)
├── tests/                          # espelha os módulos; integração marcada (todas)
└── docs/                           # manuais (Task 13)
```

**Como rodar os testes (todas as tasks):** `docker compose --profile teste run --rm testes pytest <alvo> -v`. O serviço `testes` usa a imagem própria, monta `plugins/`, `dags/`, `scripts_base/` e `tests/`, e tem `PYTHONPATH=/opt/airflow/plugins:/opt/rotinas/lib`. Testes que precisam do `ssh-teste`, do `mailpit` ou do Airflow no ar levam `@pytest.mark.integracao`; os demais não dependem de nenhum serviço.

> Pré-requisito: Docker Engine + plugin Compose na máquina de desenvolvimento (a máquina atual não tem; instalar antes da Task 1, ou desenvolver direto na VM).

---

### Task 1: Ambiente base (imagem, compose, instalação, executor de testes)

**Files:**
- Create: `Dockerfile`, `requirements.txt`, `docker-compose.yml`, `.env.example`, `.gitignore`, `pytest.ini`, `instalar.sh`, `teste/ssh/Dockerfile`, `plugins/rotinas_core/__init__.py`, `plugins/rotinas_core/config.py`
- Test: `tests/test_config.py`, `tests/test_ambiente.py`

**Interfaces:**
- Produces: `rotinas_core.config.Config` (dataclass congelada) com campos `rotinas_dir: Path`, `scripts_dir: Path`, `dados_dir: Path`, `known_hosts: Path`, `lib_dir: Path`, `backups_dir: Path`, `smtp_host: str`, `smtp_porta: int`, `smtp_tls: bool`, `smtp_usuario: str | None`, `smtp_senha: str | None`, `smtp_remetente: str`, `aviso_destinatarios: list[str]`, `api_url: str`, `api_usuario: str`, `api_senha: str`, `ui_url: str`; e `carregar_config(env: Mapping[str, str] = os.environ) -> Config`.
- Produces: serviços compose `postgres`, `airflow-init`, `airflow-apiserver`, `airflow-scheduler`, `airflow-dag-processor`; profile `teste`: `mailpit` (SMTP 1025, UI 8025), `ssh-teste` (usuário `airflow-svc`, porta 22, chave pública de `teste/ssh/chave_teste.pub` gerada pelo `instalar.sh --teste`), `testes`.

- [ ] **Step 1: Escrever `tests/test_config.py`**

```python
def test_carregar_config_le_valores_e_padroes():
    env = {"ROTINAS_DIR": "/d/rotinas", "SCRIPTS_DIR": "/d/scripts", "DADOS_DIR": "/d",
           "SSH_KNOWN_HOSTS": "/s/kh", "ROTINAS_LIB": "/l", "BACKUPS_DIR": "/b",
           "SMTP_HOST": "mailpit", "SMTP_PORTA": "1025", "SMTP_TLS": "false",
           "SMTP_REMETENTE": "airflow@cta", "AVISO_DESTINATARIOS": "a@x, b@x",
           "AIRFLOW_API_URL": "http://api:8080", "AIRFLOW_API_USUARIO": "svc",
           "AIRFLOW_API_SENHA": "s", "AIRFLOW_UI_URL": "http://vm:8080"}
    c = carregar_config(env)
    assert c.rotinas_dir == Path("/d/rotinas")
    assert c.smtp_porta == 1025 and c.smtp_tls is False
    assert c.aviso_destinatarios == ["a@x", "b@x"]
    assert c.smtp_usuario is None

def test_carregar_config_falta_variavel_obrigatoria():
    with pytest.raises(KeyError):
        carregar_config({})
```

- [ ] **Step 2: Implementar `Dockerfile`, `requirements.txt`, `docker-compose.yml`, `.env.example`, `.gitignore`, `pytest.ini`, `config.py`**
  - Dockerfile: `FROM apache/airflow:${AIRFLOW_VERSION}-python3.12`; build args `HTTP_PROXY`/`HTTPS_PROXY` repassados ao apt/pip; apt: `openssh-client rsync curl postgresql-client tar gzip git`; pip com constraints oficiais do Airflow: `requirements.txt` (`apache-airflow-providers-fab`, `pyyaml`, `croniter`, `paramiko`, `netmiko`, `jinja2`, `python-multipart`, `pytest`, `httpx`); `COPY scripts_base/lib /opt/rotinas/lib`; `git config --system` com nome/e-mail padrão "Airflow Rotinas".
  - compose: rede com sub-rede de `${DOCKER_SUBNET:-172.30.0.0/24}`; volumes `./dags`, `./plugins`, `./logs`, `${DADOS_HOST_DIR}:/opt/airflow/dados`, `./ssh:/opt/airflow/ssh`, `./backups:/opt/airflow/backups`; `env_file: .env`; healthchecks; `airflow-init` roda migração e cria o Admin inicial e a conta de serviço da API (`AIRFLOW_API_USUARIO`, papel `Admin`).
  - `.gitignore`: `.env`, `logs/`, `backups/`, `ssh/`, `dados-dev/`, `teste/ssh/chave_teste*`.

- [ ] **Step 3: Implementar `instalar.sh`**
  Idempotente. Gera `.env` a partir de `.env.example` se não existir, preenchendo `AIRFLOW__CORE__FERNET_KEY`, `AIRFLOW__API_AUTH__JWT_SECRET` (ou equivalente da versão), senha do Postgres, do Admin e da conta de serviço com valores aleatórios. Cria `${DADOS_HOST_DIR}/{rotinas,scripts}`, faz `git init` nele se não for repositório, cria `ssh/known_hosts` vazio (`chmod 600`). Com `--teste`: gera `teste/ssh/chave_teste{,.pub}` (ed25519) e usa `DADOS_HOST_DIR=./dados-dev`. Imprime ao final a chave Fernet com o aviso "Guarde esta chave em local seguro".

- [ ] **Step 4: Escrever `tests/test_ambiente.py` (integração)**

```python
@pytest.mark.integracao
def test_api_airflow_saudavel():
    r = httpx.get(os.environ["AIRFLOW_API_URL"] + "/api/v2/monitor/health", timeout=10)
    assert r.status_code == 200
    assert r.json()["scheduler"]["status"] == "healthy"

@pytest.mark.integracao
def test_executor_local_e_fuso():
    assert os.environ["AIRFLOW__CORE__EXECUTOR"] == "LocalExecutor"
    assert os.environ["AIRFLOW__CORE__DEFAULT_TIMEZONE"] == "America/Manaus"
```

- [ ] **Step 5: Subir e verificar**
  Run: `./instalar.sh --teste && docker compose --profile teste up -d --build && docker compose --profile teste run --rm testes pytest tests/test_config.py tests/test_ambiente.py -v`
  Expected: 4 passed; `http://localhost:8080` abre o login; `docker compose ps` sem serviços `redis`/`worker`.

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat: ambiente base Airflow em Docker com profile de teste"`

---

### Task 2: Modelo da rotina e validação do YAML

**Files:**
- Create: `plugins/rotinas_core/modelo.py`
- Test: `tests/test_modelo.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class RefSegredo: variavel: str | None = None; conexao: str | None = None; campo: str | None = None`
  - `@dataclass(frozen=True) class Rotina:` campos do spec §5 — `nome: str, descricao: str, ativa: bool, agendamento: str, script: str, argumentos: tuple[str, ...], tentativas: int, intervalo_tentativa_min: int, timeout_min: int, avisar_falha: bool, emails_aviso: tuple[str, ...], segredos: dict[str, RefSegredo], criado_por: str | None, atualizado_em: str | None`; método `para_dict() -> dict` (forma serializável no YAML, omitindo `None`).
  - `class RotinaInvalida(Exception): erros: dict[str, str]` (campo → mensagem em português).
  - `validar(dados: dict, scripts_dir: Path) -> Rotina` (aplica padrões; levanta `RotinaInvalida` com **todos** os erros de uma vez).
  - `carregar_rotinas(rotinas_dir: Path, scripts_dir: Path) -> tuple[list[Rotina], dict[str, str]]` — válidas ordenadas por nome; erros por nome de arquivo (`"x.yaml" → "mensagem"`); nomes duplicados entre arquivos são erro em ambos.
  - Campo `agendamento` validado por `agenda.cron_valido` (Task 3) — **nesta task**, usar `croniter.is_valid` mais os presets `@hourly @daily @weekly @monthly`; a Task 3 só reaproveita.

- [ ] **Step 1: Escrever testes**

```python
def test_valida_minimo_aplica_padroes(tmp_scripts):  # fixture cria scripts/a.sh
    r = validar({"nome": "rotina_a", "agendamento": "0 2 * * *", "script": "a.sh"}, tmp_scripts)
    assert (r.ativa, r.tentativas, r.intervalo_tentativa_min, r.timeout_min, r.avisar_falha) == (True, 1, 5, 60, True)
    assert r.argumentos == () and r.segredos == {}

@pytest.mark.parametrize("campo,valor,msg", [
    ("nome", "Ab", "nome"), ("nome", "com-hifen", "nome"),
    ("agendamento", "99 * * * *", "agendamento"),
    ("script", "../fora.sh", "script"), ("script", "/etc/passwd", "script"),
    ("script", "nao_existe.sh", "script"),
    ("tentativas", -1, "tentativas"), ("timeout_min", 0, "timeout_min"),
])
def test_campo_invalido(tmp_scripts, campo, valor, msg):
    dados = {"nome": "rotina_a", "agendamento": "0 2 * * *", "script": "a.sh", campo: valor}
    with pytest.raises(RotinaInvalida) as e:
        validar(dados, tmp_scripts)
    assert msg in e.value.erros

def test_varios_erros_de_uma_vez(tmp_scripts):
    with pytest.raises(RotinaInvalida) as e:
        validar({"nome": "X", "agendamento": "ruim", "script": "a.sh"}, tmp_scripts)
    assert {"nome", "agendamento"} <= e.value.erros.keys()

def test_segredo_nome_invalido_e_ref_incompleta(tmp_scripts):
    base = {"nome": "rotina_a", "agendamento": "@daily", "script": "a.sh"}
    with pytest.raises(RotinaInvalida) as e:
        validar({**base, "segredos": {"minusculo": {"variavel": "v"}, "OK": {"conexao": "c"}}}, tmp_scripts)
    assert "segredos" in e.value.erros

def test_carregar_isola_arquivo_invalido(tmp_path):
    # rotinas/a.yaml válido, b.yaml com YAML quebrado, c.yaml sem nome
    validas, erros = carregar_rotinas(rotinas_dir, scripts_dir)
    assert [r.nome for r in validas] == ["rotina_a"]
    assert set(erros) == {"b.yaml", "c.yaml"}

def test_nome_duplicado_entre_arquivos(tmp_path):
    validas, erros = carregar_rotinas(...)  # x.yaml e y.yaml com nome "dup"
    assert validas == [] and set(erros) == {"x.yaml", "y.yaml"}
```

Regras de `segredos`: cada valor tem exatamente `variavel` **ou** (`conexao` **e** `campo`), com `campo` ∈ {`login`, `password`, `host`, `port`, `schema`, `extra`}.

- [ ] **Step 2: Rodar** — `pytest tests/test_modelo.py -v` → FAIL (módulo inexistente)
- [ ] **Step 3: Implementar `modelo.py`** — `yaml.safe_load`; caminho do script resolvido com `(scripts_dir / script).resolve()` e checagem `is_relative_to(scripts_dir.resolve())`.
- [ ] **Step 4: Rodar** — PASS
- [ ] **Step 5: Commit** — `feat: modelo e validação de rotinas`

---

### Task 3: Agenda (presets, descrição legível, próximas execuções)

**Files:**
- Create: `plugins/rotinas_core/agenda.py`
- Test: `tests/test_agenda.py`

**Interfaces:**
- Produces:
  - `cron_valido(expr: str) -> bool`
  - `preset_para_cron(tipo: Literal["diario", "semanal", "mensal"], hora: int, minuto: int, dia_semana: int | None = None, dia_mes: int | None = None) -> str` (`dia_semana` 0=domingo…6=sábado; `dia_mes` 1–28, para valer em todo mês)
  - `cron_para_preset(expr: str) -> dict | None` (inverso, para preencher o formulário; `None` se não for preset)
  - `descrever(expr: str) -> str`
  - `proximas(expr: str, n: int, agora: datetime) -> list[datetime]` (fuso America/Manaus)
- `modelo.py` passa a usar `cron_valido` daqui (remover a duplicação da Task 2).

- [ ] **Step 1: Escrever testes**

```python
def test_presets():
    assert preset_para_cron("diario", 2, 0) == "0 2 * * *"
    assert preset_para_cron("semanal", 23, 30, dia_semana=0) == "30 23 * * 0"
    assert preset_para_cron("mensal", 3, 15, dia_mes=1) == "15 3 1 * *"
    with pytest.raises(ValueError): preset_para_cron("mensal", 3, 0, dia_mes=31)

def test_ida_e_volta():
    assert cron_para_preset("30 23 * * 0") == {"tipo": "semanal", "hora": 23, "minuto": 30, "dia_semana": 0}
    assert cron_para_preset("*/5 * * * *") is None

def test_descrever():
    assert descrever("0 2 * * *") == "Diário às 02:00"
    assert descrever("30 23 * * 0") == "Semanal, domingo às 23:30"
    assert descrever("15 3 1 * *") == "Mensal, dia 1 às 03:15"
    assert descrever("@daily") == "Diário às 00:00"
    assert descrever("*/5 * * * *") == "Cron: */5 * * * *"

def test_proximas_em_manaus():
    agora = datetime(2026, 11, 10, 12, 0, tzinfo=ZoneInfo("America/Manaus"))
    p = proximas("0 2 * * *", 2, agora)
    assert p[0] == datetime(2026, 11, 11, 2, 0, tzinfo=ZoneInfo("America/Manaus"))
    assert len(p) == 2
```

- [ ] **Step 2: Rodar** → FAIL · **Step 3: Implementar** (croniter) · **Step 4: Rodar** `pytest tests/test_agenda.py tests/test_modelo.py -v` → PASS
- [ ] **Step 5: Commit** — `feat: agenda com presets e descrição em português`

---

### Task 4: Execução de script

**Files:**
- Create: `plugins/rotinas_core/execucao.py`
- Test: `tests/test_execucao.py`

**Interfaces:**
- Produces:
  - `class ErroExecucao(Exception)` com subclasses `SemShebang`, `TempoEsgotado`, `CodigoSaidaNaoZero(codigo: int)`; mensagens em português (ex.: `"Tempo limite de 1 min excedido"`, `"O script terminou com código de saída 3"`).
  - `executar(script: Path, argumentos: Sequence[str], env: Mapping[str, str], timeout_s: int, log: Callable[[str], None]) -> None` — copia o script para um diretório temporário exclusivo (`tempfile.mkdtemp(prefix="rotina-")`, `chmod 700`), executa com `cwd` nesse diretório, `start_new_session=True`, env = `PATH`/`HOME`/`LANG` do processo pai + `env` recebido; cada linha de stdout+stderr (mesclados) vai para `log` decodificada com `errors="replace"`; ao estourar: `killpg` SIGTERM, espera 10 s, SIGKILL, levanta `TempoEsgotado`; código ≠ 0 levanta `CodigoSaidaNaoZero`; remove o diretório temporário sempre.

- [ ] **Step 1: Escrever testes** (scripts criados em `tmp_path` pelos testes)

```python
def test_sucesso_e_log(tmp_path):
    s = script(tmp_path, "#!/bin/bash\necho ola $1\necho erro >&2\n")
    linhas = []
    executar(s, ["mundo"], {}, 30, linhas.append)
    assert "ola mundo" in linhas and "erro" in linhas

def test_codigo_nao_zero(tmp_path):
    with pytest.raises(CodigoSaidaNaoZero) as e:
        executar(script(tmp_path, "#!/bin/bash\nexit 3\n"), [], {}, 30, lambda _: None)
    assert e.value.codigo == 3 and "código de saída 3" in str(e.value)

def test_sem_shebang(tmp_path):
    with pytest.raises(SemShebang):
        executar(script(tmp_path, "echo oi\n"), [], {}, 30, lambda _: None)

def test_env_chega_ao_script(tmp_path):
    linhas = []
    executar(script(tmp_path, "#!/bin/bash\necho $SEGREDO_X\n"), [], {"SEGREDO_X": "abc"}, 30, linhas.append)
    assert linhas == ["abc"]

def test_timeout_mata_grupo_inclusive_filhos_que_ignoram_term(tmp_path):
    marca = tmp_path / "filho.pid"
    s = script(tmp_path, f"#!/bin/bash\ntrap '' TERM\n(trap '' TERM; echo $BASHPID > {marca}; sleep 300) &\nsleep 300\n")
    with pytest.raises(TempoEsgotado):
        executar(s, [], {}, 1, lambda _: None)
    pid = int(marca.read_text())
    assert not pid_vivo(pid)

def test_bytes_invalidos_e_saida_grande(tmp_path):
    s = script(tmp_path, "#!/bin/bash\nprintf '\\xff\\xfe ok\\n'\nseq 1 200000\n")
    linhas = []
    executar(s, [], {}, 60, linhas.append)
    assert linhas[0].endswith(" ok") and len(linhas) == 200001

def test_diretorio_temporario_removido(tmp_path):
    linhas = []
    executar(script(tmp_path, "#!/bin/bash\npwd\n"), [], {}, 30, linhas.append)
    assert not Path(linhas[0]).exists()
```

- [ ] **Step 2: Rodar** → FAIL · **Step 3: Implementar** · **Step 4: Rodar** → PASS (o teste de timeout leva ~11 s)
- [ ] **Step 5: Commit** — `feat: execução de script com timeout e log`

---

### Task 5: Notificação por e-mail

**Files:**
- Create: `plugins/rotinas_core/notificacao.py`
- Test: `tests/test_notificacao.py`

**Interfaces:**
- Consumes: `Config` (Task 1).
- Produces:
  - `enviar(config: Config, assunto: str, corpo: str, destinatarios: Sequence[str]) -> None` (smtplib; STARTTLS se `smtp_tls`; login se `smtp_usuario`; sem destinatários = não envia e registra aviso no log do Python).
  - `montar_aviso_falha(nome: str, quando: datetime, erro: str, ultimas_linhas: Sequence[str], link_log: str) -> tuple[str, str]` → `(assunto, corpo)`; assunto exatamente `"[Rotinas] FALHA: {nome}"`.
  - `montar_aviso_vigia(novos: Sequence[str], resolvidos: Sequence[str]) -> tuple[str, str]`; assunto `"[Rotinas] Vigia: {len(novos)} problema(s), {len(resolvidos)} resolvido(s)"`.
  - Ponto único para outros canais no futuro: só `enviar` sabe de SMTP.

- [ ] **Step 1: Testes** — unitários de `montar_*` (assunto exato; corpo contém nome, horário formatado `dd/mm/aaaa HH:MM`, erro, até 30 últimas linhas, link) e `enviar` com `smtplib.SMTP` substituído por fake (verifica remetente, destinatários, `starttls` chamado só com TLS). Integração (`@integracao`): envia ao `mailpit` e confere via `GET http://mailpit:8025/api/v1/messages` que o assunto chegou.
- [ ] **Step 2: Rodar** → FAIL · **Step 3: Implementar** · **Step 4: Rodar** → PASS
- [ ] **Step 5: Commit** — `feat: notificação de falha por e-mail`

---

### Task 6: Tarefa de execução de rotina (segredos, chave SSH, ambiente, aviso)

**Files:**
- Create: `plugins/rotinas_core/tarefa.py`
- Test: `tests/test_tarefa.py`

**Interfaces:**
- Consumes: `Rotina`, `RefSegredo` (Task 2), `executar`, `ErroExecucao` (Task 4), `enviar`, `montar_aviso_falha` (Task 5), `Config`.
- Produces:
  - `class ErroSegredo(Exception)`.
  - `resolver_segredos(segredos: Mapping[str, RefSegredo], obter_variavel: Callable[[str], str], obter_conexao: Callable[[str], Any]) -> dict[str, str]` — levanta `ErroSegredo` com mensagem clara `"Segredo DB_SENHA: Variable 'x' não encontrada"` (idem `"Connection 'x' não encontrada"`).
  - `montar_ambiente(rotina: Rotina, segredos: dict[str, str], chave_path: Path | None, ssh_usuario: str | None, config: Config, execucao_id: str) -> dict[str, str]` → inclui segredos, `SSH_CHAVE`, `SSH_USUARIO`, `SSH_KNOWN_HOSTS`, `ROTINAS_LIB`, `PYTHONPATH` (com `lib_dir`), `ROTINA_NOME`, `ROTINA_EXECUCAO`, `BACKUPS_DIR`.
  - `chave_temporaria(conteudo: str | None) -> ContextManager[Path | None]` — arquivo `600` em diretório temporário `700`, removido na saída mesmo com exceção.
  - `executar_rotina(nome: str, contexto: dict) -> None` — função chamada pelo DAG: recarrega a rotina via `carregar_rotinas` (pega a versão atual do YAML), resolve segredos com `airflow.sdk.Variable.get` / `airflow.sdk.Connection.get`, chama `mask_secret` do Airflow para cada valor, lê a Connection `ssh_padrao` se existir (chave privada em `extra["private_key"]`, usuário em `login`; ausente = sem `SSH_CHAVE`/`SSH_USUARIO` no ambiente), roda `executar(... timeout_s=rotina.timeout_min*60, log=logger.info)`.
  - `ao_falhar(contexto: dict) -> None` — callback `on_failure_callback`: se `avisar_falha`, envia `montar_aviso_falha` para `emails_aviso` ou `config.aviso_destinatarios`; link `"{ui_url}/dags/{dag_id}/runs/{run_id}"`; só dispara na última tentativa (o Airflow já só chama `on_failure_callback` após esgotar retries — confirmar e testar com `on_retry_callback` ausente).

- [ ] **Step 1: Testes** (Airflow substituído por fakes via injeção/monkeypatch)

```python
def test_resolver_segredos():
    refs = {"DB_SENHA": RefSegredo(variavel="senha_x"), "TOKEN": RefSegredo(conexao="api", campo="password")}
    conn = SimpleNamespace(password="t0k", login="u", host="h", port=1, schema="s", extra="{}")
    assert resolver_segredos(refs, {"senha_x": "s3nha"}.__getitem__, lambda c: conn) == {"DB_SENHA": "s3nha", "TOKEN": "t0k"}

def test_segredo_inexistente_mensagem_clara():
    with pytest.raises(ErroSegredo, match="Segredo DB_SENHA: Variable 'senha_x' não encontrada"):
        resolver_segredos({"DB_SENHA": RefSegredo(variavel="senha_x")}, falha_key_error, None)

def test_chave_temporaria_permissoes_e_remocao():
    with chave_temporaria("-----BEGIN KEY-----\n") as p:
        assert oct(p.stat().st_mode & 0o777) == "0o600"
    assert not p.exists()

def test_chave_removida_mesmo_com_excecao(): ...

def test_montar_ambiente_contem_variaveis_fixas(config, rotina): 
    env = montar_ambiente(rotina, {"A": "1"}, Path("/tmp/k"), "airflow-svc", config, "run_1")
    assert env["SSH_CHAVE"] == "/tmp/k" and env["SSH_USUARIO"] == "airflow-svc"
    assert env["SSH_KNOWN_HOSTS"] == str(config.known_hosts) and env["A"] == "1"
    assert env["ROTINA_NOME"] == rotina.nome and str(config.lib_dir) in env["PYTHONPATH"]

def test_segredos_nunca_nos_argumentos(monkeypatch, ...):
    # executar_rotina com segredo "s3nha": o argv passado a executar não contém "s3nha"

def test_cada_segredo_e_mascarado(monkeypatch, ...):
    # executar_rotina com 2 segredos: mask_secret (substituído por fake) recebeu os 2 valores antes de executar ser chamado

def test_ao_falhar_envia_para_destinatarios_da_rotina(...): ...
def test_ao_falhar_respeita_avisar_falha_false(...): ...
```

- [ ] **Step 2: Rodar** → FAIL · **Step 3: Implementar** · **Step 4: Rodar** → PASS
- [ ] **Step 5: Commit** — `feat: tarefa de execução de rotina com segredos e chave SSH`

---

### Task 7: Gerador de DAGs

**Files:**
- Create: `dags/gerador_rotinas.py`
- Test: `tests/test_gerador.py`

**Interfaces:**
- Consumes: `carregar_rotinas` (Task 2), `executar_rotina`, `ao_falhar` (Task 6), `carregar_config`.
- Produces:
  - `construir_dags(rotinas: list[Rotina], erros: dict[str, str]) -> dict[str, DAG]` (função pura, testável) e, no nível do módulo, `globals().update(construir_dags(*carregar_rotinas(...)))`.
  - Para cada rotina válida: `DAG(dag_id=nome, schedule=agendamento, start_date=datetime(2026, 1, 1, tz=America/Manaus), catchup=False, max_active_runs=1, tags=["rotina"], description=descricao, is_paused_upon_creation=not ativa)`; uma tarefa `executar` (`PythonOperator` chamando `executar_rotina(nome, contexto)`) com `retries=tentativas`, `retry_delay=timedelta(minutes=intervalo_tentativa_min)`, `execution_timeout=timedelta(minutes=timeout_min) + 1 min` (folga para o timeout próprio do `executar`, que é quem gera a mensagem amigável), `on_failure_callback=ao_falhar`.
  - Para cada arquivo inválido: DAG `rotina_invalida__<stem saneado>` com `schedule=None`, tag `["rotina", "erro"]`, `description="ERRO: <mensagem>"`, tarefa única que falha com a mensagem. A vigia (Task 9) é quem avisa; este DAG serve para o erro aparecer no painel.

- [ ] **Step 1: Testes**

```python
def test_dag_com_parametros_da_rotina(rotina_exemplo):
    dags = construir_dags([rotina_exemplo], {})
    d = dags["rotina_a"]
    t = d.get_task("executar")
    assert d.max_active_runs == 1 and d.catchup is False and "rotina" in d.tags
    assert t.retries == 2 and t.retry_delay == timedelta(minutes=5)
    assert t.execution_timeout == timedelta(minutes=61)

def test_rotina_inativa_nasce_pausada(rotina_inativa):
    assert construir_dags([rotina_inativa], {})["rotina_b"].is_paused_upon_creation is True

def test_arquivo_invalido_vira_dag_de_erro():
    dags = construir_dags([], {"meu arquivo.yaml": "nome: campo obrigatório"})
    d = dags["rotina_invalida__meu_arquivo"]
    assert "erro" in d.tags and "campo obrigatório" in d.description

def test_dagbag_importa_sem_erros(tmp_dados):  # integração leve: DagBag sobre dags/ com ROTINAS_DIR apontando para fixtures
    bag = DagBag(dag_folder="dags/gerador_rotinas.py", include_examples=False)
    assert bag.import_errors == {}
```

- [ ] **Step 2: Rodar** → FAIL · **Step 3: Implementar** · **Step 4: Rodar** → PASS
- [ ] **Step 5: Verificar no ambiente** — copiar um YAML de teste (`echo` simples) para `dados-dev/rotinas/`, aguardar ~30 s, conferir o DAG na UI, disparar com *Trigger*, ver log verde. Depois um YAML com `exit 1` e `avisar_falha: true`: ver vermelho e e-mail no Mailpit (`http://localhost:8025`).
- [ ] **Step 6: Commit** — `feat: gerador de DAGs a partir dos YAMLs`

---

### Task 8: Bibliotecas de apoio SSH e cadastro de alvo

**Files:**
- Create: `scripts_base/lib/ssh.sh`, `scripts_base/lib/ssh_util.py`, `scripts_base/cadastrar_alvo.sh`
- Test: `tests/test_ssh_libs.py` (integração com `ssh-teste`)

**Interfaces:**
- Consumes: variáveis `SSH_CHAVE`, `SSH_USUARIO`, `SSH_KNOWN_HOSTS` (Task 6).
- Produces:
  - `ssh.sh`: `remoto HOST COMANDO...`, `copiar_para HOST ORIGEM DESTINO`, `copiar_de HOST ORIGEM DESTINO`. Opções fixas: `-i "$SSH_CHAVE" -o UserKnownHostsFile="$SSH_KNOWN_HOSTS" -o StrictHostKeyChecking=yes -o BatchMode=yes -o ConnectTimeout=15`; usuário `${SSH_USUARIO_ALVO:-$SSH_USUARIO}`; aborta com mensagem em português se `SSH_CHAVE` vazia; repassa o código de saída remoto.
  - `ssh_util.py`: `remoto(host: str, comando: str, usuario: str | None = None, timeout: int = 300) -> Resultado` (`Resultado(codigo: int, saida: str, erro: str)`; levanta `ErroRemoto` se `codigo != 0` a menos que `verificar=False`), `enviar(host, origem, destino)`, `receber(host, origem, destino)`, `conectar_equipamento(host: str, tipo_dispositivo: str, **kw) -> netmiko.BaseConnection` — todos com paramiko `RejectPolicy` e `load_host_keys(SSH_KNOWN_HOSTS)`.
  - `cadastrar_alvo.sh HOST [PORTA]`: `ssh-keyscan` → mostra impressões digitais (`ssh-keygen -lf`) → pergunta "As impressões digitais conferem com as do servidor? (s/N)" → só então acrescenta ao `ssh/known_hosts`. Imprime também a chave pública do ambiente a instalar no alvo.

- [ ] **Step 1: Testes** (o fixture executa `cadastrar_alvo.sh ssh-teste` em modo não interativo `--sim` e exporta as variáveis com `teste/ssh/chave_teste`)

```python
@pytest.mark.integracao
def test_bash_remoto_ok(env_ssh):
    r = run(["bash", "-c", f"source {LIB}/ssh.sh; remoto ssh-teste whoami"], env=env_ssh)
    assert r.returncode == 0 and r.stdout.strip() == "airflow-svc"

@pytest.mark.integracao
def test_bash_repassa_codigo_remoto(env_ssh):
    assert run(["bash", "-c", f"source {LIB}/ssh.sh; remoto ssh-teste 'exit 7'"], env=env_ssh).returncode == 7

@pytest.mark.integracao
def test_host_desconhecido_recusado(env_ssh_known_hosts_vazio):
    r = run(["bash", "-c", f"source {LIB}/ssh.sh; remoto ssh-teste true"], env=env_ssh_known_hosts_vazio)
    assert r.returncode != 0 and "Host key verification failed" in r.stderr

@pytest.mark.integracao
def test_python_remoto_e_arquivos(env_ssh, tmp_path):
    assert ssh_util.remoto("ssh-teste", "echo oi").saida.strip() == "oi"
    with pytest.raises(ssh_util.ErroRemoto): ssh_util.remoto("ssh-teste", "exit 2")
    ssh_util.enviar("ssh-teste", tmp_path / "a.txt", "/tmp/a.txt"); ssh_util.receber("ssh-teste", "/tmp/a.txt", tmp_path / "b.txt")
    assert (tmp_path / "b.txt").read_text() == (tmp_path / "a.txt").read_text()

@pytest.mark.integracao
def test_python_host_desconhecido_recusado(env_ssh_known_hosts_vazio): ...
```

- [ ] **Step 2: Rodar** → FAIL · **Step 3: Implementar** · **Step 4: Rodar** → PASS
- [ ] **Step 5: Commit** — `feat: bibliotecas de apoio SSH e cadastro de alvo`

---

### Task 9: Vigia de rotinas

**Files:**
- Create: `plugins/rotinas_core/api_airflow.py`, `plugins/rotinas_core/vigia.py`, `dags/vigia_rotinas.py`
- Test: `tests/test_vigia.py`, `tests/test_api_airflow.py`

**Interfaces:**
- Consumes: `carregar_rotinas`, `Rotina` (Task 2), `proximas`/croniter (Task 3), `enviar`, `montar_aviso_vigia` (Task 5).
- Produces:
  - `@dataclass class EstadoDag: pausado: bool; ultima_execucao_ok: datetime | None; existe: bool`
  - `class ClienteAirflow(api_url: str, usuario: str, senha: str)`: obtém JWT (`POST /auth/token`), `estados(dag_ids: Iterable[str]) -> dict[str, EstadoDag]` (`GET /api/v2/dags/{id}` + `GET /api/v2/dags/{id}/dagRuns?state=success&order_by=-logical_date&limit=1`), `erros_importacao() -> list[str]` (`GET /api/v2/importErrors`, retorna filenames + mensagem), `definir_pausa(dag_id: str, pausado: bool) -> None` (`PATCH /api/v2/dags/{id}`). Reautentica uma vez em 401.
  - `@dataclass(frozen=True) class Problema: chave: str; mensagem: str` — chaves estáveis: `"importacao:<arquivo>"`, `"yaml:<arquivo>"`, `"atraso:<nome>"`, `"divergencia:<nome>"`.
  - `avaliar(rotinas: list[Rotina], erros_yaml: dict[str, str], erros_importacao: list[str], estados: dict[str, EstadoDag], agora: datetime) -> list[Problema]`.
    - atraso: rotina ativa, não pausada, cuja execução prevista mais recente `p` (último disparo do cron ≤ `agora - tolerância`) não tem sucesso com `ultima_execucao_ok >= p`; tolerância = `timeout_min + tentativas * intervalo_tentativa_min` minutos (+ 5 min de margem do scheduler). Rotina sem nenhum disparo previsto desde a criação do DAG não gera atraso.
    - divergência: `ativa != (not pausado)`; DAG inexistente para rotina válida conta como problema de importação, não divergência.
  - `comparar(anteriores: set[str], atuais: list[Problema]) -> tuple[list[Problema], list[str]]` → `(novos, chaves_resolvidas)`.
  - DAG `vigia_rotinas`: `schedule="*/15 * * * *"`, `catchup=False`, `max_active_runs=1`, tag `["sistema"]`; estado anterior guardado na Variable `vigia_estado` (JSON `{"chaves": [...]}`); envia `montar_aviso_vigia` só se houver novos ou resolvidos.

- [ ] **Step 1: Testes de `avaliar`/`comparar`** (tudo com datas fixas em Manaus)

```python
AGORA = datetime(2026, 11, 10, 12, 0, tzinfo=MAO)

def test_sem_problemas(): assert avaliar([diaria_2h], {}, [], {"r": EstadoDag(False, AGORA.replace(hour=2, minute=1), True)}, AGORA) == []

def test_atraso_quando_ultima_ok_antes_do_previsto():
    p = avaliar([diaria_2h], {}, [], {"r": EstadoDag(False, AGORA - timedelta(days=1, hours=10), True)}, AGORA)
    assert [x.chave for x in p] == ["atraso:r"]

def test_sem_atraso_dentro_da_tolerancia():
    agora = AGORA.replace(hour=2, minute=30)  # timeout 60 → ainda tolerado
    assert avaliar([diaria_2h], {}, [], {"r": EstadoDag(False, None, True)}, agora) == []

def test_pausada_inativa_nao_gera_atraso_nem_divergencia(): ...
def test_divergencia_ativa_mas_pausada(): ...  # chave "divergencia:r"
def test_erros_yaml_e_importacao(): ...        # chaves "yaml:b.yaml", "importacao:dags/x.py"
def test_comparar():
    novos, resolvidos = comparar({"atraso:r", "yaml:b.yaml"}, [Problema("atraso:r", "..."), Problema("divergencia:s", "...")])
    assert [p.chave for p in novos] == ["divergencia:s"] and resolvidos == ["yaml:b.yaml"]
```

- [ ] **Step 2: Testes de `ClienteAirflow`** com `httpx.MockTransport` (token obtido, header `Authorization: Bearer`, reautenticação em 401, mapeamento para `EstadoDag`) + um `@integracao` contra o Airflow do compose (`estados(["vigia_rotinas"])` retorna `existe=True`).
- [ ] **Step 3: Rodar** → FAIL · **Step 4: Implementar** · **Step 5: Rodar** → PASS
- [ ] **Step 6: Verificar no ambiente** — quebrar um YAML em `dados-dev/rotinas/`, disparar `vigia_rotinas`, conferir 1 e-mail no Mailpit; disparar de novo, nenhum e-mail novo; consertar o YAML, disparar, e-mail de "resolvido".
- [ ] **Step 7: Commit** — `feat: vigia de rotinas que falharam em rodar`

---

### Task 10: Repositório de rotinas (gravação atômica, Git, auditoria)

**Files:**
- Create: `plugins/rotinas_core/armazenamento.py`
- Test: `tests/test_armazenamento.py`

**Interfaces:**
- Consumes: `validar`, `Rotina`, `RotinaInvalida`, `carregar_rotinas` (Task 2).
- Produces: `class RepositorioRotinas(dados_dir: Path)`:
  - `listar() -> tuple[list[Rotina], dict[str, str]]`
  - `obter(nome: str) -> Rotina | None`
  - `scripts_existentes() -> list[str]` (relativos a `scripts/`)
  - `criar(dados: dict, script: ArquivoEnviado | None, usuario: str) -> Rotina`
  - `atualizar(nome: str, dados: dict, script: ArquivoEnviado | None, usuario: str) -> Rotina` (nome imutável: `dados["nome"]` diferente → `RotinaInvalida({"nome": "Não é possível renomear uma rotina"})`)
  - `definir_ativa(nome: str, ativa: bool, usuario: str) -> Rotina`
  - `excluir(nome: str, usuario: str) -> None`
  - `@dataclass class ArquivoEnviado: nome_arquivo: str; conteudo: bytes`
  - Regras: script enviado vai para `scripts/rotinas/<nome>/<nome_arquivo saneado>`; `> 1 MB` → erro `"O script excede 1 MB"`; não decodifica como UTF-8 ou contém byte nulo → `"O arquivo enviado não parece ser um script de texto"`; não começa com `#!` → `"O script precisa começar com #! (ex.: #!/bin/bash)"`; CRLF → LF; `chmod 750`. `criado_por` preservado na edição; `atualizado_em` = agora (ISO, Manaus). Gravação: arquivo temporário no mesmo diretório + `os.replace`. Lock exclusivo (`fcntl.flock` em `dados_dir/.lock`) em toda operação de escrita. Cada operação faz `git add -A && git commit --author "<usuario> <usuario@airflow>" -m "<ação> rotina <nome>"` (ações: `Cria`, `Atualiza`, `Ativa`, `Desativa`, `Exclui`) e acrescenta linha JSON em `dados_dir/auditoria.log` (`{"quando", "usuario", "acao", "rotina"}`), arquivo listado no `.gitignore` do diretório de dados. `excluir` remove o script só se nenhuma outra rotina o referencia.

- [ ] **Step 1: Testes** (`dados_dir` em `tmp_path` com `git init`)

```python
def test_criar_grava_yaml_script_e_commit(repo):
    r = repo.criar({"nome": "rotina_a", "agendamento": "@daily"}, ArquivoEnviado("a.sh", b"#!/bin/bash\necho oi\n"), "joao")
    assert r.script == "rotinas/rotina_a/a.sh" and r.criado_por == "joao"
    assert (repo.dados_dir / "rotinas/rotina_a.yaml").exists()
    assert git_log(repo) [0] == ("joao", "Cria rotina rotina_a")

def test_criar_nome_existente_nao_sobrescreve(repo_com_a):
    with pytest.raises(RotinaInvalida) as e:
        repo_com_a.criar({"nome": "rotina_a", "agendamento": "@hourly"}, ArquivoEnviado("b.sh", b"#!/bin/bash\n"), "maria")
    assert e.value.erros["nome"] == "Já existe uma rotina com esse nome"
    assert repo_com_a.obter("rotina_a").agendamento == "@daily"

def test_crlf_vira_lf(repo):
    repo.criar({...}, ArquivoEnviado("a.sh", b"#!/bin/bash\r\necho oi\r\n"), "joao")
    assert b"\r" not in (repo.dados_dir / "scripts/rotinas/rotina_a/a.sh").read_bytes()

@pytest.mark.parametrize("conteudo,msg", [
    (b"echo sem shebang\n", "precisa começar com #!"),
    (b"#!/bin/bash\n\x00\x01", "não parece ser um script de texto"),
    (b"#!/bin/bash\n" + b"x" * (1024 * 1024), "excede 1 MB"),
])
def test_script_recusado(repo, conteudo, msg): ...

def test_validacao_falha_nao_deixa_arquivos_nem_commit(repo): ...
def test_atualizar_sem_script_mantem_o_atual_e_preserva_criado_por(repo_com_a): ...
def test_renomear_recusado(repo_com_a): ...
def test_definir_ativa_commit_desativa(repo_com_a): ...
def test_excluir_remove_yaml_e_script_nao_compartilhado(repo_com_a): ...
def test_excluir_preserva_script_compartilhado(repo): ...
def test_auditoria_registra_cada_operacao(repo): ...
def test_nome_de_arquivo_enviado_saneado(repo):  # "../../x.sh" → "x.sh"
```

- [ ] **Step 2: Rodar** → FAIL · **Step 3: Implementar** · **Step 4: Rodar** → PASS
- [ ] **Step 5: Commit** — `feat: repositório de rotinas com Git e auditoria`

---

### Task 11: Plugin web "Rotinas"

**Files:**
- Create: `plugins/rotinas_web/__init__.py`, `plugins/rotinas_web/app.py`, `plugins/rotinas_web/seguranca.py`, `plugins/rotinas_web/templates/{base,lista,formulario,confirmar_exclusao}.html`
- Test: `tests/test_plugin_web.py`

**Interfaces:**
- Consumes: `RepositorioRotinas`, `ArquivoEnviado` (Task 10), `RotinaInvalida`, `Rotina` (Task 2), `descrever`, `preset_para_cron`, `cron_para_preset`, `proximas` (Task 3), `ClienteAirflow.definir_pausa`, `ClienteAirflow.estados` (Task 9), `carregar_config`.
- Produces:
  - `class RotinasPlugin(AirflowPlugin)`: `name="rotinas"`, `fastapi_apps=[{"app": app, "url_prefix": "/rotinas-app", "name": "Rotinas"}]`, `external_views=[{"name": "Rotinas", "href": "/rotinas-app/", "destination": "nav", "url_route": "rotinas"}]` (nomes de chave conforme a versão 3.1.x pinada).
  - `exigir_admin(request) -> str` (dependência FastAPI; devolve o nome de usuário; 401 sem sessão, 403 sem papel Admin). Usa o mecanismo de autenticação do Airflow (token JWT do usuário logado, via dependência de segurança da API do Airflow / auth manager FAB).
  - `verificar_origem(request)` — em POST, `Origin`/`Referer` deve ser o próprio host; senão 403 (defesa contra CSRF, já que a sessão é por cookie).
  - Rotas (todas com `exigir_admin`): `GET /` lista; `GET /nova`; `POST /nova`; `GET /{nome}/editar`; `POST /{nome}/editar`; `POST /{nome}/ativa` (form `ativa=true|false`); `GET /{nome}/excluir`; `POST /{nome}/excluir`; `GET /api/proximas?agendamento=...` (JSON com as 3 próximas, para o formulário atualizar ao vivo).
  - Ativar/desativar: `repo.definir_ativa` e depois `cliente.definir_pausa(nome, not ativa)`; se a API falhar, a tela mostra "Rotina salva, mas não foi possível aplicar a pausa no Airflow agora; a vigia apontará a divergência".
  - Formulário: campos do spec §8; horário por preset (tipo, hora, minuto, dia) ou cron avançado; segredos como linhas dinâmicas (nome → `variavel` ou `conexao`+`campo`); escolha entre upload e script existente; erros de `RotinaInvalida.erros` ao lado de cada campo; valores preenchidos preservados após erro.
  - Lista: nome, descrição, `descrever(agendamento)`, ativa, status/data da última execução (`ClienteAirflow.estados`), próxima execução, link `/dags/{nome}`. Rotinas com YAML inválido aparecem em destaque com a mensagem de erro.

- [ ] **Step 1: Spike de autenticação (descartável, sem testes)** — com o ambiente no ar, montar uma rota mínima protegida e confirmar no navegador: (a) logado como Admin, o menu "Rotinas" aparece e a rota devolve o usuário; (b) logado como Viewer, 403; (c) sem login, 401. Registrar no topo de `seguranca.py`, num comentário, qual mecanismo do Airflow 3.1.x foi usado. Se a view embutida não repassar o token, servir a página em nova aba (`destination` que abre link) mantendo `exigir_admin`.
- [ ] **Step 2: Testes** (`TestClient`; `exigir_admin` sobrescrito por `app.dependency_overrides`; `RepositorioRotinas` real em `tmp_path`; `ClienteAirflow` fake)

```python
def test_rotas_exigem_admin(cliente_sem_admin):
    for metodo, url in [("get", "/"), ("get", "/nova"), ("post", "/nova"), ("post", "/x/ativa"), ("post", "/x/excluir")]:
        assert getattr(cliente_sem_admin, metodo)(url).status_code in (401, 403)

def test_post_de_outra_origem_recusado(cliente_admin):
    r = cliente_admin.post("/nova", data={...}, headers={"Origin": "http://malicioso"})
    assert r.status_code == 403

def test_criar_por_preset(cliente_admin, repo):
    r = cliente_admin.post("/nova", data={"nome": "rotina_a", "tipo_horario": "semanal", "hora": "23", "minuto": "30",
        "dia_semana": "0", "tentativas": "1", "timeout_min": "60"},
        files={"script": ("a.sh", b"#!/bin/bash\necho oi\n")}, headers=MESMA_ORIGEM)
    assert r.status_code == 303 and repo.obter("rotina_a").agendamento == "30 23 * * 0"

def test_erro_de_validacao_mostra_mensagem_e_preserva_campos(cliente_admin):
    r = cliente_admin.post("/nova", data={"nome": "X", ...}, files=..., headers=MESMA_ORIGEM)
    assert r.status_code == 422 and "nome" in r.text and 'value="X"' in r.text

def test_desativar_pausa_no_airflow(cliente_admin, repo_com_a, airflow_fake):
    cliente_admin.post("/rotina_a/ativa", data={"ativa": "false"}, headers=MESMA_ORIGEM)
    assert airflow_fake.pausas == [("rotina_a", True)] and repo_com_a.obter("rotina_a").ativa is False

def test_desativar_com_api_fora_avisa(cliente_admin, repo_com_a, airflow_quebrado): ...  # texto "a vigia apontará a divergência"
def test_lista_mostra_descricao_do_horario_e_yaml_invalido(cliente_admin, ...): ...  # "Diário às 02:00"; mensagem de erro do YAML
def test_editar_preenche_preset(cliente_admin, repo_com_a): ...
def test_excluir_pede_confirmacao_e_remove(cliente_admin, repo_com_a): ...
def test_api_proximas(cliente_admin):
    assert len(cliente_admin.get("/api/proximas", params={"agendamento": "0 2 * * *"}).json()["proximas"]) == 3
```

- [ ] **Step 3: Rodar** → FAIL · **Step 4: Implementar** (Jinja2, HTML simples sem build de front-end, CSS leve inline em `base.html`; todos os textos em português) · **Step 5: Rodar** → PASS
- [ ] **Step 6: Verificar no navegador** — criar rotina pelo formulário com upload, vê-la aparecer na lista do Airflow em ~30 s, disparar, editar o horário (próximas execuções atualizam ao vivo), desativar (DAG pausa), excluir; conferir `git log` em `dados-dev/` com autor correto.
- [ ] **Step 7: Commit** — `feat: plugin web para gerenciar rotinas`

---

### Task 12: Rotinas de exemplo e homologação ponta a ponta

**Files:**
- Create: `scripts_base/exemplos/scripts/{backup_banco_airflow.sh,verifica_servicos_http.py,backup_etc_servidor_teste.sh,exemplo_falha_proposital.sh}`, `scripts_base/exemplos/rotinas/*.yaml` (um por script), `scripts_base/instalar_exemplos.sh`
- Modify: `instalar.sh` (oferece instalar exemplos)
- Test: `tests/test_exemplos.py`

**Interfaces:**
- Consumes: tudo acima; `ssh.sh` (Task 8); variáveis `BACKUPS_DIR`, `ROTINA_EXECUCAO`.
- Produces (comportamento, spec §10):
  - `backup_banco_airflow` — diário 01:00; `pg_dump` do banco do Airflow (credenciais via `segredos` → Connection `postgres_airflow`, cadastrada pelo `airflow-init`) para `$BACKUPS_DIR/airflow-db/airflow-<data>.sql.gz`, mantém os 7 últimos (arg 1, padrão 7).
  - `verifica_servicos_http` — a cada 30 min; args = URLs; falha (código 1) listando as que não responderam 200 em 10 s.
  - `backup_etc_servidor_teste` — diário 02:00; args `HOST [N=7]`; via `remoto`, `tar czf` do `/etc` (usuário `airflow-svc` com `sudo tar` liberado no `ssh-teste`) e `copiar_de` para `$BACKUPS_DIR/etc-<HOST>/`; mantém N.
  - `exemplo_falha_proposital` — `ativa: false`, `tentativas: 1`, `intervalo_tentativa_min: 1`; escreve "Falha proposital para demonstração" e sai com 1.
  - Todos os bash com `set -euo pipefail`.
  - `instalar_exemplos.sh` copia scripts e YAMLs para o diretório de dados e faz commit "Instala rotinas de exemplo"; não sobrescreve rotinas existentes.

- [ ] **Step 1: Testes**

```python
def test_yamls_de_exemplo_sao_validos():
    validas, erros = carregar_rotinas(EXEMPLOS / "rotinas", EXEMPLOS / "scripts")
    assert erros == {} and len(validas) == 4

@pytest.mark.integracao
def test_backup_etc_servidor_teste_ponta_a_ponta(env_ssh, tmp_path):
    env = {**env_ssh, "BACKUPS_DIR": str(tmp_path)}
    executar(EXEMPLOS / "scripts/backup_etc_servidor_teste.sh", ["ssh-teste", "2"], env, 120, print)
    executar(..., ["ssh-teste", "2"], ...); executar(..., ["ssh-teste", "2"], ...)
    assert len(list((tmp_path / "etc-ssh-teste").glob("*.tar.gz"))) == 2

@pytest.mark.integracao
def test_verifica_servicos_http_falha_com_url_fora():
    with pytest.raises(CodigoSaidaNaoZero):
        executar(EXEMPLOS / "scripts/verifica_servicos_http.py", ["http://airflow-apiserver:8080/api/v2/monitor/health", "http://nao-existe.invalid"], {}, 60, print)

def test_falha_proposital_sai_com_1(): ...
@pytest.mark.integracao
def test_backup_banco_airflow_gera_arquivo(...): ...
```

- [ ] **Step 2: Rodar** → FAIL · **Step 3: Implementar** · **Step 4: Rodar** `pytest -v` (suíte inteira, com integração) → PASS
- [ ] **Step 5: Homologação manual** — executar o roteiro do spec §11 de ponta a ponta no ambiente `--profile teste`, anotando resultado de cada item em `docs/homologacao.md` (criado na Task 13; aqui só registrar os resultados num rascunho).
- [ ] **Step 6: Commit** — `feat: rotinas de exemplo`

---

### Task 13: Documentação e roteiro da instrução

**Files:**
- Create: `README.md`, `docs/instalacao.md`, `docs/preparar-alvo.md`, `docs/criar-rotinas.md`, `docs/operacao.md`, `docs/homologacao.md`, `docs/instrucao.md`

**Interfaces:**
- Consumes: comandos, variáveis e telas reais das Tasks 1–12 (os documentos devem citar nomes exatamente como implementados).
- Produces (conteúdo mínimo, spec §12):
  - `README.md` — o que é, arquitetura em 1 diagrama, links para os demais.
  - `instalacao.md` — requisitos (ponto de partida 4 vCPU / 8 GB / 50 GB; Ubuntu 24.04), instalar Docker, `./instalar.sh`, `docker compose up -d`, primeiro login, criar usuários Admin/Viewer, cadastrar Connection `ssh_padrao` (`login` = `airflow-svc`, `extra` = `{"private_key": "..."}`), configurar SMTP, regra de firewall da porta do painel, **procedimento offline** (`docker save` / `docker load`), proxy (`HTTP_PROXY` no build), `DOCKER_SUBNET`.
  - `preparar-alvo.md` — VM Linux (usuário `airflow-svc`, `authorized_keys`, exemplo de sudoers restrito) e equipamento de rede (usuário local de privilégio mínimo); `cadastrar_alvo.sh` e conferência da impressão digital.
  - `criar-rotinas.md` — passo a passo pela tela (com capturas de tela), referência do YAML (todos os campos e padrões), guia de escrita de script (`set -euo pipefail`, uso de `remoto`/`copiar_de` e `ssh_util`, segredos por variável de ambiente, mensagens no log, idempotência, nada de senha no script).
  - `operacao.md` — painel, logs, *Trigger*, o que fazer com cada aviso da vigia, ativar/desativar só pela tela, histórico no Git dos dados (`git log`, voltar versão), backup/restauração (banco, diretório de dados, **chave Fernet**), atualização do Airflow, recomendações de produção (HTTPS, monitoramento externo do `/api/v2/monitor/health`, backup fora da VM, LDAP).
  - `homologacao.md` — roteiro do spec §11 em formato de checklist com coluna de resultado preenchida com o que foi executado na Task 12.
  - `instrucao.md` — roteiro de aula (~1h30): motivação, demonstração com as 4 rotinas de exemplo, exercício guiado de criar uma rotina com SSH, leitura de log de falha, dúvidas.

- [ ] **Step 1: Escrever os documentos**
- [ ] **Step 2: Verificar** — seguir `instalacao.md` do zero numa VM/máquina limpa (ou `docker compose down -v` + diretório de dados novo) até ver as rotinas de exemplo rodando; corrigir qualquer passo que divergir.
- [ ] **Step 3: Commit** — `docs: manuais de instalação, uso, operação e instrução`
