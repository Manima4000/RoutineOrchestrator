import os
import shutil
import subprocess
from pathlib import Path

import pytest

import ssh_util

RAIZ = Path("/opt/airflow")
LIB = RAIZ / "scripts_base" / "lib"
CADASTRAR = RAIZ / "scripts_base" / "cadastrar_alvo.sh"
CHAVE_ORIGEM = RAIZ / "teste" / "ssh" / "chave_teste"

pytestmark = pytest.mark.integracao


def run(cmd, env=None, **kw):
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120, **kw)


@pytest.fixture
def env_ssh(tmp_path, monkeypatch):
    chave = tmp_path / "id"
    shutil.copy(CHAVE_ORIGEM, chave)
    chave.chmod(0o600)
    kh = tmp_path / "known_hosts"
    env = {**os.environ, "SSH_CHAVE": str(chave), "SSH_USUARIO": "airflow-svc", "SSH_KNOWN_HOSTS": str(kh)}
    r = run([str(CADASTRAR), "--sim", "ssh-teste"], env=env)
    assert r.returncode == 0, r.stderr
    for k in ("SSH_CHAVE", "SSH_USUARIO", "SSH_KNOWN_HOSTS"):
        monkeypatch.setenv(k, env[k])
    return env


@pytest.fixture
def env_ssh_known_hosts_vazio(env_ssh, tmp_path, monkeypatch):
    vazio = tmp_path / "vazio"
    vazio.write_text("")
    monkeypatch.setenv("SSH_KNOWN_HOSTS", str(vazio))
    return {**env_ssh, "SSH_KNOWN_HOSTS": str(vazio)}


def bash(script, env):
    return run(["bash", "-c", f"set -euo pipefail; source {LIB}/ssh.sh; {script}"], env=env)


def test_bash_remoto_ok(env_ssh):
    r = bash("remoto ssh-teste whoami", env_ssh)
    assert r.returncode == 0 and r.stdout.strip() == "airflow-svc"


def test_bash_repassa_codigo_remoto(env_ssh):
    r = run(["bash", "-c", f"source {LIB}/ssh.sh; remoto ssh-teste 'exit 7'"], env=env_ssh)
    assert r.returncode == 7


def test_bash_varios_argumentos_citados(env_ssh):
    r = bash('remoto ssh-teste touch "/tmp/a b" && remoto ssh-teste test -f "/tmp/a b"', env_ssh)
    assert r.returncode == 0, r.stderr
    r = bash("remoto ssh-teste printf '%s' '$(id)'", env_ssh)
    assert r.stdout == "$(id)"
    r = bash("remoto ssh-teste printf '%s' 'a;b c'", env_ssh)
    assert r.stdout == "a;b c"


def test_bash_sem_chave_mensagem_em_portugues(env_ssh):
    env = {k: v for k, v in env_ssh.items() if k != "SSH_CHAVE"}
    r = run(["bash", "-c", f"source {LIB}/ssh.sh; remoto ssh-teste true; echo continua"], env=env)
    assert "SSH_CHAVE" in r.stderr and "continua" in r.stdout  # não derruba o shell do chamador


def test_bash_copiar(env_ssh, tmp_path):
    (tmp_path / "a.txt").write_text("conteudo")
    r = bash(f"copiar_para ssh-teste {tmp_path}/a.txt /tmp/a_bash.txt && copiar_de ssh-teste /tmp/a_bash.txt {tmp_path}/b.txt", env_ssh)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "b.txt").read_text() == "conteudo"


def test_host_desconhecido_recusado(env_ssh_known_hosts_vazio):
    r = bash("remoto ssh-teste true", env_ssh_known_hosts_vazio)
    assert r.returncode != 0 and "Host key verification failed" in r.stderr


def test_cadastrar_alvo_idempotente(tmp_path):
    kh = tmp_path / "kh"
    env = {**os.environ, "SSH_KNOWN_HOSTS": str(kh)}
    for _ in range(2):
        r = run([str(CADASTRAR), "--sim", "ssh-teste"], env=env)
        assert r.returncode == 0, r.stderr
    assert len([l for l in kh.read_text().splitlines() if l.strip()]) >= 1
    n1 = len(kh.read_text().splitlines())
    run([str(CADASTRAR), "--sim", "ssh-teste"], env=env)
    assert len(kh.read_text().splitlines()) == n1
    assert "--sim" in run([str(CADASTRAR), "--help"], env=env).stdout


def test_cadastrar_alvo_nao_aceita_resposta_negativa(tmp_path):
    kh = tmp_path / "kh"
    env = {**os.environ, "SSH_KNOWN_HOSTS": str(kh)}
    r = run([str(CADASTRAR), "ssh-teste"], env=env, input="n\n")
    assert r.returncode != 0
    assert not kh.exists() or kh.read_text() == ""


def test_python_remoto_e_arquivos(env_ssh, tmp_path):
    assert ssh_util.remoto("ssh-teste", "echo oi").saida.strip() == "oi"
    with pytest.raises(ssh_util.ErroRemoto) as e:
        ssh_util.remoto("ssh-teste", "echo falhou >&2; exit 2")
    assert "ssh-teste" in str(e.value) and "2" in str(e.value) and "falhou" in str(e.value)
    assert ssh_util.remoto("ssh-teste", "exit 3", verificar=False).codigo == 3
    (tmp_path / "a.txt").write_text("olá")
    ssh_util.enviar("ssh-teste", tmp_path / "a.txt", "/tmp/a.txt")
    ssh_util.receber("ssh-teste", "/tmp/a.txt", tmp_path / "b.txt")
    assert (tmp_path / "b.txt").read_text() == "olá"


def test_resultado_imutavel():
    r = ssh_util.Resultado(0, "", "")
    with pytest.raises(Exception):
        r.codigo = 1


def test_python_host_desconhecido_recusado(env_ssh_known_hosts_vazio):
    with pytest.raises(Exception) as e:
        ssh_util.remoto("ssh-teste", "true")
    assert not isinstance(e.value, ssh_util.ErroRemoto)
