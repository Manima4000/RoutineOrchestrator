#!/usr/bin/env bash
# Prepara o ambiente de rotinas. Idempotente. Uso: ./instalar.sh [--teste]
set -euo pipefail
cd "$(dirname "$0")"

TESTE=0
[ "${1:-}" = "--teste" ] && TESTE=1

aleatorio() { head -c 64 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c "${1:-24}"; }

definir() { # definir CHAVE VALOR  (substitui a linha CHAVE=... em .env)
    sed -i "s|^$1=.*|$1=$2|" .env
}

preencher() { # preenche CHAVE apenas se ainda estiver como CHANGEME
    if grep -q "^$1=CHANGEME$" .env; then definir "$1" "$2"; fi
}

if [ ! -f .env ]; then
    cp .env.example .env
    chmod 600 .env
    echo "Arquivo .env criado."
fi

# Chave Fernet: base64 url-safe de 32 bytes
preencher AIRFLOW__CORE__FERNET_KEY "$(head -c 32 /dev/urandom | base64 | tr '+/' '-_')"
preencher AIRFLOW__API_AUTH__JWT_SECRET "$(aleatorio 48)"
preencher AIRFLOW__API__SECRET_KEY "$(aleatorio 48)"
preencher POSTGRES_PASSWORD "$(aleatorio 24)"
preencher ADMIN_SENHA "$(aleatorio 16)"
preencher AIRFLOW_API_SENHA "$(aleatorio 24)"
definir AIRFLOW_UID "$(id -u)"

if [ "$TESTE" = 1 ]; then
    definir DADOS_HOST_DIR "./dados-dev"
    if [ ! -f teste/ssh/chave_teste ]; then
        ssh-keygen -t ed25519 -N "" -C "chave-teste" -f teste/ssh/chave_teste >/dev/null
        echo "Chave SSH de teste gerada em teste/ssh/chave_teste."
    fi
fi

DADOS_HOST_DIR="$(grep '^DADOS_HOST_DIR=' .env | cut -d= -f2-)"
mkdir -p "$DADOS_HOST_DIR/rotinas" "$DADOS_HOST_DIR/scripts" logs backups ssh dags
if [ ! -d "$DADOS_HOST_DIR/.git" ]; then
    git init -q "$DADOS_HOST_DIR"
    echo "Repositório Git iniciado em $DADOS_HOST_DIR."
fi
touch ssh/known_hosts
chmod 600 ssh/known_hosts

echo
echo "Ambiente preparado. Para subir: docker compose up -d --build"
echo "Usuário Admin: $(grep '^ADMIN_USUARIO=' .env | cut -d= -f2-)  Senha: $(grep '^ADMIN_SENHA=' .env | cut -d= -f2-)"
echo
echo "Chave Fernet: $(grep '^AIRFLOW__CORE__FERNET_KEY=' .env | cut -d= -f2-)"
echo "ATENÇÃO: Guarde esta chave em local seguro (sem ela, variáveis e conexões cifradas não podem ser recuperadas)."
