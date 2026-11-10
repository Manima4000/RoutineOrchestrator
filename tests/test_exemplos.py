import os
import shutil
import subprocess
from pathlib import Path

import pytest

from rotinas_core.execucao import CodigoSaidaNaoZero, executar
from rotinas_core.modelo import carregar_rotinas

from test_ssh_libs import env_ssh  # noqa: F401  (fixture)

RAIZ = Path("/opt/airflow")
EXEMPLOS = RAIZ / "scripts_base" / "exemplos"
INSTALAR = RAIZ / "scripts_base" / "instalar_exemplos.sh"


def test_yamls_de_exemplo_sao_validos(tmp_path):
    # os YAMLs apontam "exemplos/<arq>" relativo a scripts/ (como fica após instalar_exemplos.sh)
    shutil.copytree(EXEMPLOS / "scripts", tmp_path / "exemplos")
    validas, erros = carregar_rotinas(EXEMPLOS / "rotinas", tmp_path)
    assert erros == {}
    assert sorted(r.nome for r in validas) == [
        "backup_banco_airflow",
        "backup_etc_servidor_teste",
        "exemplo_falha_proposital",
        "verifica_servicos_http",
    ]
    por_nome = {r.nome: r for r in validas}
    assert por_nome["exemplo_falha_proposital"].ativa is False
    assert por_nome["verifica_servicos_http"].argumentos == ("http://airflow-apiserver:8080/api/v2/monitor/health",)


def test_scripts_bash_usam_modo_estrito():
    for s in (EXEMPLOS / "scripts").glob("*.sh"):
        assert "set -euo pipefail" in s.read_text(), s.name


def test_falha_proposital_sai_com_1():
    linhas = []
    with pytest.raises(CodigoSaidaNaoZero) as e:
        executar(EXEMPLOS / "scripts/exemplo_falha_proposital.sh", [], {}, 30, linhas.append)
    assert e.value.codigo == 1
    assert any("Falha proposital para demonstração" in l for l in linhas)


@pytest.mark.integracao
def test_backup_etc_servidor_teste_ponta_a_ponta(env_ssh, tmp_path):  # noqa: F811
    env = {**env_ssh, "BACKUPS_DIR": str(tmp_path), "ROTINA_EXECUCAO": "teste"}
    for _ in range(3):
        executar(EXEMPLOS / "scripts/backup_etc_servidor_teste.sh", ["ssh-teste", "2"], env, 120, print)
    arqs = list((tmp_path / "etc-ssh-teste").glob("*.tar.gz"))
    assert len(arqs) == 2
    assert all(a.stat().st_mode & 0o777 == 0o600 for a in arqs)


@pytest.mark.integracao
def test_verifica_servicos_http_ok_e_falha():
    url = "http://airflow-apiserver:8080/api/v2/monitor/health"
    executar(EXEMPLOS / "scripts/verifica_servicos_http.py", [url], {}, 60, print)
    linhas = []
    with pytest.raises(CodigoSaidaNaoZero):
        executar(EXEMPLOS / "scripts/verifica_servicos_http.py", [url, "http://nao-existe.invalid"], {}, 60, linhas.append)
    assert any("nao-existe.invalid" in l for l in linhas)
    assert "OK      " + url in [l.rstrip() for l in linhas]
    assert not any("FALHOU" in l and url in l for l in linhas)


@pytest.mark.integracao
def test_backup_banco_airflow_gera_arquivo_e_mantem_n(tmp_path):
    env = {
        "BACKUPS_DIR": str(tmp_path),
        "PGPASSWORD": os.environ["POSTGRES_PASSWORD"],
    }
    for _ in range(3):
        executar(EXEMPLOS / "scripts/backup_banco_airflow.sh", ["2"], env, 120, print)
    arqs = list((tmp_path / "airflow-db").glob("airflow-*.sql.gz"))
    assert len(arqs) == 2 and all(a.stat().st_size > 1000 for a in arqs)


def test_instalar_exemplos_idempotente_e_nao_sobrescreve(tmp_path):
    dados = tmp_path / "dados"
    (dados / "rotinas").mkdir(parents=True)
    (dados / "scripts").mkdir()
    subprocess.run(["git", "init", "-q", str(dados)], check=True)
    existente = dados / "rotinas" / "exemplo_falha_proposital.yaml"
    existente.write_text("nome: exemplo_falha_proposital\n# minha versão\n")
    env = {**os.environ, "DADOS_DIR": str(dados)}
    for _ in range(2):
        r = subprocess.run([str(INSTALAR)], env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    assert "# minha versão" in existente.read_text()
    assert (dados / "rotinas/backup_banco_airflow.yaml").exists()
    assert (dados / "scripts/exemplos/verifica_servicos_http.py").exists()
    log = subprocess.run(
        ["git", "-c", f"safe.directory={dados}", "-C", str(dados), "log", "--format=%s"],
        capture_output=True, text=True,
    ).stdout.split("\n")
    assert log.count("Instala rotinas de exemplo") == 1


@pytest.mark.integracao
def test_backup_banco_airflow_sem_senha_falha(tmp_path):
    with pytest.raises(CodigoSaidaNaoZero):
        executar(EXEMPLOS / "scripts/backup_banco_airflow.sh", [], {"BACKUPS_DIR": str(tmp_path)}, 60, print)
