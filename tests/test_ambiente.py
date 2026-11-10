import os

import httpx
import pytest


@pytest.mark.integracao
def test_api_airflow_saudavel():
    r = httpx.get(os.environ["AIRFLOW_API_URL"] + "/api/v2/monitor/health", timeout=10)
    assert r.status_code == 200
    assert r.json()["scheduler"]["status"] == "healthy"


@pytest.mark.integracao
def test_executor_local_e_fuso():
    assert os.environ["AIRFLOW__CORE__EXECUTOR"] == "LocalExecutor"
    assert os.environ["AIRFLOW__CORE__DEFAULT_TIMEZONE"] == "America/Manaus"
