import importlib.util
from datetime import timedelta
from pathlib import Path

import pytest
from airflow.models import DagBag

from rotinas_core.modelo import Rotina

RAIZ = Path(__file__).resolve().parent.parent
ARQ_DAG = RAIZ / "dags" / "gerador_rotinas.py"


@pytest.fixture
def construir_dags(monkeypatch, tmp_path):
    monkeypatch.setenv("ROTINAS_DIR", str(tmp_path / "rotinas"))
    monkeypatch.setenv("SCRIPTS_DIR", str(tmp_path / "scripts"))
    spec = importlib.util.spec_from_file_location("gerador_rotinas_teste", ARQ_DAG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.construir_dags


@pytest.fixture
def rotina_exemplo():
    return Rotina(nome="rotina_a", agendamento="0 3 * * *", script="a.sh", descricao="Exemplo",
                  tentativas=2, intervalo_tentativa_min=5, timeout_min=60)


@pytest.fixture
def rotina_inativa():
    return Rotina(nome="rotina_b", agendamento="0 3 * * *", script="b.sh", ativa=False)


def test_dag_com_parametros_da_rotina(construir_dags, rotina_exemplo):
    d = construir_dags([rotina_exemplo], {})["rotina_a"]
    t = d.get_task("executar")
    assert d.max_active_runs == 1 and d.catchup is False and "rotina" in d.tags
    assert d.description == "Exemplo"
    assert t.retries == 2 and t.retry_delay == timedelta(minutes=5)
    assert t.execution_timeout == timedelta(minutes=61)
    assert t.on_failure_callback is not None


def test_rotina_inativa_nasce_pausada(construir_dags, rotina_inativa):
    assert construir_dags([rotina_inativa], {})["rotina_b"].is_paused_upon_creation is True


def test_arquivo_invalido_vira_dag_de_erro(construir_dags):
    dags = construir_dags([], {"meu arquivo.yaml": "nome: campo obrigatório"})
    d = dags["rotina_invalida__meu_arquivo"]
    assert "erro" in d.tags and "campo obrigatório" in d.description


def test_dagbag_importa_sem_erros(tmp_path, monkeypatch):
    (tmp_path / "rotinas").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "a.sh").write_text("echo oi\n")
    (tmp_path / "rotinas" / "rotina_a.yaml").write_text(
        "nome: rotina_a\nagendamento: '0 3 * * *'\nscript: a.sh\n")
    (tmp_path / "rotinas" / "quebrada.yaml").write_text("nome: x\n")
    monkeypatch.setenv("ROTINAS_DIR", str(tmp_path / "rotinas"))
    monkeypatch.setenv("SCRIPTS_DIR", str(tmp_path / "scripts"))
    bag = DagBag(dag_folder=str(ARQ_DAG), include_examples=False)
    assert bag.import_errors == {}
    assert {"rotina_a", "rotina_invalida__quebrada"} <= set(bag.dags)
