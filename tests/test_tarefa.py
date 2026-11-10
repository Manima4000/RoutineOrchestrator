import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from rotinas_core import tarefa
from rotinas_core.config import Config
from rotinas_core.execucao import CodigoSaidaNaoZero, TempoEsgotado
from rotinas_core.modelo import RefSegredo, Rotina
from rotinas_core.tarefa import (
    ErroSegredo, FalhaRotina, _ao_falhar, _executar, chave_temporaria,
    montar_ambiente, resolver_segredos,
)


def _config(tmp_path, **extra) -> Config:
    base = dict(
        rotinas_dir=tmp_path / "rotinas", scripts_dir=tmp_path / "scripts", dados_dir=tmp_path,
        known_hosts=Path("/k/known_hosts"), lib_dir=Path("/opt/lib"), backups_dir=Path("/b"),
        smtp_host="smtp", smtp_porta=25, smtp_tls=False, smtp_usuario=None, smtp_senha=None,
        smtp_remetente="r@x", aviso_destinatarios=["geral@x"],
        api_url="http://x", api_usuario="u", api_senha="s", ui_url="http://ui",
    )
    base.update(extra)
    return Config(**base)


@pytest.fixture
def config(tmp_path):
    (tmp_path / "rotinas").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "a.sh").write_text("#!/bin/bash\n")
    return _config(tmp_path)


def _yaml(config, nome="minha_rotina", extra=""):
    (config.rotinas_dir / f"{nome}.yaml").write_text(
        f"nome: {nome}\nagendamento: '@daily'\nscript: a.sh\nargumentos: [um]\ntimeout_min: 2\n{extra}"
    )


@pytest.fixture
def rotina():
    return Rotina(nome="minha_rotina", agendamento="@daily", script="a.sh", argumentos=("um",))


def _falha_key(_):
    raise KeyError("x")


# ---------- segredos ----------

def test_resolver_segredos():
    refs = {"DB_SENHA": RefSegredo(variavel="senha_x"), "TOKEN": RefSegredo(conexao="api", campo="password"),
            "PORTA": RefSegredo(conexao="api", campo="port"), "EXTRA": RefSegredo(conexao="api", campo="extra")}
    conn = SimpleNamespace(password="t0k", login="u", host="h", port=1, schema="s", extra={"a": 1})
    r = resolver_segredos(refs, {"senha_x": "s3nha"}.__getitem__, lambda c: conn)
    assert r == {"DB_SENHA": "s3nha", "TOKEN": "t0k", "PORTA": "1", "EXTRA": '{"a": 1}'}


def test_segredo_variavel_inexistente_mensagem_clara():
    with pytest.raises(ErroSegredo, match="Segredo DB_SENHA: Variable 'senha_x' não encontrada"):
        resolver_segredos({"DB_SENHA": RefSegredo(variavel="senha_x")}, _falha_key, None)


def test_segredo_conexao_inexistente_mensagem_clara():
    with pytest.raises(ErroSegredo, match="Segredo T: Connection 'api' não encontrada"):
        resolver_segredos({"T": RefSegredo(conexao="api", campo="login")}, None, _falha_key)


def test_segredo_campo_vazio():
    conn = SimpleNamespace(password=None)
    with pytest.raises(ErroSegredo, match="Segredo T: campo 'password' da Connection 'api' está vazio"):
        resolver_segredos({"T": RefSegredo(conexao="api", campo="password")}, None, lambda c: conn)


# ---------- chave temporária ----------

def test_chave_temporaria_permissoes_e_remocao():
    with chave_temporaria("-----BEGIN KEY-----\n") as p:
        assert oct(p.stat().st_mode & 0o777) == "0o600"
        assert oct(p.parent.stat().st_mode & 0o777) == "0o700"
        assert p.read_text() == "-----BEGIN KEY-----\n"
    assert not p.exists() and not p.parent.exists()


def test_chave_removida_mesmo_com_excecao():
    with pytest.raises(RuntimeError):
        with chave_temporaria("k\n") as p:
            raise RuntimeError("boom")
    assert not p.exists() and not p.parent.exists()


def test_chave_temporaria_none():
    with chave_temporaria(None) as p:
        assert p is None


# ---------- ambiente ----------

def test_montar_ambiente_contem_variaveis_fixas(config, rotina):
    env = montar_ambiente(rotina, {"A": "1"}, Path("/tmp/k"), "airflow-svc", config, "run_1")
    assert env["SSH_CHAVE"] == "/tmp/k" and env["SSH_USUARIO"] == "airflow-svc"
    assert env["SSH_KNOWN_HOSTS"] == str(config.known_hosts) and env["A"] == "1"
    assert env["ROTINA_NOME"] == rotina.nome and str(config.lib_dir) in env["PYTHONPATH"]
    assert env["ROTINA_EXECUCAO"] == "run_1" and env["ROTINAS_LIB"] == str(config.lib_dir)
    assert env["BACKUPS_DIR"] == str(config.backups_dir)


def test_montar_ambiente_sem_ssh(config, rotina):
    env = montar_ambiente(rotina, {}, None, None, config, "r")
    assert "SSH_CHAVE" not in env and "SSH_USUARIO" not in env
    assert env["SSH_KNOWN_HOSTS"] == str(config.known_hosts)


# ---------- _executar ----------

class Chamadas:
    def __init__(self):
        self.ordem, self.mascarados, self.exec = [], [], None

    def mascarar(self, v):
        self.mascarados.append(v)
        self.ordem.append("mascarar")

    def executar_fn(self, script, argumentos, env, timeout_s, log):
        self.ordem.append("executar")
        self.exec = SimpleNamespace(script=script, argumentos=list(argumentos), env=dict(env),
                                    timeout_s=timeout_s, chave=env.get("SSH_CHAVE") and Path(env["SSH_CHAVE"]).read_text())
        log("linha 1")


CTX = {"ti": SimpleNamespace(dag_id="minha_rotina", run_id="run_1")}


def _rodar(config, c, variaveis=None, conexoes=None, ctx=CTX, **kw):
    variaveis, conexoes = variaveis or {}, conexoes or {}
    return _executar(
        "minha_rotina", ctx, config=config,
        obter_variavel=variaveis.__getitem__, obter_conexao=conexoes.__getitem__,
        mascarar=c.mascarar, executar_fn=kw.get("executar_fn", c.executar_fn),
    )


def test_segredos_nunca_nos_argumentos_e_mascarados_antes(config):
    _yaml(config, extra="segredos:\n  DB_SENHA: {variavel: v1}\n  TOKEN: {conexao: api, campo: password}\n")
    c = Chamadas()
    _rodar(config, c, {"v1": "s3nha"}, {"api": SimpleNamespace(password="t0k")})
    assert c.exec.argumentos == ["um"]
    assert "s3nha" not in " ".join(c.exec.argumentos) and "t0k" not in " ".join(c.exec.argumentos)
    assert c.exec.env["DB_SENHA"] == "s3nha" and c.exec.env["TOKEN"] == "t0k"
    assert sorted(c.mascarados) == ["s3nha", "t0k"]
    assert c.ordem == ["mascarar", "mascarar", "executar"]
    assert c.exec.timeout_s == 120
    assert c.exec.script == config.scripts_dir / "a.sh"
    assert c.exec.env["ROTINA_EXECUCAO"] == "run_1"


def test_chave_ssh_presente_durante_e_removida_depois(config):
    _yaml(config)
    c = Chamadas()
    conn = SimpleNamespace(login="svc", extra=json.dumps({"private_key": "CHAVE\n"}))
    _rodar(config, c, conexoes={"ssh_padrao": conn})
    assert c.exec.env["SSH_USUARIO"] == "svc" and c.exec.chave == "CHAVE\n"
    assert not Path(c.exec.env["SSH_CHAVE"]).exists()
    assert "CHAVE\n" in c.mascarados


def test_chave_ssh_extra_dict(config):
    _yaml(config)
    c = Chamadas()
    conn = SimpleNamespace(login="svc", extra={"private_key": "K\n"})
    _rodar(config, c, conexoes={"ssh_padrao": conn})
    assert c.exec.chave == "K\n"


def test_sem_ssh_padrao(config):
    _yaml(config)
    c = Chamadas()
    _rodar(config, c)
    assert "SSH_CHAVE" not in c.exec.env and "SSH_USUARIO" not in c.exec.env
    assert c.exec.env["SSH_KNOWN_HOSTS"] == str(config.known_hosts)


def test_rotina_inexistente(config):
    with pytest.raises(FalhaRotina, match="Rotina 'minha_rotina' não encontrada ou inválida"):
        _rodar(config, Chamadas())


def test_rotina_invalida_inclui_erro_do_arquivo(config):
    (config.rotinas_dir / "minha_rotina.yaml").write_text("nome: minha_rotina\nagendamento: xx\nscript: a.sh\n")
    with pytest.raises(FalhaRotina, match=r"não encontrada ou inválida: .*[Aa]gendamento"):
        _rodar(config, Chamadas())


def test_erro_execucao_vira_falha_rotina_com_ultimas_linhas(config):
    _yaml(config)
    original = CodigoSaidaNaoZero(3, "O script terminou com código de saída 3")

    def exec_falha(script, argumentos, env, timeout_s, log):
        for i in range(40):
            log(f"l{i}")
        raise original

    with pytest.raises(FalhaRotina) as ei:
        _rodar(config, Chamadas(), executar_fn=exec_falha)
    assert ei.value.mensagem == "O script terminou com código de saída 3"
    assert ei.value.ultimas_linhas == [f"l{i}" for i in range(10, 40)]
    assert ei.value.__cause__ is original


def test_erro_segredo_propaga_sem_executar(config):
    _yaml(config, extra="segredos:\n  X: {variavel: nao_existe}\n")
    c = Chamadas()
    with pytest.raises(ErroSegredo, match="Segredo X: Variable 'nao_existe' não encontrada"):
        _rodar(config, c)
    assert c.exec is None


# ---------- ao_falhar ----------

class Envio:
    def __init__(self, falha=False):
        self.chamadas, self.falha = [], falha

    def __call__(self, config, assunto, corpo, destinatarios):
        if self.falha:
            raise OSError("smtp fora")
        self.chamadas.append((assunto, corpo, list(destinatarios)))


def _ctx_falha(exc):
    return {"ti": SimpleNamespace(dag_id="minha_rotina", run_id="manual__2026-01-01T00:00:00+00:00"),
            "exception": exc}


def test_ao_falhar_envia_para_destinatarios_da_rotina(config):
    _yaml(config, extra="emails_aviso: [dono@x]\n")
    envio = Envio()
    exc = FalhaRotina("deu ruim", ["a", "b"])
    _ao_falhar(_ctx_falha(exc), config=config, enviar_fn=envio)
    assunto, corpo, dest = envio.chamadas[0]
    assert dest == ["dono@x"] and "minha_rotina" in assunto
    assert "deu ruim" in corpo and "a\nb" in corpo
    assert "http://ui/dags/minha_rotina/runs/manual__2026-01-01T00%3A00%3A00%2B00%3A00" in corpo


def test_ao_falhar_sem_emails_usa_padrao_da_config(config):
    _yaml(config)
    envio = Envio()
    _ao_falhar(_ctx_falha(FalhaRotina("x", [])), config=config, enviar_fn=envio)
    assert envio.chamadas[0][2] == ["geral@x"]


def test_ao_falhar_respeita_avisar_falha_false(config):
    _yaml(config, extra="avisar_falha: false\n")
    envio = Envio()
    _ao_falhar(_ctx_falha(FalhaRotina("x", [])), config=config, enviar_fn=envio)
    assert envio.chamadas == []


def test_ao_falhar_rotina_ilegivel_ainda_notifica_padrao(config):
    envio = Envio()
    _ao_falhar(_ctx_falha(ValueError("outro")), config=config, enviar_fn=envio)
    assunto, corpo, dest = envio.chamadas[0]
    assert dest == ["geral@x"] and "outro" in corpo


def test_ao_falhar_nunca_levanta(config, caplog):
    _yaml(config)
    with caplog.at_level(logging.ERROR):
        _ao_falhar(_ctx_falha(FalhaRotina("x", [])), config=config, enviar_fn=Envio(falha=True))
    assert "smtp fora" in caplog.text
    _ao_falhar({}, config=config, enviar_fn=Envio())  # contexto quebrado também não levanta


def test_tempo_esgotado_tambem_vira_falha(config):
    _yaml(config)

    def exec_falha(*a, **k):
        raise TempoEsgotado("Tempo limite de 2 min excedido")

    with pytest.raises(FalhaRotina, match="Tempo limite"):
        _rodar(config, Chamadas(), executar_fn=exec_falha)


# ---------- redação de segredos nas linhas guardadas ----------

def _exec_loga(*linhas, erro=None):
    def fn(script, argumentos, env, timeout_s, log):
        for l in linhas:
            log(l)
        if erro:
            raise erro
    return fn


def test_segredo_impresso_pelo_script_e_redigido(config):
    _yaml(config, extra="segredos:\n  DB_SENHA: {variavel: v1}\n")
    with pytest.raises(FalhaRotina) as ei:
        _rodar(config, Chamadas(), {"v1": "s3nha"},
               executar_fn=_exec_loga("senha=s3nha", "ok",
                                      erro=CodigoSaidaNaoZero(1, "falhou com s3nha")))
    assert ei.value.ultimas_linhas == ["senha=***", "ok"]
    assert "s3nha" not in ei.value.mensagem


def test_corpo_da_chave_e_redigido(config):
    _yaml(config)
    conn = SimpleNamespace(login="svc", extra={"private_key": "-----BEGIN KEY-----\nABCDEF\nGHIJKL\n-----END KEY-----\n"})
    with pytest.raises(FalhaRotina) as ei:
        _rodar(config, Chamadas(), conexoes={"ssh_padrao": conn},
               executar_fn=_exec_loga("-----BEGIN KEY-----", "ABCDEF", "x GHIJKL y", "-----END KEY-----",
                                      erro=CodigoSaidaNaoZero(1, "x")))
    assert ei.value.ultimas_linhas == ["-----BEGIN KEY-----", "***", "x *** y", "-----END KEY-----"]
