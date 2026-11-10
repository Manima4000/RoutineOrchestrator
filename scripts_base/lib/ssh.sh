# shellcheck shell=bash
# Funções de apoio para SSH nos scripts das rotinas. Uso: source "$ROTINAS_LIB/ssh.sh"
# Variáveis: SSH_CHAVE, SSH_USUARIO (ou SSH_USUARIO_ALVO), SSH_KNOWN_HOSTS.
# A verificação da chave do servidor está sempre ligada: host desconhecido é recusado
# (cadastre-o antes com scripts_base/cadastrar_alvo.sh).
# Seguro para "source" sob set -euo pipefail; erros próprios usam return, nunca exit.

_ssh_preparar() {
    if [ -z "${SSH_CHAVE:-}" ]; then
        echo "ERRO: variável SSH_CHAVE vazia. Rode o script por uma rotina (que fornece a chave ssh_padrao)." >&2
        return 2
    fi
    if [ -z "${SSH_KNOWN_HOSTS:-}" ]; then
        echo "ERRO: variável SSH_KNOWN_HOSTS vazia." >&2
        return 2
    fi
    _SSH_USUARIO="${SSH_USUARIO_ALVO:-${SSH_USUARIO:-}}"
    if [ -z "$_SSH_USUARIO" ]; then
        echo "ERRO: usuário SSH não definido (SSH_USUARIO ou SSH_USUARIO_ALVO)." >&2
        return 2
    fi
    _SSH_OPCOES=(
        -i "$SSH_CHAVE"
        -o "UserKnownHostsFile=$SSH_KNOWN_HOSTS"
        -o StrictHostKeyChecking=yes
        -o BatchMode=yes
        -o ConnectTimeout=15
    )
}

# remoto HOST COMANDO...  -> executa o comando no alvo; devolve o código de saída remoto
# Contrato: com UM argumento após HOST, ele é uma string de shell interpretada no alvo
# (ex.: remoto h 'cd /x && ls'). Com DOIS ou mais, cada argumento é citado (printf %q) e chega
# literalmente (ex.: remoto h touch "a b" cria um arquivo; '$(id)' não é executado).
remoto() {
    if [ "$#" -lt 2 ]; then
        echo "Uso: remoto HOST COMANDO..." >&2
        return 2
    fi
    _ssh_preparar || return $?
    local host="$1"
    shift
    local comando
    if [ "$#" -eq 1 ]; then
        comando="$1"
    else
        printf -v comando '%q ' "$@"
    fi
    ssh "${_SSH_OPCOES[@]}" "$_SSH_USUARIO@$host" "$comando"
}

# copiar_para HOST ORIGEM_LOCAL DESTINO_REMOTO
copiar_para() {
    if [ "$#" -ne 3 ]; then
        echo "Uso: copiar_para HOST ORIGEM DESTINO" >&2
        return 2
    fi
    _ssh_preparar || return $?
    scp -q -r "${_SSH_OPCOES[@]}" -- "$2" "$_SSH_USUARIO@$1:$3"
}

# copiar_de HOST ORIGEM_REMOTA DESTINO_LOCAL
copiar_de() {
    if [ "$#" -ne 3 ]; then
        echo "Uso: copiar_de HOST ORIGEM DESTINO" >&2
        return 2
    fi
    _ssh_preparar || return $?
    scp -q -r "${_SSH_OPCOES[@]}" -- "$_SSH_USUARIO@$1:$2" "$3"
}
