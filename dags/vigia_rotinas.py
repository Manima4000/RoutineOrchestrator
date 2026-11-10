"""Vigia: a cada 15 min confere se as rotinas rodaram e avisa por e-mail (um aviso por problema)."""
from __future__ import annotations

import json
from datetime import datetime

import pendulum
from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG, Variable

FUSO = pendulum.timezone("America/Manaus")
VARIAVEL = "vigia_estado"


def _vigiar():
    from rotinas_core.api_airflow import ClienteAirflow
    from rotinas_core.config import carregar_config
    from rotinas_core.modelo import carregar_rotinas
    from rotinas_core.notificacao import enviar
    from rotinas_core.vigia import ciclo

    cfg = carregar_config()
    rotinas, erros_yaml = carregar_rotinas(cfg.rotinas_dir, cfg.scripts_dir)
    cliente = ClienteAirflow(cfg.api_url, cfg.api_usuario, cfg.api_senha)
    ciclo(
        rotinas=rotinas, erros_yaml=erros_yaml, cliente=cliente, agora=datetime.now(FUSO),
        ler_estado=lambda: json.loads(Variable.get(VARIAVEL, default='{"chaves": []}')),
        gravar_estado=lambda d: Variable.set(VARIAVEL, json.dumps(d)),
        enviar=lambda assunto, corpo: enviar(cfg, assunto, corpo, cfg.aviso_destinatarios),
    )


with DAG(
    dag_id="vigia_rotinas", schedule="*/15 * * * *", start_date=pendulum.datetime(2026, 1, 1, tz=FUSO),
    catchup=False, max_active_runs=1, tags=["sistema"], is_paused_upon_creation=False,
    description="Confere se as rotinas rodaram e avisa por e-mail.",
):
    PythonOperator(task_id="vigiar", python_callable=_vigiar)
