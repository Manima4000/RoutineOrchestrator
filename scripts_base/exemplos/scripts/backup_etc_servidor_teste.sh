#!/bin/bash
# Compacta o /etc de um servidor via SSH e traz o arquivo para $BACKUPS_DIR/etc-<HOST>/, mantendo os N últimos.
# Uso: backup_etc_servidor_teste.sh HOST [N=7]
# Requer: usuário de serviço no alvo com "sudo tar" liberado (ver docs de preparação de alvo).
set -euo pipefail
umask 077

HOST="${1:?Uso: backup_etc_servidor_teste.sh HOST [N=7]}"
MANTER="${2:-7}"
[[ "$HOST" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "ERRO: host inválido: $HOST" >&2; exit 2; }
[[ "$MANTER" =~ ^[1-9][0-9]*$ ]] || { echo "ERRO: N inválido: $MANTER" >&2; exit 2; }
: "${BACKUPS_DIR:?ERRO: BACKUPS_DIR não definida}"

# shellcheck source=/dev/null
source "${ROTINAS_LIB:?ERRO: ROTINAS_LIB não definida}/ssh.sh"

nome="etc-$HOST-$(date +%Y%m%d-%H%M%S-%3N).tar.gz"
destino="$BACKUPS_DIR/etc-$HOST"
mkdir -p "$destino"
parcial="$destino/$nome.parcial"

limpar() {
    rm -f "$parcial"
    remoto "$HOST" "rm -f ~/$nome" >/dev/null 2>&1 || true
}
trap limpar EXIT

echo "Compactando /etc em $HOST..."
# umask 077 + redirecionamento pelo shell do usuário de serviço: o arquivo (inclui shadow e chaves do
# host) pertence a ele e fica 600 no alvo (um arquivo criado pelo sudo seria de root e ilegível ao scp).
# tar sai com 1 em "arquivo mudou durante a leitura" (backup válido), mas sudo também sai com 1
# em falha própria: só aceita código 1 se o arquivo existir e não estiver vazio.
rc=0
remoto "$HOST" "umask 077; sudo -n tar czf - -C / etc > ~/$nome" || rc=$?
if [ "$rc" -eq 1 ] && remoto "$HOST" "test -s ~/$nome"; then
    echo "AVISO: tar terminou com código 1 (arquivos mudaram durante a leitura); backup mantido." >&2
elif [ "$rc" -ne 0 ]; then
    echo "ERRO: tar remoto falhou (código $rc)" >&2
    exit "$rc"
fi

echo "Copiando para $destino..."
copiar_de "$HOST" "$nome" "$parcial"
mv "$parcial" "$destino/$nome"
echo "Backup criado: $destino/$nome ($(du -h "$destino/$nome" | cut -f1))"

ls -1 "$destino"/etc-*.tar.gz | sort -r | tail -n +"$((MANTER + 1))" | while read -r velho; do
    echo "Removendo backup antigo: $velho"
    rm -f -- "$velho"
done
