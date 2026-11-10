#!/bin/bash
# pg_dump do banco de metadados do Airflow para $BACKUPS_DIR/airflow-db/, mantendo os N últimos.
# Uso: backup_banco_airflow.sh [N=7 [HOST=postgres [USUARIO=airflow [BANCO=airflow]]]]
# A senha vem da variável PGPASSWORD, fornecida pela rotina via "segredos" (Connection postgres_airflow):
# nunca vai na linha de comando. Host, usuário e banco (não secretos) são argumentos, para o
# mascaramento de segredos do log não apagar palavras comuns como "airflow".
set -euo pipefail

MANTER="${1:-7}"
[[ "$MANTER" =~ ^[1-9][0-9]*$ ]] || { echo "ERRO: N inválido: $MANTER" >&2; exit 2; }
: "${BACKUPS_DIR:?ERRO: BACKUPS_DIR não definida}"
export PGHOST="${2:-${PGHOST:-postgres}}"
export PGUSER="${3:-${PGUSER:-airflow}}"
export PGDATABASE="${4:-${PGDATABASE:-airflow}}"
: "${PGPASSWORD:?ERRO: PGPASSWORD não definida (use segredos: PGPASSWORD da Connection postgres_airflow)}"

destino="$BACKUPS_DIR/airflow-db"
mkdir -p "$destino"
arquivo="$destino/airflow-$(date +%Y%m%d-%H%M%S-%3N).sql.gz"
parcial="$arquivo.parcial"
trap 'rm -f "$parcial"' EXIT

echo "Gerando backup de $PGDATABASE em $PGHOST..."
pg_dump --no-owner | gzip -c >"$parcial"
mv "$parcial" "$arquivo"
echo "Backup criado: $arquivo ($(du -h "$arquivo" | cut -f1))"

# Retenção: remove os mais antigos além dos N últimos
ls -1 "$destino"/airflow-*.sql.gz | sort -r | tail -n +"$((MANTER + 1))" | while read -r velho; do
    echo "Removendo backup antigo: $velho"
    rm -f -- "$velho"
done
