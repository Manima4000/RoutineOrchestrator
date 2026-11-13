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

# govc: CLI oficial da VMware para o vCenter (VMs, energia, clone de template, snapshots...). Não existe
# no apt; baixa o binário da versão fixada e confere o SHA-256 (checksums.txt da release). Para atualizar,
# troque a versão e os dois hashes. Uso nos scripts: GOVC_URL, GOVC_USERNAME, GOVC_PASSWORD vindos de segredos.
ARG GOVC_VERSAO=0.56.2
ARG GOVC_SHA256_AMD64=12889f30e42e868487041f6628e9789606c80e13a194fb37c099abffc92d5a59
ARG GOVC_SHA256_ARM64=9c34a018300fbb02b943e48f277b9cee8f90ab7a6e6936427ef9f48c1e93af50
RUN export http_proxy="${BUILD_HTTP_PROXY}" HTTP_PROXY="${BUILD_HTTP_PROXY}" https_proxy="${BUILD_HTTPS_PROXY}" HTTPS_PROXY="${BUILD_HTTPS_PROXY}" \
    && case "$(dpkg --print-architecture)" in \
         amd64) arq=x86_64; sha="${GOVC_SHA256_AMD64}" ;; \
         arm64) arq=arm64; sha="${GOVC_SHA256_ARM64}" ;; \
         *) echo "ERRO: arquitetura sem govc configurado" >&2; exit 1 ;; esac \
    && curl -fsSL -o /tmp/govc.tar.gz "https://github.com/vmware/govmomi/releases/download/v${GOVC_VERSAO}/govc_Linux_${arq}.tar.gz" \
    && echo "${sha}  /tmp/govc.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/govc.tar.gz -C /usr/local/bin govc \
    && chmod 755 /usr/local/bin/govc \
    && rm -f /tmp/govc.tar.gz \
    && govc version

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
