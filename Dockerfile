ARG AIRFLOW_VERSION=3.1.8
FROM apache/airflow:${AIRFLOW_VERSION}-python3.12

# Repetido: ARGs declarados antes do FROM não existem depois dele.
ARG AIRFLOW_VERSION=3.1.8
# HTTP_PROXY/HTTPS_PROXY são ARGs predefinidos: valem só durante o build (apt/pip).
ARG HTTP_PROXY
ARG HTTPS_PROXY

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client rsync curl postgresql-client tar gzip git \
    && apt-get clean \
    && git config --system user.name "Airflow Rotinas" \
    && git config --system user.email "airflow-rotinas@localhost" \
    && git config --system safe.directory '*'

USER airflow
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-3.12.txt"

COPY scripts_base/lib /opt/rotinas/lib
ENV PYTHONPATH=/opt/rotinas/lib
