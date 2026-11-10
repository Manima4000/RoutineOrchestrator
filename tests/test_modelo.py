import pytest

from rotinas_core.modelo import RefSegredo, Rotina, RotinaInvalida, carregar_rotinas, validar

BASE = {"nome": "rotina_a", "agendamento": "0 2 * * *", "script": "a.sh"}


@pytest.fixture
def tmp_scripts(tmp_path):
    d = tmp_path / "scripts"
    d.mkdir()
    (d / "a.sh").write_text("echo oi\n")
    return d


def test_valida_minimo_aplica_padroes(tmp_scripts):
    r = validar(dict(BASE), tmp_scripts)
    assert (r.ativa, r.tentativas, r.intervalo_tentativa_min, r.timeout_min, r.avisar_falha) == (True, 1, 5, 60, True)
    assert r.argumentos == () and r.segredos == {} and r.emails_aviso == ()
    assert r.criado_por is None and r.atualizado_em is None


@pytest.mark.parametrize("campo,valor,msg", [
    ("nome", "Ab", "nome"), ("nome", "com-hifen", "nome"),
    ("agendamento", "99 * * * *", "agendamento"),
    ("script", "../fora.sh", "script"), ("script", "/etc/passwd", "script"),
    ("script", "nao_existe.sh", "script"),
    ("tentativas", -1, "tentativas"), ("tentativas", True, "tentativas"),
    ("timeout_min", 0, "timeout_min"), ("intervalo_tentativa_min", 0, "intervalo_tentativa_min"),
    ("ativa", "sim", "ativa"), ("argumentos", "x", "argumentos"),
    ("emails_aviso", "a@b.c", "emails_aviso"), ("typo", 1, "campos"),
])
def test_campo_invalido(tmp_scripts, campo, valor, msg):
    with pytest.raises(RotinaInvalida) as e:
        validar({**BASE, campo: valor}, tmp_scripts)
    assert msg in e.value.erros


def test_varios_erros_de_uma_vez(tmp_scripts):
    with pytest.raises(RotinaInvalida) as e:
        validar({"nome": "X", "agendamento": "ruim", "script": "a.sh"}, tmp_scripts)
    assert {"nome", "agendamento"} <= e.value.erros.keys()


def test_obrigatorios_ausentes(tmp_scripts):
    with pytest.raises(RotinaInvalida) as e:
        validar({}, tmp_scripts)
    assert {"nome", "agendamento", "script"} <= e.value.erros.keys()


@pytest.mark.parametrize("cron", ["@hourly", "@daily", "@weekly", "@monthly", "*/5 * * * *"])
def test_agendamentos_validos(tmp_scripts, cron):
    assert validar({**BASE, "agendamento": cron}, tmp_scripts).agendamento == cron


def test_segredo_nome_invalido_e_ref_incompleta(tmp_scripts):
    with pytest.raises(RotinaInvalida) as e:
        validar({**BASE, "segredos": {"minusculo": {"variavel": "v"}, "OK": {"conexao": "c"}}}, tmp_scripts)
    assert "segredos" in e.value.erros


@pytest.mark.parametrize("ref", [
    {"variavel": "v", "conexao": "c", "campo": "login"},
    {"conexao": "c", "campo": "outro"},
    {}, "texto",
])
def test_segredo_ref_invalida(tmp_scripts, ref):
    with pytest.raises(RotinaInvalida) as e:
        validar({**BASE, "segredos": {"OK": ref}}, tmp_scripts)
    assert "segredos" in e.value.erros


def test_segredos_validos_e_roundtrip(tmp_scripts):
    dados = {
        **BASE, "descricao": "d", "argumentos": ["-x", "1"], "tentativas": 0,
        "emails_aviso": ["a@b.c"], "criado_por": "admin", "atualizado_em": "2026-01-01T00:00:00",
        "segredos": {"TOKEN": {"variavel": "v"}, "SENHA": {"conexao": "c", "campo": "password"}},
    }
    r = validar(dados, tmp_scripts)
    assert r.segredos == {"TOKEN": RefSegredo(variavel="v"), "SENHA": RefSegredo(conexao="c", campo="password")}
    assert r.argumentos == ("-x", "1") and r.tentativas == 0
    d = r.para_dict()
    assert d["segredos"] == {"TOKEN": {"variavel": "v"}, "SENHA": {"conexao": "c", "campo": "password"}}
    assert d["argumentos"] == ["-x", "1"]
    assert validar(d, tmp_scripts) == r


def test_para_dict_omite_none(tmp_scripts):
    d = validar(dict(BASE), tmp_scripts).para_dict()
    assert "criado_por" not in d and "atualizado_em" not in d
    assert isinstance(validar(dict(BASE), tmp_scripts), Rotina)


def _yaml(d, nome, texto):
    (d / nome).write_text(texto)


def test_carregar_isola_arquivo_invalido(tmp_path, tmp_scripts):
    rd = tmp_path / "rotinas"
    rd.mkdir()
    _yaml(rd, "a.yaml", "nome: rotina_a\nagendamento: '@daily'\nscript: a.sh\n")
    _yaml(rd, "b.yaml", "nome: [quebrado\n")
    _yaml(rd, "c.yaml", "agendamento: '@daily'\nscript: a.sh\n")
    _yaml(rd, "d.yaml", "- lista\n")
    _yaml(rd, "ignorado.txt", "x")
    validas, erros = carregar_rotinas(rd, tmp_scripts)
    assert [r.nome for r in validas] == ["rotina_a"]
    assert set(erros) == {"b.yaml", "c.yaml", "d.yaml"}
    assert all(isinstance(m, str) and m for m in erros.values())


def test_carregar_ordena_por_nome(tmp_path, tmp_scripts):
    rd = tmp_path / "rotinas"
    rd.mkdir()
    _yaml(rd, "1.yaml", "nome: zzz\nagendamento: '@daily'\nscript: a.sh\n")
    _yaml(rd, "2.yaml", "nome: aaa\nagendamento: '@daily'\nscript: a.sh\n")
    validas, erros = carregar_rotinas(rd, tmp_scripts)
    assert [r.nome for r in validas] == ["aaa", "zzz"] and erros == {}


def test_nome_duplicado_entre_arquivos(tmp_path, tmp_scripts):
    rd = tmp_path / "rotinas"
    rd.mkdir()
    for f in ("x.yaml", "y.yaml"):
        _yaml(rd, f, "nome: dup\nagendamento: '@daily'\nscript: a.sh\n")
    validas, erros = carregar_rotinas(rd, tmp_scripts)
    assert validas == [] and set(erros) == {"x.yaml", "y.yaml"}
