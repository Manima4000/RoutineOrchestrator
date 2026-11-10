import subprocess
from datetime import datetime, timezone
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from rotinas_core.api_airflow import ErroApiAirflow, EstadoDag
from rotinas_core.armazenamento import ArquivoEnviado, RepositorioRotinas
from rotinas_web import seguranca
from rotinas_web.app import app, obter_cliente, obter_repo
from rotinas_web.seguranca import exigir_admin

MESMA_ORIGEM = {"Origin": "http://testserver"}
SCRIPT = ArquivoEnviado("a.sh", b"#!/bin/bash\necho oi\n")
ARQ = {"script": ("a.sh", b"#!/bin/bash\necho oi\n")}
FORM_A = {"nome": "rotina_a", "tipo_horario": "semanal", "hora": "23", "minuto": "30",
          "dia_semana": "0", "tentativas": "1", "timeout_min": "60"}


class AirflowFake:
    def __init__(self):
        self.pausas = []
        self.quebrado = False
        self.dados = {}

    def estados(self, dag_ids):
        if self.quebrado:
            raise ErroApiAirflow("API fora do ar")
        return {i: self.dados.get(i, EstadoDag(False, None, True, False)) for i in dag_ids}

    def definir_pausa(self, dag_id, pausado):
        if self.quebrado:
            raise ErroApiAirflow("API fora do ar")
        self.pausas.append((dag_id, pausado))


def git_log(repo):
    saida = subprocess.run(["git", "log", "--format=%an|%s"], cwd=repo.dados_dir,
                           capture_output=True, text=True, check=True).stdout
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
    repo.criar({"nome": "rotina_a", "agendamento": "0 2 * * *"}, SCRIPT, "joao")
    return repo


@pytest.fixture
def airflow_fake():
    return AirflowFake()


@pytest.fixture
def airflow_quebrado(airflow_fake):
    airflow_fake.quebrado = True
    return airflow_fake


@pytest.fixture
def overrides(repo, airflow_fake):
    app.dependency_overrides = {obter_repo: lambda: repo, obter_cliente: lambda: airflow_fake}
    yield app.dependency_overrides
    app.dependency_overrides = {}


@pytest.fixture
def cliente_admin(overrides):
    overrides[exigir_admin] = lambda: "joao"
    return TestClient(app, follow_redirects=False)


def _usuario(nome, *papeis):
    return SimpleNamespace(get_name=lambda: nome, roles=[SimpleNamespace(name=p) for p in papeis])


@pytest.fixture
def cliente_sem_admin(overrides, monkeypatch):
    monkeypatch.setattr(seguranca, "_usuario_do_token", lambda request: _usuario("maria", "Viewer", "User"))
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def cliente_sem_login(overrides, monkeypatch):
    monkeypatch.setattr(seguranca, "_usuario_do_token", lambda request: None)
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def cliente_admin_real(overrides, monkeypatch):
    """exigir_admin de verdade, com o token resolvendo para um Admin."""
    monkeypatch.setattr(seguranca, "_usuario_do_token", lambda request: _usuario("chefe", "Admin"))
    return TestClient(app, follow_redirects=False)


def _todas_as_rotas():
    for rota in app.routes:
        for metodo in sorted(getattr(rota, "methods", None) or ()):
            if metodo in ("HEAD", "OPTIONS"):
                continue
            yield metodo.lower(), rota.path.replace("{nome}", "x")


# ---------- segurança ----------

def test_rotas_exigem_admin(cliente_sem_admin):
    for metodo, url in [("get", "/"), ("get", "/nova"), ("post", "/nova"), ("post", "/x/ativa"), ("post", "/x/excluir")]:
        assert getattr(cliente_sem_admin, metodo)(url, headers=MESMA_ORIGEM).status_code in (401, 403)


def test_toda_rota_do_app_responde_403_sem_papel_admin(cliente_sem_admin):
    rotas = list(_todas_as_rotas())
    assert len(rotas) >= 9
    for metodo, url in rotas:
        r = getattr(cliente_sem_admin, metodo)(url, headers=MESMA_ORIGEM)
        assert r.status_code == 403, (metodo, url, r.status_code)
        assert "administradores" in r.text


def test_toda_rota_do_app_responde_401_sem_sessao(cliente_sem_login):
    for metodo, url in _todas_as_rotas():
        assert getattr(cliente_sem_login, metodo)(url).status_code == 401, (metodo, url)


def test_sem_documentacao_automatica_exposta(cliente_sem_login):
    for url in ("/docs", "/redoc", "/openapi.json"):
        assert cliente_sem_login.get(url).status_code in (401, 404)


def test_usuario_logado_vira_autor_do_commit(cliente_admin_real, repo):
    assert "chefe" in cliente_admin_real.get("/").text
    r = cliente_admin_real.post("/nova", data=FORM_A, files=ARQ, headers=MESMA_ORIGEM)
    assert r.status_code == 303
    assert git_log(repo)[0] == ("chefe", "Cria rotina rotina_a")


def test_post_de_outra_origem_recusado(cliente_admin, repo):
    r = cliente_admin.post("/nova", data=FORM_A, files=ARQ, headers={"Origin": "http://malicioso"})
    assert r.status_code == 403 and repo.obter("rotina_a") is None


def test_post_sem_origin_nem_referer_recusado(cliente_admin, repo):
    assert cliente_admin.post("/nova", data=FORM_A, files=ARQ).status_code == 403
    assert cliente_admin.post("/nova", data=FORM_A, files=ARQ, headers={"Origin": "null"}).status_code == 403
    assert cliente_admin.post("/nova", data=FORM_A, files=ARQ,
                              headers={"Origin": "http://testserver:8081"}).status_code == 403
    assert repo.obter("rotina_a") is None


def test_post_com_referer_da_mesma_origem_aceito(cliente_admin, repo):
    r = cliente_admin.post("/nova", data=FORM_A, files=ARQ,
                           headers={"Referer": "http://testserver/rotinas-app/nova"})
    assert r.status_code == 303 and repo.obter("rotina_a") is not None


def test_referer_de_outro_host_recusado(cliente_admin, repo):
    r = cliente_admin.post("/nova", data=FORM_A, files=ARQ, headers={"Referer": "http://testserver.malicioso/x"})
    assert r.status_code == 403


# ---------- criar ----------

def test_criar_por_preset(cliente_admin, repo):
    r = cliente_admin.post("/nova", data={"nome": "rotina_a", "tipo_horario": "semanal", "hora": "23", "minuto": "30",
        "dia_semana": "0", "tentativas": "1", "timeout_min": "60"},
        files={"script": ("a.sh", b"#!/bin/bash\necho oi\n")}, headers=MESMA_ORIGEM)
    assert r.status_code == 303 and repo.obter("rotina_a").agendamento == "30 23 * * 0"
    assert r.headers["location"] == "/"
    rot = repo.obter("rotina_a")
    assert rot.ativa is True and rot.avisar_falha is True and rot.criado_por == "joao"


def test_criar_com_todos_os_campos(cliente_admin, repo):
    dados = {
        "nome": "rotina_b", "descricao": "Faz backup", "tipo_horario": "cron", "cron": "*/15 * * * *",
        "argumentos": "--modo completo\r\n\r\n/etc\r\n", "tentativas": "3", "intervalo_tentativa_min": "10",
        "timeout_min": "30", "ativa": ["false", "true"], "avisar_falha": ["false"],
        "emails_aviso": "a@x.com, b@x.com\nc@x.com",
        "segredo_nome": ["TOKEN", "SENHA_DB", ""], "segredo_tipo": ["variavel", "conexao", "variavel"],
        "segredo_ref": ["token_api", "banco", ""], "segredo_campo": ["password", "password", "password"],
    }
    r = cliente_admin.post("/nova", data=dados, files=ARQ, headers=MESMA_ORIGEM)
    assert r.status_code == 303, r.text
    rot = repo.obter("rotina_b")
    assert rot.descricao == "Faz backup" and rot.agendamento == "*/15 * * * *"
    assert rot.argumentos == ("--modo completo", "/etc")
    assert (rot.tentativas, rot.intervalo_tentativa_min, rot.timeout_min) == (3, 10, 30)
    assert rot.ativa is True and rot.avisar_falha is False
    assert rot.emails_aviso == ("a@x.com", "b@x.com", "c@x.com")
    assert rot.segredos["TOKEN"].variavel == "token_api"
    assert (rot.segredos["SENHA_DB"].conexao, rot.segredos["SENHA_DB"].campo) == ("banco", "password")


def test_criar_com_script_existente(cliente_admin, repo_com_a):
    r = cliente_admin.post("/nova", data={**FORM_A, "nome": "rotina_c", "origem_script": "existente",
                                          "script_existente": "rotinas/rotina_a/a.sh"}, headers=MESMA_ORIGEM)
    assert r.status_code == 303
    assert repo_com_a.obter("rotina_c").script == "rotinas/rotina_a/a.sh"


def test_erro_de_validacao_mostra_mensagem_e_preserva_campos(cliente_admin, repo):
    r = cliente_admin.post("/nova", data={**FORM_A, "nome": "X", "descricao": "minha descrição",
                                          "argumentos": "um\ndois", "emails_aviso": "z@x.com"},
                           files=ARQ, headers=MESMA_ORIGEM)
    assert r.status_code == 422 and "nome" in r.text and 'value="X"' in r.text
    assert "letras minúsculas" in r.text
    assert "minha descrição" in r.text and "um\ndois" in r.text and "z@x.com" in r.text
    assert repo.obter("X") is None


def test_erros_do_formulario_em_portugues(cliente_admin):
    r = cliente_admin.post("/nova", data={**FORM_A, "hora": "25", "tentativas": "muitas",
                                          "emails_aviso": "sem-arroba"}, files=ARQ, headers=MESMA_ORIGEM)
    assert r.status_code == 422
    assert "Hora deve estar entre 0 e 23" in r.text
    assert "número inteiro" in r.text
    assert "E-mail inválido: sem-arroba" in r.text


def test_criar_sem_script_pede_script(cliente_admin):
    r = cliente_admin.post("/nova", data=FORM_A, headers=MESMA_ORIGEM)
    assert r.status_code == 422 and "Envie um script" in r.text


def test_upload_binario_recusado(cliente_admin):
    r = cliente_admin.post("/nova", data=FORM_A, files={"script": ("a.bin", b"\x00\x01\x02")}, headers=MESMA_ORIGEM)
    assert r.status_code == 422 and "texto" in r.text


def test_formulario_novo(cliente_admin, repo_com_a):
    r = cliente_admin.get("/nova")
    assert r.status_code == 200
    assert 'name="nome"' in r.text and 'type="file"' in r.text
    assert "rotinas/rotina_a/a.sh" in r.text  # escolha de script existente


# ---------- lista ----------

def test_lista_mostra_descricao_do_horario_e_yaml_invalido(cliente_admin, repo_com_a, airflow_fake):
    (repo_com_a.dados_dir / "rotinas" / "quebrada.yaml").write_text("nome: [", encoding="utf-8")
    airflow_fake.dados["rotina_a"] = EstadoDag(False, datetime(2026, 11, 10, 6, 0, tzinfo=timezone.utc), True, True)
    r = cliente_admin.get("/")
    assert r.status_code == 200
    assert "rotina_a" in r.text and "Diário às 02:00" in r.text
    assert "quebrada.yaml" in r.text and "Não foi possível ler o arquivo" in r.text
    assert "10/11/2026 02:00" in r.text  # 06:00 UTC = 02:00 em Manaus
    assert "/dags/rotina_a" in r.text


def test_lista_com_api_fora_mostra_indisponivel(cliente_admin, repo_com_a, airflow_quebrado):
    r = cliente_admin.get("/")
    assert r.status_code == 200 and "rotina_a" in r.text and "indisponível" in r.text


def test_lista_escapa_conteudo_do_usuario(cliente_admin, repo):
    repo.criar({"nome": "rotina_x", "agendamento": "@daily", "descricao": "<script>alert(1)</script>"}, SCRIPT, "j")
    r = cliente_admin.get("/")
    assert "<script>alert(1)</script>" not in r.text and "&lt;script&gt;" in r.text


# ---------- ativar / desativar ----------

def test_desativar_pausa_no_airflow(cliente_admin, repo_com_a, airflow_fake):
    r = cliente_admin.post("/rotina_a/ativa", data={"ativa": "false"}, headers=MESMA_ORIGEM)
    assert r.status_code == 303
    assert airflow_fake.pausas == [("rotina_a", True)] and repo_com_a.obter("rotina_a").ativa is False
    cliente_admin.post("/rotina_a/ativa", data={"ativa": "true"}, headers=MESMA_ORIGEM)
    assert airflow_fake.pausas[-1] == ("rotina_a", False) and repo_com_a.obter("rotina_a").ativa is True


def test_desativar_com_api_fora_avisa(cliente_admin, repo_com_a, airflow_quebrado):
    r = cliente_admin.post("/rotina_a/ativa", data={"ativa": "false"}, headers=MESMA_ORIGEM)
    assert r.status_code == 200
    assert "Rotina salva, mas não foi possível aplicar a pausa no Airflow agora; a vigia apontará a divergência" in r.text
    assert repo_com_a.obter("rotina_a").ativa is False


def test_ativa_valor_invalido_ou_rotina_inexistente(cliente_admin, repo_com_a):
    assert cliente_admin.post("/rotina_a/ativa", data={"ativa": "talvez"}, headers=MESMA_ORIGEM).status_code == 400
    assert cliente_admin.post("/nao_existe/ativa", data={"ativa": "true"}, headers=MESMA_ORIGEM).status_code == 404


# ---------- editar ----------

class _Formulario(HTMLParser):
    """Simula o envio do formulário pelo navegador: coleta o que ele mandaria."""

    def __init__(self):
        super().__init__()
        self.campos: list[tuple[str, str]] = []
        self._select = None
        self._opcao_padrao = None
        self._textarea = None
        self._texto = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "input" and a.get("name") and "disabled" not in a:
            tipo = a.get("type", "text")
            if tipo == "file" or tipo in ("submit", "button"):
                return
            if tipo in ("checkbox", "radio") and "checked" not in a:
                return
            self.campos.append((a["name"], a.get("value", "on" if tipo in ("checkbox", "radio") else "")))
        elif tag == "select" and a.get("name") and "disabled" not in a:
            self._select, self._opcao_padrao, self._escolhida = a["name"], None, None
        elif tag == "option" and self._select is not None:
            if self._opcao_padrao is None:
                self._opcao_padrao = a.get("value", "")
            if "selected" in a:
                self._escolhida = a.get("value", "")
        elif tag == "textarea" and a.get("name"):
            self._textarea, self._texto = a["name"], []

    def handle_endtag(self, tag):
        if tag == "select" and self._select is not None:
            valor = self._escolhida if self._escolhida is not None else self._opcao_padrao
            self.campos.append((self._select, valor or ""))
            self._select = None
        elif tag == "textarea" and self._textarea:
            texto = "".join(self._texto)
            self.campos.append((self._textarea, texto[1:] if texto.startswith("\n") else texto))
            self._textarea = None

    def handle_data(self, data):
        if self._textarea:
            self._texto.append(data)


def _enviar_como_navegador(html: str, trocar: dict) -> dict:
    p = _Formulario()
    p.feed(html)
    dados: dict[str, list[str]] = {}
    for nome, valor in p.campos:
        dados.setdefault(nome, []).append(valor)
    for nome, valor in trocar.items():
        dados[nome] = [valor]
    return dados


def test_editar_preenche_preset(cliente_admin, repo_com_a):
    r = cliente_admin.get("/rotina_a/editar")
    assert r.status_code == 200
    dados = _enviar_como_navegador(r.text, {})
    assert dados["tipo_horario"] == ["diario"] and dados["hora"] == ["2"] and dados["minuto"] == ["0"]
    assert dados["origem_script"] == ["manter"]


def test_editar_cron_avancado_preenche_campo_cron(cliente_admin, repo):
    repo.criar({"nome": "rotina_k", "agendamento": "*/5 * * * 1-5"}, SCRIPT, "j")
    dados = _enviar_como_navegador(cliente_admin.get("/rotina_k/editar").text, {})
    assert dados["tipo_horario"] == ["cron"] and dados["cron"] == ["*/5 * * * 1-5"]


def test_editar_so_o_horario_mantem_os_demais_campos(cliente_admin, repo):
    repo.criar({
        "nome": "rotina_a", "agendamento": "0 2 * * *", "descricao": "Descrição <com> acento",
        "argumentos": ["--x", "valor com espaço"], "tentativas": 4, "intervalo_tentativa_min": 7,
        "timeout_min": 90, "avisar_falha": False, "emails_aviso": ["a@x.com", "b@x.com"],
        "segredos": {"TOKEN": {"variavel": "tok"}, "SENHA": {"conexao": "banco", "campo": "login"}},
    }, SCRIPT, "joao")
    antes = repo.obter("rotina_a")
    dados = _enviar_como_navegador(cliente_admin.get("/rotina_a/editar").text, {"hora": "5", "minuto": "15"})
    r = cliente_admin.post("/rotina_a/editar", data=dados, headers=MESMA_ORIGEM)
    assert r.status_code == 303, r.text
    depois = repo.obter("rotina_a")
    assert depois.agendamento == "15 5 * * *"
    for campo in ("descricao", "argumentos", "tentativas", "intervalo_tentativa_min", "timeout_min",
                  "avisar_falha", "emails_aviso", "segredos", "script", "ativa", "criado_por"):
        assert getattr(depois, campo) == getattr(antes, campo), campo


def test_editar_trocando_script_por_upload(cliente_admin, repo_com_a):
    dados = _enviar_como_navegador(cliente_admin.get("/rotina_a/editar").text, {"origem_script": "upload"})
    r = cliente_admin.post("/rotina_a/editar", data=dados, files={"script": ("novo.sh", b"#!/bin/sh\necho 2\n")},
                           headers=MESMA_ORIGEM)
    assert r.status_code == 303
    assert repo_com_a.obter("rotina_a").script == "rotinas/rotina_a/novo.sh"


def test_editar_desativando_pausa_no_airflow(cliente_admin, repo_com_a, airflow_fake):
    dados = _enviar_como_navegador(cliente_admin.get("/rotina_a/editar").text, {})
    dados["ativa"] = ["false"]
    r = cliente_admin.post("/rotina_a/editar", data=dados, headers=MESMA_ORIGEM)
    assert r.status_code == 303 and airflow_fake.pausas == [("rotina_a", True)]


def test_editar_com_erro_preserva_e_mostra(cliente_admin, repo_com_a):
    dados = _enviar_como_navegador(cliente_admin.get("/rotina_a/editar").text,
                                   {"tipo_horario": "cron", "cron": "isso não é cron"})
    r = cliente_admin.post("/rotina_a/editar", data=dados, headers=MESMA_ORIGEM)
    assert r.status_code == 422 and "Agendamento inválido" in r.text and "isso não é cron" in r.text
    assert repo_com_a.obter("rotina_a").agendamento == "0 2 * * *"


def test_editar_inexistente_404(cliente_admin, repo):
    assert cliente_admin.get("/nao_existe/editar").status_code == 404
    assert cliente_admin.post("/nao_existe/editar", data=FORM_A, headers=MESMA_ORIGEM).status_code == 404


# ---------- excluir ----------

def test_excluir_pede_confirmacao_e_remove(cliente_admin, repo_com_a):
    r = cliente_admin.get("/rotina_a/excluir")
    assert r.status_code == 200 and "rotina_a" in r.text and 'method="post"' in r.text
    assert repo_com_a.obter("rotina_a") is not None
    r = cliente_admin.post("/rotina_a/excluir", headers=MESMA_ORIGEM)
    assert r.status_code == 303 and repo_com_a.obter("rotina_a") is None
    assert git_log(repo_com_a)[0] == ("joao", "Exclui rotina rotina_a")


def test_falha_do_git_vira_pagina_de_erro_em_portugues(cliente_admin, repo_com_a, monkeypatch):
    from rotinas_core.armazenamento import ErroRepositorio

    def falha(*a, **k):
        raise ErroRepositorio("O git falhou ao executar 'git commit'")
    monkeypatch.setattr(repo_com_a, "excluir", falha)
    monkeypatch.setattr(repo_com_a, "definir_ativa", falha)
    for url, dados in (("/rotina_a/excluir", None), ("/rotina_a/ativa", {"ativa": "false"})):
        r = cliente_admin.post(url, data=dados, headers=MESMA_ORIGEM)
        assert r.status_code == 500 and "Não foi possível gravar a alteração" in r.text and "git commit" in r.text


def test_excluir_inexistente_404(cliente_admin, repo):
    assert cliente_admin.get("/nao_existe/excluir").status_code == 404
    assert cliente_admin.post("/nao_existe/excluir", headers=MESMA_ORIGEM).status_code == 404


# ---------- próximas execuções ----------

def test_api_proximas(cliente_admin):
    assert len(cliente_admin.get("/api/proximas", params={"agendamento": "0 2 * * *"}).json()["proximas"]) == 3


def test_api_proximas_por_preset_e_invalido(cliente_admin):
    r = cliente_admin.get("/api/proximas", params={"tipo_horario": "mensal", "hora": "3", "minuto": "5", "dia_mes": "10"})
    corpo = r.json()
    assert r.status_code == 200 and corpo["agendamento"] == "5 3 10 * *"
    assert corpo["descricao"] == "Mensal, dia 10 às 03:05" and len(corpo["proximas"]) == 3
    assert all(" 03:05" in p for p in corpo["proximas"])
    r = cliente_admin.get("/api/proximas", params={"agendamento": "lixo"})
    assert r.status_code == 422 and r.json()["erro"]
