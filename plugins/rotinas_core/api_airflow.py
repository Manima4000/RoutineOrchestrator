"""Cliente da API REST do Airflow (usado pela vigia e pelo plugin).

Formatos verificados no Airflow 3.1.8:
- POST /auth/token  {"username","password"} -> 201 {"access_token": "..."}; uso: Authorization: Bearer
- GET /api/v2/dags/{id} -> 200 {"is_paused": bool, ...}; DAG inexistente -> 404
- GET /api/v2/dags/{id}/dagRuns?state=success&order_by=-end_date&limit=1
  -> {"dag_runs": [{"state", "end_date", "logical_date", ...}], "total_entries": n}
- GET /api/v2/importErrors -> {"import_errors": [{"filename", "stack_trace", ...}], "total_entries": n}
- PATCH /api/v2/dags/{id}?update_mask=is_paused  {"is_paused": bool}
- Token inválido/expirado -> 401 (ou 403 "Invalid JWT token" se malformado).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

import httpx

TIMEOUT_S = 15


class ErroApiAirflow(Exception):
    """Falha ao falar com a API do Airflow (mensagem em português)."""


@dataclass
class EstadoDag:
    pausado: bool
    ultima_execucao_ok: datetime | None
    existe: bool
    tem_execucoes: bool = False


def _data(texto: str | None) -> datetime | None:
    return datetime.fromisoformat(texto.replace("Z", "+00:00")) if texto else None


class ClienteAirflow:
    def __init__(self, api_url: str, usuario: str, senha: str, transporte: httpx.BaseTransport | None = None):
        self._usuario, self._senha = usuario, senha
        self._http = httpx.Client(base_url=api_url.rstrip("/"), timeout=TIMEOUT_S, transport=transporte)
        self._token: str | None = None

    def _autenticar(self) -> None:
        try:
            r = self._http.post("/auth/token", json={"username": self._usuario, "password": self._senha})
        except httpx.HTTPError as e:
            raise ErroApiAirflow(f"Não foi possível conectar à API do Airflow: {e}") from e
        if r.status_code not in (200, 201):
            raise ErroApiAirflow(f"Falha na autenticação na API do Airflow (HTTP {r.status_code}).")
        self._token = r.json()["access_token"]

    def _requisitar(self, metodo: str, caminho: str, aceitar_404: bool = False, **kw) -> httpx.Response | None:
        for tentativa in (1, 2):
            if self._token is None:
                self._autenticar()
            try:
                r = self._http.request(metodo, caminho, headers={"Authorization": f"Bearer {self._token}"}, **kw)
            except httpx.HTTPError as e:
                raise ErroApiAirflow(f"Não foi possível conectar à API do Airflow: {e}") from e
            if r.status_code in (401, 403) and tentativa == 1:
                self._token = None  # reautentica uma vez
                continue
            if r.status_code in (401, 403):
                raise ErroApiAirflow(f"A API do Airflow recusou a autenticação (HTTP {r.status_code}).")
            if r.status_code == 404 and aceitar_404:
                return None
            if not 200 <= r.status_code < 300:
                raise ErroApiAirflow(f"A API do Airflow respondeu HTTP {r.status_code} em {metodo} {caminho}.")
            return r
        raise AssertionError("inalcançável")

    def estados(self, dag_ids: Iterable[str]) -> dict[str, EstadoDag]:
        saida = {}
        for dag_id in dag_ids:
            r = self._requisitar("GET", f"/api/v2/dags/{dag_id}", aceitar_404=True)
            if r is None:
                saida[dag_id] = EstadoDag(False, None, False, False)
                continue
            pausado = bool(r.json()["is_paused"])
            ok = self._requisitar("GET", f"/api/v2/dags/{dag_id}/dagRuns",
                                  params={"state": "success", "order_by": "-end_date", "limit": 1}).json()
            ultima = _data(ok["dag_runs"][0]["end_date"]) if ok["dag_runs"] else None
            if ultima is not None:
                tem = True
            else:
                qualquer = self._requisitar("GET", f"/api/v2/dags/{dag_id}/dagRuns", params={"limit": 1}).json()
                tem = bool(qualquer["dag_runs"])
            saida[dag_id] = EstadoDag(pausado, ultima, True, tem)
        return saida

    def erros_importacao(self) -> list[str]:
        """Cada item: 'arquivo\\nstack trace'."""
        dados = self._requisitar("GET", "/api/v2/importErrors", params={"limit": 100}).json()
        return [f"{e['filename']}\n{e.get('stack_trace') or ''}".rstrip() for e in dados["import_errors"]]

    def definir_pausa(self, dag_id: str, pausado: bool) -> None:
        self._requisitar("PATCH", f"/api/v2/dags/{dag_id}", params={"update_mask": "is_paused"},
                         json={"is_paused": pausado})
