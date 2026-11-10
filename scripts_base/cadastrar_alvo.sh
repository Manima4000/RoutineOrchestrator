#!/usr/bin/env bash
# Cadastra a chave do servidor de um alvo no known_hosts do ambiente.
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KNOWN_HOSTS="${SSH_KNOWN_HOSTS:-$RAIZ/ssh/known_hosts}"

uso() {
    cat <<'TXT'
Uso: cadastrar_alvo.sh [--sim] HOST [PORTA]

Obtém as chaves do servidor com ssh-keyscan, mostra as impressões digitais para
conferência e, após confirmação, acrescenta ao known_hosts do ambiente
(SSH_KNOWN_HOSTS, padrão: ssh/known_hosts no diretório do projeto).
Rodar de novo para um alvo já cadastrado não duplica a entrada.

  --sim   não pergunta; aceita as impressões digitais (somente para testes)
  --help  mostra esta ajuda
TXT
}

SIM=0
ARGS=()
for a in "$@"; do
    case "$a" in
        --sim) SIM=1 ;;
        --help | -h) uso; exit 0 ;;
        *) ARGS+=("$a") ;;
    esac
done
if [ "${#ARGS[@]}" -lt 1 ] || [ "${#ARGS[@]}" -gt 2 ]; then
    uso >&2
    exit 2
fi
HOST="${ARGS[0]}"
PORTA="${ARGS[1]:-22}"
[[ "$PORTA" =~ ^[0-9]+$ ]] || { echo "ERRO: porta inválida: $PORTA" >&2; exit 2; }

if [ "$PORTA" = "22" ]; then ALVO="$HOST"; else ALVO="[$HOST]:$PORTA"; fi

mostrar_chave_ambiente() {
    if [ -f "$RAIZ/ssh/id_ambiente.pub" ]; then
        echo
        echo "Instale esta chave pública em ~airflow-svc/.ssh/authorized_keys no alvo:"
        cat "$RAIZ/ssh/id_ambiente.pub"
    fi
}

if [ -f "$KNOWN_HOSTS" ] && ssh-keygen -F "$ALVO" -f "$KNOWN_HOSTS" >/dev/null 2>&1; then
    echo "O alvo $ALVO já está cadastrado em $KNOWN_HOSTS."
    mostrar_chave_ambiente
    exit 0
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
ssh-keyscan -T 10 -p "$PORTA" "$HOST" >"$TMP" 2>/dev/null || true
if [ ! -s "$TMP" ]; then
    echo "ERRO: não foi possível obter as chaves de $HOST:$PORTA (host inacessível ou sem SSH)." >&2
    exit 1
fi

echo "Impressões digitais de $ALVO:"
ssh-keygen -lf "$TMP"

if [ "$SIM" -ne 1 ]; then
    read -r -p "As impressões digitais conferem com as do servidor? (s/N) " resp || resp=""
    case "$resp" in
        s | S | sim | SIM | Sim) ;;
        *) echo "Cancelado: nada foi gravado." >&2; exit 1 ;;
    esac
fi

mkdir -p "$(dirname "$KNOWN_HOSTS")"
touch "$KNOWN_HOSTS"
chmod 600 "$KNOWN_HOSTS"
cat "$TMP" >>"$KNOWN_HOSTS"
echo "Alvo $ALVO cadastrado em $KNOWN_HOSTS."
mostrar_chave_ambiente
