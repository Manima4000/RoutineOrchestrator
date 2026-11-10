import json
import os
from datetime import datetime, timezone

import httpx
import pytest

from rotinas_core.api_airflow import ClienteAirflow, EstadoDag, ErroApiAirflow


def cliente(handler):
    return ClienteAirflow("http://api", "svc", "senha", transporte=httpx.MockTransport(handler))


class Servidor:
    def __init__(self, dags=None, runs=None, erros=None):
        self.dags, self.runs, self.erros = dags or {}, runs or {}, erros or []
        self.chamadas, self.tokens, self.rejeitar = [], 0, 0

    def __call__(self, req: httpx.Request):
        self.chamadas.append((req.method, req.url.path, dict(req.url.params)))
        if req.url.path == "/auth/token":
            self.tokens += 1
            assert json.loads(req.content) == {"username": "svc", "password": "senha"}
            return httpx.Response(201, json={"access_token": f"tk{self.tokens}"})
        if self.rejeitar:
            self.rejeitar -= 1
            return httpx.Response(401, json={"detail": "expirado"})
        assert req.headers["Authorization"].startswith("Bearer tk")
        p = req.url.path
        if p == "/api/v2/importErrors":
            return httpx.Response(200, json={"import_errors": self.erros, "total_entries": len(self.erros)})
        partes = p.split("/")  # '', api, v2, dags, id[, dagRuns]
        dag_id = partes[4]
        if dag_id not in self.dags:
            return httpx.Response(404, json={"detail": "nao achou"})
        if req.method == "PATCH":
            self.dags[dag_id] = json.loads(req.content)["is_paused"]
            return httpx.Response(200, json={"dag_id": dag_id, "is_paused": self.dags[dag_id]})
        if len(partes) == 5:
            return httpx.Response(200, json={"dag_id": dag_id, "is_paused": self.dags[dag_id]})
        todos = self.runs.get(dag_id, [])
        sel = [r for r in todos if r["state"] == req.url.params.get("state", r["state"])]
        return httpx.Response(200, json={"dag_runs": sel[: int(req.url.params["limit"])], "total_entries": len(sel)})


def test_estados_mapeia_dag_e_execucoes():
    s = Servidor(dags={"a": False, "b": True}, runs={"a": [
        {"state": "failed", "end_date": "2026-11-10T07:00:00Z"},
        {"state": "success", "end_date": "2026-11-10T06:00:00Z"}]})
    est = cliente(s).estados(["a", "b", "c"])
    assert est["a"] == EstadoDag(False, datetime(2026, 11, 10, 6, tzinfo=timezone.utc), True, True)
    assert est["b"] == EstadoDag(True, None, True, False)
    assert est["c"] == EstadoDag(False, None, False, False)
    ok = [c for c in s.chamadas if c[1].endswith("/a/dagRuns") and c[2].get("state") == "success"]
    assert ok and ok[0][2]["order_by"] == "-end_date" and ok[0][2]["limit"] == "1"


def test_token_unico_e_reutilizado():
    s = Servidor(dags={"a": False})
    c = cliente(s)
    c.estados(["a"])
    c.estados(["a"])
    assert s.tokens == 1


def test_reautentica_uma_vez_em_401():
    s = Servidor(dags={"a": False})
    s.rejeitar = 1
    c = cliente(s)
    assert c.estados(["a"])["a"].existe and s.tokens == 2


def test_401_persistente_gera_erro_claro():
    s = Servidor(dags={"a": False})
    s.rejeitar = 5
    with pytest.raises(ErroApiAirflow, match="autentic"):
        cliente(s).estados(["a"])


def test_erro_http_vira_erro_em_portugues():
    c = cliente(lambda r: httpx.Response(201, json={"access_token": "tk"}) if r.url.path == "/auth/token"
                else httpx.Response(500, text="boom"))
    with pytest.raises(ErroApiAirflow, match="500"):
        c.erros_importacao()


def test_erros_importacao():
    s = Servidor(erros=[{"filename": "dags/x.py", "stack_trace": "Traceback\nValueError: ruim"}])
    assert cliente(s).erros_importacao() == ["dags/x.py\nTraceback\nValueError: ruim"]


def test_definir_pausa():
    s = Servidor(dags={"a": False})
    cliente(s).definir_pausa("a", True)
    assert s.dags["a"] is True
    patch = [c for c in s.chamadas if c[0] == "PATCH"][0]
    assert patch[2] == {"update_mask": "is_paused"}


@pytest.mark.integracao
def test_integracao_estados_vigia():
    c = ClienteAirflow(os.environ["AIRFLOW_API_URL"], os.environ["AIRFLOW_API_USUARIO"],
                       os.environ["AIRFLOW_API_SENHA"])
    assert c.estados(["vigia_rotinas"])["vigia_rotinas"].existe is True
