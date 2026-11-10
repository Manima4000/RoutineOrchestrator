"""Apoio a SSH para scripts Python das rotinas (paramiko; netmiko para equipamentos de rede).

Usa SSH_CHAVE, SSH_USUARIO e SSH_KNOWN_HOSTS. Chaves de servidor desconhecidas são sempre
recusadas (RejectPolicy): cadastre o alvo antes com scripts_base/cadastrar_alvo.sh.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import paramiko

_TIMEOUT_CONEXAO = 15


@dataclass(frozen=True)
class Resultado:
    codigo: int
    saida: str
    erro: str


class ErroRemoto(Exception):
    def __init__(self, host: str, comando: str, resultado: Resultado):
        self.host = host
        self.comando = comando
        self.resultado = resultado
        cauda = resultado.erro.strip()[-500:]
        super().__init__(
            f"Comando falhou em {host} (código de saída {resultado.codigo})"
            + (f": {cauda}" if cauda else "")
        )


def _var(nome: str) -> str:
    valor = os.environ.get(nome, "")
    if not valor:
        raise RuntimeError(f"Variável de ambiente {nome} vazia. Rode o script por uma rotina.")
    return valor


@contextmanager
def _cliente(host: str, usuario: str | None) -> Iterator[paramiko.SSHClient]:
    cliente = paramiko.SSHClient()
    cliente.load_host_keys(_var("SSH_KNOWN_HOSTS"))
    cliente.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        cliente.connect(
            host,
            username=usuario or os.environ.get("SSH_USUARIO_ALVO") or _var("SSH_USUARIO"),
            key_filename=_var("SSH_CHAVE"),
            look_for_keys=False,
            allow_agent=False,
            timeout=_TIMEOUT_CONEXAO,
        )
        yield cliente
    finally:
        cliente.close()


def remoto(
    host: str,
    comando: str,
    usuario: str | None = None,
    timeout: int = 300,
    verificar: bool = True,
) -> Resultado:
    with _cliente(host, usuario) as cliente:
        _, stdout, stderr = cliente.exec_command(comando, timeout=timeout)
        saida = stdout.read().decode(errors="replace")
        erro = stderr.read().decode(errors="replace")
        resultado = Resultado(stdout.channel.recv_exit_status(), saida, erro)
    if verificar and resultado.codigo != 0:
        raise ErroRemoto(host, comando, resultado)
    return resultado


def enviar(host: str, origem: str | Path, destino: str, usuario: str | None = None) -> None:
    with _cliente(host, usuario) as cliente, cliente.open_sftp() as sftp:
        sftp.put(str(origem), destino)


def receber(host: str, origem: str, destino: str | Path, usuario: str | None = None) -> None:
    with _cliente(host, usuario) as cliente, cliente.open_sftp() as sftp:
        sftp.get(origem, str(destino))


def conectar_equipamento(host: str, tipo_dispositivo: str, **kw):
    """Conexão netmiko com verificação estrita da chave do servidor (known_hosts do ambiente)."""
    from netmiko import ConnectHandler

    params = dict(
        device_type=tipo_dispositivo,
        host=host,
        username=os.environ.get("SSH_USUARIO_ALVO") or _var("SSH_USUARIO"),
        use_keys=True,
        key_file=_var("SSH_CHAVE"),
        ssh_strict=True,
        system_host_keys=False,
        alt_host_keys=True,
        alt_key_file=_var("SSH_KNOWN_HOSTS"),
    )
    params.update(kw)
    return ConnectHandler(**params)
