#!/usr/bin/env bash
# Instala as rotinas de exemplo no diretório de dados e faz commit no Git dos dados.
# Idempotente; não sobrescreve rotinas que já existem.
# Diretório de dados: $DADOS_DIR, ou DADOS_HOST_DIR do .env (padrão /opt/airflow-rotinas/dados).
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EX="$RAIZ/scripts_base/exemplos"

if [ -n "${DADOS_DIR:-}" ]; then
    DADOS="$DADOS_DIR"
else
    DADOS="/opt/airflow-rotinas/dados"
    if [ -f "$RAIZ/.env" ] && grep -q '^DADOS_HOST_DIR=' "$RAIZ/.env"; then
        DADOS="$(grep '^DADOS_HOST_DIR=' "$RAIZ/.env" | cut -d= -f2-)"
    fi
fi
case "$DADOS" in /*) ;; *) DADOS="$RAIZ/$DADOS" ;; esac

mkdir -p "$DADOS/rotinas" "$DADOS/scripts/exemplos"
[ -d "$DADOS/.git" ] || git init -q "$DADOS"

instaladas=0
for yaml in "$EX"/rotinas/*.yaml; do
    nome="$(basename "$yaml")"
    if [ -e "$DADOS/rotinas/$nome" ]; then
        echo "Já existe, mantida: rotinas/$nome"
        continue
    fi
    script="$(sed -n 's/^script: *//p' "$yaml" | head -n1)"
    cp "$EX/scripts/$(basename "$script")" "$DADOS/scripts/$script"
    cp "$yaml" "$DADOS/rotinas/$nome"
    echo "Instalada: rotinas/$nome"
    instaladas=$((instaladas + 1))
done

git_dados() { git -c safe.directory="$DADOS" -C "$DADOS" "$@"; }
git_dados add rotinas scripts
if git_dados diff --cached --quiet; then
    echo "Nada novo para registrar no Git."
else
    git_dados -c user.name="Instalador de rotinas" -c user.email="rotinas@localhost" \
        commit -q -m "Instala rotinas de exemplo"
    echo "Commit criado: Instala rotinas de exemplo"
fi
