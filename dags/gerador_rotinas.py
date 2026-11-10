"""Gera um DAG por rotina (YAML em ROTINAS_DIR) e um DAG de erro por arquivo inválido."""
from __future__ import annotations

import os
import re
from datetime import timedelta
from pathlib import Path

import pendulum
from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG

from rotinas_core.modelo import Rotina, carregar_rotinas
from rotinas_core.tarefa import ao_falhar, executar_rotina

FUSO = pendulum.timezone("America/Manaus")
INICIO = pendulum.datetime(2026, 1, 1, tz=FUSO)


def _rodar(nome, **contexto):
    executar_rotina(nome, contexto)


def _falhar(mensagem, **_):
    raise RuntimeError(mensagem)


def _dag_rotina(r: Rotina) -> DAG:
    dag = DAG(
        dag_id=r.nome, schedule=r.agendamento, start_date=INICIO, catchup=False,
        max_active_runs=1, tags=["rotina"], description=r.descricao,
        is_paused_upon_creation=not r.ativa,
    )
    PythonOperator(
        task_id="executar", dag=dag, python_callable=_rodar, op_kwargs={"nome": r.nome},
        retries=r.tentativas, retry_delay=timedelta(minutes=r.intervalo_tentativa_min),
        # folga de 1 min: o timeout próprio de executar gera a mensagem amigável
        execution_timeout=timedelta(minutes=r.timeout_min + 1),
        on_failure_callback=ao_falhar,
    )
    return dag


def _dag_erro(arquivo: str, mensagem: str) -> DAG:
    stem = re.sub(r"[^a-z0-9_]", "_", Path(arquivo).stem.lower())
    dag = DAG(
        dag_id=f"rotina_invalida__{stem}", schedule=None, start_date=INICIO, catchup=False,
        tags=["rotina", "erro"], description=f"ERRO: {mensagem}",
    )
    PythonOperator(
        task_id="erro", dag=dag, python_callable=_falhar,
        op_kwargs={"mensagem": f"Arquivo {arquivo} inválido: {mensagem}"},
    )
    return dag


def construir_dags(rotinas: list[Rotina], erros: dict[str, str]) -> dict[str, DAG]:
    dags = {r.nome: _dag_rotina(r) for r in rotinas}
    for arquivo, mensagem in erros.items():
        d = _dag_erro(arquivo, mensagem)
        dags[d.dag_id] = d
    return dags


globals().update(construir_dags(*carregar_rotinas(
    Path(os.environ.get("ROTINAS_DIR", "/opt/airflow/dados/rotinas")),
    Path(os.environ.get("SCRIPTS_DIR", "/opt/airflow/dados/scripts")),
)))
