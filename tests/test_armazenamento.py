import json
import subprocess

import pytest
import yaml

from rotinas_core.armazenamento import ArquivoEnviado, ErroRepositorio, RepositorioRotinas
from rotinas_core.modelo import RotinaInvalida, carregar_rotinas

SCRIPT = ArquivoEnviado("a.sh", b"#!/bin/bash\necho oi\n")
A = {"nome": "rotina_a", "agendamento": "@daily"}


def git(repo, *args):
    return subprocess.run(
        ["git", "-c", f"safe.directory={repo.dados_dir}", *args],
        cwd=repo.dados_dir, capture_output=True, text=True, check=True,
    ).stdout


def git_log(repo):
    saida = git(repo, "log", "--format=%an|%s")
    return [tuple(l.split("|", 1)) for l in saida.splitlines()]


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "dados"
    d.mkdir()
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    subprocess.run(["git", "-C", str(d), "config", "user.name", "Teste"], check=True)
    subprocess.run(["git", "-C", str(d), "config", "user.email", "t@t"], check=True)
    return RepositorioRotinas(d)


@pytest.fixture
def repo_com_a(repo):
    repo.criar(dict(A), SCRIPT, "joao")
    return repo


def test_criar_grava_yaml_script_e_commit(repo):
    r = repo.criar(dict(A), SCRIPT, "joao")
    assert r.script == "rotinas/rotina_a/a.sh" and r.criado_por == "joao"
    assert (repo.dados_dir / "rotinas/rotina_a.yaml").exists()
    assert git_log(repo)[0] == ("joao", "Cria rotina rotina_a")
    assert (repo.dados_dir / "scripts/rotinas/rotina_a/a.sh").stat().st_mode & 0o777 == 0o750
    assert repo.obter("rotina_a") == r
    assert repo.scripts_existentes() == ["rotinas/rotina_a/a.sh"]


def test_yaml_gravado_volta_por_carregar_rotinas(repo):
    r = repo.criar({**A, "argumentos": ["x"], "segredos": {"TOKEN": {"variavel": "t"}}}, SCRIPT, "joao")
    validas, erros = carregar_rotinas(repo.dados_dir / "rotinas", repo.dados_dir / "scripts")
    assert erros == {} and validas == [r]
    assert isinstance(yaml.safe_load((repo.dados_dir / "rotinas/rotina_a.yaml").read_text())["atualizado_em"], str)
    assert r.atualizado_em.endswith("-04:00") and "." not in r.atualizado_em


def test_criar_nome_existente_nao_sobrescreve(repo_com_a):
    with pytest.raises(RotinaInvalida) as e:
        repo_com_a.criar({"nome": "rotina_a", "agendamento": "@hourly"}, ArquivoEnviado("b.sh", b"#!/bin/bash\n"), "maria")
    assert e.value.erros["nome"] == "Já existe uma rotina com esse nome"
    assert repo_com_a.obter("rotina_a").agendamento == "@daily"
    assert not (repo_com_a.dados_dir / "scripts/rotinas/rotina_a/b.sh").exists()


def test_crlf_vira_lf(repo):
    repo.criar(dict(A), ArquivoEnviado("a.sh", b"#!/bin/bash\r\necho oi\r\n"), "joao")
    assert b"\r" not in (repo.dados_dir / "scripts/rotinas/rotina_a/a.sh").read_bytes()


@pytest.mark.parametrize("conteudo,msg", [
    (b"echo sem shebang\n", "precisa começar com #!"),
    (b"#!/bin/bash\n\x00\x01", "não parece ser um script de texto"),
    (b"#!/bin/bash\n\xff\xfe", "não parece ser um script de texto"),
    (b"#!/bin/bash\n" + b"x" * (1024 * 1024), "excede 1 MB"),
])
def test_script_recusado(repo, conteudo, msg):
    with pytest.raises(RotinaInvalida) as e:
        repo.criar(dict(A), ArquivoEnviado("a.sh", conteudo), "joao")
    assert msg in e.value.erros["script"]
    assert not (repo.dados_dir / "scripts/rotinas/rotina_a").exists()
    assert git_log_vazio(repo)


def git_log_vazio(repo):
    r = subprocess.run(["git", "-c", f"safe.directory={repo.dados_dir}", "log"], cwd=repo.dados_dir, capture_output=True)
    return r.returncode != 0


def test_validacao_falha_nao_deixa_arquivos_nem_commit(repo):
    with pytest.raises(RotinaInvalida) as e:
        repo.criar({"nome": "rotina_a", "agendamento": "99 * * * *"}, SCRIPT, "joao")
    assert "agendamento" in e.value.erros
    assert not (repo.dados_dir / "rotinas/rotina_a.yaml").exists()
    assert not (repo.dados_dir / "scripts/rotinas/rotina_a").exists()
    assert git_log_vazio(repo)


def test_nome_invalido_nao_cria_pasta(repo):
    with pytest.raises(RotinaInvalida) as e:
        repo.criar({"nome": "../x", "agendamento": "@daily"}, SCRIPT, "joao")
    assert "nome" in e.value.erros
    assert not (repo.dados_dir / "scripts").exists() or not any((repo.dados_dir / "scripts").iterdir())


def test_criar_exige_script(repo):
    with pytest.raises(RotinaInvalida) as e:
        repo.criar(dict(A), None, "joao")
    assert e.value.erros == {"script": "Envie um script ou escolha um existente"}


def test_criar_com_script_existente(repo_com_a):
    r = repo_com_a.criar({"nome": "rotina_b", "agendamento": "@daily", "script": "rotinas/rotina_a/a.sh"}, None, "maria")
    assert r.script == "rotinas/rotina_a/a.sh"


def test_atualizar_sem_script_mantem_o_atual_e_preserva_criado_por(repo_com_a):
    r = repo_com_a.atualizar("rotina_a", {"nome": "rotina_a", "agendamento": "@hourly"}, None, "maria")
    assert r.script == "rotinas/rotina_a/a.sh" and r.agendamento == "@hourly"
    assert r.criado_por == "joao"
    assert git_log(repo_com_a)[0] == ("maria", "Atualiza rotina rotina_a")


def test_atualizar_com_novo_script(repo_com_a):
    r = repo_com_a.atualizar("rotina_a", dict(A), ArquivoEnviado("novo.sh", b"#!/bin/sh\n"), "maria")
    assert r.script == "rotinas/rotina_a/novo.sh"
    assert not (repo_com_a.dados_dir / "scripts/rotinas/rotina_a/a.sh").exists()


def test_atualizar_invalido_restaura_tudo(repo_com_a):
    antes = (repo_com_a.dados_dir / "rotinas/rotina_a.yaml").read_bytes()
    with pytest.raises(RotinaInvalida):
        repo_com_a.atualizar("rotina_a", {**A, "agendamento": "xx"}, ArquivoEnviado("a.sh", b"#!/bin/sh\nmudou\n"), "maria")
    assert (repo_com_a.dados_dir / "rotinas/rotina_a.yaml").read_bytes() == antes
    assert b"echo oi" in (repo_com_a.dados_dir / "scripts/rotinas/rotina_a/a.sh").read_bytes()
    assert len(git_log(repo_com_a)) == 1


def test_renomear_recusado(repo_com_a):
    with pytest.raises(RotinaInvalida) as e:
        repo_com_a.atualizar("rotina_a", {"nome": "rotina_z", "agendamento": "@daily"}, None, "maria")
    assert e.value.erros["nome"] == "Não é possível renomear uma rotina"


def test_definir_ativa_commit_desativa(repo_com_a):
    r = repo_com_a.definir_ativa("rotina_a", False, "maria")
    assert r.ativa is False and repo_com_a.obter("rotina_a").ativa is False
    assert git_log(repo_com_a)[0] == ("maria", "Desativa rotina rotina_a")
    repo_com_a.definir_ativa("rotina_a", True, "maria")
    assert git_log(repo_com_a)[0] == ("maria", "Ativa rotina rotina_a")


def test_definir_ativa_igual_e_noop(repo_com_a):
    commits = len(git_log(repo_com_a))
    linhas = (repo_com_a.dados_dir / "auditoria.log").read_text().splitlines()
    repo_com_a.definir_ativa("rotina_a", True, "maria")
    assert len(git_log(repo_com_a)) == commits
    assert (repo_com_a.dados_dir / "auditoria.log").read_text().splitlines() == linhas


def test_excluir_remove_yaml_e_script_nao_compartilhado(repo_com_a):
    repo_com_a.excluir("rotina_a", "maria")
    assert repo_com_a.obter("rotina_a") is None
    assert not (repo_com_a.dados_dir / "scripts/rotinas/rotina_a").exists()
    assert git_log(repo_com_a)[0] == ("maria", "Exclui rotina rotina_a")


def test_excluir_preserva_script_compartilhado(repo_com_a):
    repo_com_a.criar({"nome": "rotina_b", "agendamento": "@daily", "script": "rotinas/rotina_a/a.sh"}, None, "maria")
    repo_com_a.excluir("rotina_a", "maria")
    assert (repo_com_a.dados_dir / "scripts/rotinas/rotina_a/a.sh").exists()
    assert repo_com_a.obter("rotina_b") is not None


def test_auditoria_registra_cada_operacao(repo):
    repo.criar(dict(A), SCRIPT, "joao")
    repo.definir_ativa("rotina_a", False, "maria")
    repo.excluir("rotina_a", "ana")
    linhas = [json.loads(l) for l in (repo.dados_dir / "auditoria.log").read_text().splitlines()]
    assert [(l["usuario"], l["acao"], l["rotina"]) for l in linhas] == [
        ("joao", "Cria", "rotina_a"), ("maria", "Desativa", "rotina_a"), ("ana", "Exclui", "rotina_a")]
    assert all(l["quando"] for l in linhas)


def test_gitignore_idempotente_e_auditoria_fora_do_git(repo):
    repo.criar(dict(A), SCRIPT, "joao")
    repo.definir_ativa("rotina_a", False, "joao")
    linhas = (repo.dados_dir / ".gitignore").read_text().splitlines()
    assert linhas.count("auditoria.log") == 1 and linhas.count(".lock") == 1
    assert "auditoria.log" not in git(repo, "ls-files")


@pytest.mark.parametrize("enviado,esperado", [
    ("../../x.sh", "x.sh"), ("a b$c.sh", "a_b_c.sh"), ("C:\\temp\\y.sh", "y.sh"), ("çã.sh", "__.sh"),
])
def test_nome_de_arquivo_enviado_saneado(repo, enviado, esperado):
    r = repo.criar(dict(A), ArquivoEnviado(enviado, b"#!/bin/bash\n"), "joao")
    assert r.script == f"rotinas/rotina_a/{esperado}"


@pytest.mark.parametrize("nome", ["", "..", ".oculto.sh", "/"])
def test_nome_de_arquivo_invalido(repo, nome):
    with pytest.raises(RotinaInvalida) as e:
        repo.criar(dict(A), ArquivoEnviado(nome, b"#!/bin/bash\n"), "joao")
    assert "script" in e.value.erros


def test_erro_do_git_reverte_e_libera_lock(repo, monkeypatch):
    import fcntl
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(ErroRepositorio):
        repo.criar(dict(A), SCRIPT, "joao")
    monkeypatch.undo()
    assert not (repo.dados_dir / "rotinas/rotina_a.yaml").exists()
    with open(repo.dados_dir / ".lock", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _git_quebrado(repo, monkeypatch):
    def falha(*a, **k):
        raise ErroRepositorio("git falhou")
    monkeypatch.setattr(repo, "_versionar", falha)


def test_excluir_com_falha_no_git_restaura_script(repo_com_a, monkeypatch):
    p = repo_com_a.dados_dir / "scripts/rotinas/rotina_a/a.sh"
    antes = p.read_bytes()
    _git_quebrado(repo_com_a, monkeypatch)
    with pytest.raises(ErroRepositorio):
        repo_com_a.excluir("rotina_a", "maria")
    assert p.read_bytes() == antes
    assert repo_com_a.obter("rotina_a") is not None


def test_atualizar_trocando_script_com_falha_no_git_restaura(repo_com_a, monkeypatch):
    repo_com_a.criar({"nome": "rotina_c", "agendamento": "@daily"}, ArquivoEnviado("c.sh", b"#!/bin/sh\n"), "joao")
    p = repo_com_a.dados_dir / "scripts/rotinas/rotina_c/c.sh"
    antes = p.read_bytes()
    _git_quebrado(repo_com_a, monkeypatch)
    with pytest.raises(ErroRepositorio):
        repo_com_a.atualizar("rotina_c", {"nome": "rotina_c", "agendamento": "@daily", "script": "rotinas/rotina_a/a.sh"}, None, "maria")
    assert p.read_bytes() == antes
    assert repo_com_a.obter("rotina_c").script == "rotinas/rotina_c/c.sh"


def test_upload_nao_sobrescreve_script_de_outra_rotina_caso_a(repo_com_a):
    repo_com_a.criar({"nome": "rotina_b", "agendamento": "@daily", "script": "rotinas/rotina_a/a.sh"}, None, "maria")
    with pytest.raises(RotinaInvalida) as e:
        repo_com_a.atualizar("rotina_a", dict(A), ArquivoEnviado("a.sh", b"#!/bin/sh\nnovo\n"), "joao")
    assert e.value.erros["script"] == "O arquivo rotinas/rotina_a/a.sh é usado também pela rotina rotina_b; envie com outro nome"
    assert b"echo oi" in (repo_com_a.dados_dir / "scripts/rotinas/rotina_a/a.sh").read_bytes()


def test_upload_nao_sobrescreve_script_de_outra_rotina_caso_b(repo_com_a):
    repo_com_a.criar({"nome": "rotina_b", "agendamento": "@daily", "script": "rotinas/rotina_a/a.sh"}, None, "maria")
    repo_com_a.excluir("rotina_a", "joao")
    with pytest.raises(RotinaInvalida) as e:
        repo_com_a.criar(dict(A), ArquivoEnviado("a.sh", b"#!/bin/sh\nnovo\n"), "joao")
    assert "rotina_b" in e.value.erros["script"]
    assert b"echo oi" in (repo_com_a.dados_dir / "scripts/rotinas/rotina_a/a.sh").read_bytes()
