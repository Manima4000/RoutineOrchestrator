#!/usr/bin/env bash
# Gera o par de chaves SSH do ambiente (ed25519), grava a privada na Connection "ssh_padrao"
# do Airflow (criptografada pela Fernet) e guarda SÓ a pública em ssh/id_ambiente.pub.
# Rodar na máquina que controla o compose, com o ambiente no ar. Uso: gerar_chave_ambiente.sh [USUARIO]
# Se a Connection já existir, é substituída (a chave antiga deixa de valer).
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USUARIO="${1:-airflow-svc}"
SERVICO=airflow-apiserver
cd "$RAIZ"

TMP="$(mktemp -d)"
chmod 700 "$TMP"
ARQ_REMOTO=""
limpar() {
    if [ -n "$ARQ_REMOTO" ]; then
        docker compose exec -T "$SERVICO" rm -f "$ARQ_REMOTO" >/dev/null 2>&1 || true
    fi
    if [ -d "$TMP" ]; then
        find "$TMP" -type f -exec shred -u {} + 2>/dev/null || true
        rm -rf "$TMP"
    fi
}
trap limpar EXIT

ssh-keygen -q -t ed25519 -N "" -C "airflow-rotinas-ambiente" -f "$TMP/id"

# JSON de importação montado em arquivo (a chave nunca vai na linha de comando)
python3 - "$TMP/id" "$USUARIO" >"$TMP/conexao.json" <<'PY'
import json, sys
chave = open(sys.argv[1]).read()
print(json.dumps({"ssh_padrao": {"conn_type": "ssh", "login": sys.argv[2],
                                 "extra": json.dumps({"private_key": chave})}}))
PY

ARQ_REMOTO="/tmp/ssh_padrao_$$.json"
# via pipe: o compose exec perde o stdin quando ele é redirecionado direto de arquivo
cat "$TMP/conexao.json" | docker compose exec -T "$SERVICO" bash -c 'umask 077; cat > "$1"' _ "$ARQ_REMOTO"
docker compose exec -T "$SERVICO" airflow connections import "$ARQ_REMOTO" --overwrite

mkdir -p "$RAIZ/ssh"
install -m 644 "$TMP/id.pub" "$RAIZ/ssh/id_ambiente.pub"

echo
echo "Connection ssh_padrao criada/atualizada (usuário: $USUARIO)."
echo "Chave pública salva em ssh/id_ambiente.pub. Instale-a em ~$USUARIO/.ssh/authorized_keys em cada alvo:"
cat "$RAIZ/ssh/id_ambiente.pub"
