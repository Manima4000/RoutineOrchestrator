ARG AIRFLOW_VERSION=3.1.8
FROM apache/airflow:${AIRFLOW_VERSION}-python3.12

# Repetido: ARGs declarados antes do FROM não existem depois dele.
ARG AIRFLOW_VERSION=3.1.8
# Proxy só para o build; exportado em minúsculas e maiúsculas (o apt lê minúsculas) apenas dentro dos RUN.
ARG BUILD_HTTP_PROXY
ARG BUILD_HTTPS_PROXY

USER root
RUN export http_proxy="${BUILD_HTTP_PROXY}" HTTP_PROXY="${BUILD_HTTP_PROXY}" https_proxy="${BUILD_HTTPS_PROXY}" HTTPS_PROXY="${BUILD_HTTPS_PROXY}" \
    && apt-get update \
    && apt-get install -y --no-install-recommends openssh-client rsync curl postgresql-client tar gzip git \
    && apt-get clean \
    && git config --system user.name "Airflow Rotinas" \
    && git config --system user.email "airflow-rotinas@localhost" \
    && git config --system safe.directory '*'

# Ferramentas pedidas pelos scripts das rotinas (ferramentas/sistema.txt). Camada separada: mudar a
# lista não reconstrói as camadas acima. Linha inválida interrompe o build mostrando qual é.
COPY ferramentas/sistema.txt /tmp/ferramentas-sistema.txt
RUN export http_proxy="${BUILD_HTTP_PROXY}" HTTP_PROXY="${BUILD_HTTP_PROXY}" https_proxy="${BUILD_HTTPS_PROXY}" HTTPS_PROXY="${BUILD_HTTPS_PROXY}" \
    && sed -e 's/#.*//' -e 's/[[:space:]]//g' /tmp/ferramentas-sistema.txt | grep -v '^$' > /tmp/pacotes.txt || true \
    && if grep -vE '^[a-z0-9][a-z0-9+.-]*(=[A-Za-z0-9.+:~-]+)?$' /tmp/pacotes.txt; then \
         echo "ERRO: linha(s) inválida(s) acima em ferramentas/sistema.txt" >&2; exit 1; fi \
    && if [ -s /tmp/pacotes.txt ]; then \
         apt-get update && xargs -a /tmp/pacotes.txt apt-get install -y --no-install-recommends \
         && apt-get clean && rm -rf /var/lib/apt/lists/*; fi \
    && rm -f /tmp/pacotes.txt /tmp/ferramentas-sistema.txt

USER airflow
COPY requirements.txt /tmp/requirements.txt
RUN export http_proxy="${BUILD_HTTP_PROXY}" HTTP_PROXY="${BUILD_HTTP_PROXY}" https_proxy="${BUILD_HTTPS_PROXY}" HTTPS_PROXY="${BUILD_HTTPS_PROXY}" \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-3.12.txt"

# Bibliotecas pedidas pelos scripts das rotinas (ferramentas/python.txt), com as mesmas constraints
# do Airflow para não trocar versões de que ele depende. Opções do pip (linhas com "-") são recusadas.
COPY ferramentas/python.txt /tmp/ferramentas-python.txt
RUN export http_proxy="${BUILD_HTTP_PROXY}" HTTP_PROXY="${BUILD_HTTP_PROXY}" https_proxy="${BUILD_HTTPS_PROXY}" HTTPS_PROXY="${BUILD_HTTPS_PROXY}" \
    && sed -e 's/#.*//' -e 's/[[:space:]]//g' /tmp/ferramentas-python.txt | grep -v '^$' > /tmp/libs.txt || true \
    && if grep -vE '^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9,._-]+\])?([<>=!~]=?[A-Za-z0-9.*+!-]+(,[<>=!~]=?[A-Za-z0-9.*+!-]+)*)?$' /tmp/libs.txt; then \
         echo "ERRO: linha(s) inválida(s) acima em ferramentas/python.txt" >&2; exit 1; fi \
    && if [ -s /tmp/libs.txt ]; then \
         pip install --no-cache-dir -r /tmp/libs.txt \
         --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-3.12.txt"; fi \
    && rm -f /tmp/libs.txt

COPY scripts_base/lib /opt/rotinas/lib
ENV PYTHONPATH=/opt/rotinas/lib
