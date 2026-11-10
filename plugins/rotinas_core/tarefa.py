"""Tarefa que executa uma rotina: segredos, chave SSH temporária, ambiente e aviso de falha.

Fatos verificados no Airflow 3.1.8 (Task SDK):
- Variable: `airflow.sdk.Variable.get(key)`; se não existe levanta
  `airflow.sdk.exceptions.AirflowRuntimeError` com `.error.error == ErrorType.VARIABLE_NOT_FOUND`.
- Connection: `airflow.sdk.Connection.get(conn_id)`; se não existe levanta
  `airflow.exceptions.AirflowNotFoundException`. `conn.extra` pode ser str JSON ou dict.
- `mask_secret` fica em `airflow.sdk.log` (o caminho antigo `execution_time.secrets_masker` é obsoleto).
- `on_failure_callback` só roda no estado FAILED (retries esgotados); a tentativa que vai
  repetir (UP_FOR_RETRY) chama `on_retry_callback`, que não é definido aqui.
- No contexto do callback, `contexto["exception"]` é a exceção e `contexto["ti"]` tem `dag_id`/`run_id`.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from collections import deque
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote
from zoneinfo import ZoneInfo

from .config import Config, carregar_config
from .execucao import ErroExecucao, executar
from .modelo import RefSegredo, Rotina, carregar_rotinas
from .notificacao import enviar, montar_aviso_falha

logger = logging.getLogger(__name__)

_FUSO = ZoneInfo("America/Manaus")
_CONEXAO_SSH = "ssh_padrao"


class ErroSegredo(Exception):
    pass


class FalhaRotina(ErroExecucao):
    def __init__(self, mensagem: str, ultimas_linhas: list[str]):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.ultimas_linhas = list(ultimas_linhas)


def resolver_segredos(
    segredos: Mapping[str, RefSegredo],
    obter_variavel: Callable[[str], str],
    obter_conexao: Callable[[str], Any],
) -> dict[str, str]:
    """Os getters devem levantar KeyError quando o item não existe."""
    saida: dict[str, str] = {}
    for nome, ref in segredos.items():
        if ref.variavel is not None:
            try:
                valor = obter_variavel(ref.variavel)
            except KeyError:
                raise ErroSegredo(f"Segredo {nome}: Variable '{ref.variavel}' não encontrada") from None
        else:
            try:
                conn = obter_conexao(ref.conexao)
            except KeyError:
                raise ErroSegredo(f"Segredo {nome}: Connection '{ref.conexao}' não encontrada") from None
            valor = getattr(conn, ref.campo, None)
            if valor is None or valor == "":
                raise ErroSegredo(
                    f"Segredo {nome}: campo '{ref.campo}' da Connection '{ref.conexao}' está vazio"
                )
            if isinstance(valor, (dict, list)):
                valor = json.dumps(valor)
        saida[nome] = str(valor)
    return saida


@contextmanager
def chave_temporaria(conteudo: str | None) -> Iterator[Path | None]:
    if conteudo is None:
        yield None
        return
    pasta = Path(tempfile.mkdtemp(prefix="chave-"))
    try:
        os.chmod(pasta, 0o700)
        caminho = pasta / "id"
        fd = os.open(caminho, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(conteudo)
        yield caminho
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def montar_ambiente(
    rotina: Rotina,
    segredos: dict[str, str],
    chave_path: Path | None,
    ssh_usuario: str | None,
    config: Config,
    execucao_id: str,
) -> dict[str, str]:
    env = dict(segredos)
    if chave_path is not None:
        env["SSH_CHAVE"] = str(chave_path)
    if ssh_usuario:
        env["SSH_USUARIO"] = ssh_usuario
    env.update(
        SSH_KNOWN_HOSTS=str(config.known_hosts),
        ROTINAS_LIB=str(config.lib_dir),
        PYTHONPATH=str(config.lib_dir),
        ROTINA_NOME=rotina.nome,
        ROTINA_EXECUCAO=execucao_id,
        BACKUPS_DIR=str(config.backups_dir),
    )
    return env


def _ids(contexto) -> tuple[str, str]:
    ti = contexto["ti"]
    return ti.dag_id, ti.run_id


def _carregar(nome: str, config: Config) -> Rotina:
    rotinas, erros = carregar_rotinas(config.rotinas_dir, config.scripts_dir)
    for r in rotinas:
        if r.nome == nome:
            return r
    detalhe = erros.get(f"{nome}.yaml", "")
    raise FalhaRotina(f"Rotina '{nome}' não encontrada ou inválida" + (f": {detalhe}" if detalhe else ""), [])


def _executar(
    nome: str,
    contexto,
    *,
    config: Config,
    obter_variavel: Callable[[str], str],
    obter_conexao: Callable[[str], Any],
    mascarar: Callable[[str], None],
    executar_fn: Callable = executar,
) -> None:
    rotina = _carregar(nome, config)
    segredos = resolver_segredos(rotina.segredos, obter_variavel, obter_conexao)
    for valor in segredos.values():
        mascarar(valor)

    chave, usuario = None, None
    try:
        conn = obter_conexao(_CONEXAO_SSH)
    except KeyError:
        conn = None
    if conn is not None:
        extra = conn.extra or {}
        if isinstance(extra, str):
            extra = json.loads(extra) if extra.strip() else {}
        chave = extra.get("private_key")
        usuario = conn.login or None
        if chave:
            mascarar(chave)
            if not chave.endswith("\n"):
                chave += "\n"

    ultimas: deque[str] = deque(maxlen=30)

    sensiveis = list(segredos.values())
    if chave:
        sensiveis += [
            l.strip() for l in chave.splitlines()
            if l.strip() and not l.strip().startswith("-----")
        ]
        sensiveis.append(chave.strip())
    sensiveis = sorted({v for v in sensiveis if v}, key=len, reverse=True)

    def redigir(texto: str) -> str:
        for v in sensiveis:
            texto = texto.replace(v, "***")
        return texto

    def log(linha: str) -> None:
        linha = redigir(linha)
        ultimas.append(linha)
        logger.info("%s", linha)

    _, run_id = _ids(contexto)
    with chave_temporaria(chave or None) as chave_path:
        env = montar_ambiente(rotina, segredos, chave_path, usuario, config, run_id)
        try:
            executar_fn(
                Path(config.scripts_dir) / rotina.script, rotina.argumentos, env,
                rotina.timeout_min * 60, log,
            )
        except ErroExecucao as e:
            raise FalhaRotina(redigir(str(e)), list(ultimas)) from e


def executar_rotina(nome: str, contexto: dict) -> None:
    """Chamada pelo DAG (PythonOperator). Liga as funções reais do Airflow."""
    from airflow.exceptions import AirflowNotFoundException
    from airflow.sdk import Connection, Variable
    from airflow.sdk.exceptions import AirflowRuntimeError, ErrorType
    from airflow.sdk.log import mask_secret

    def obter_variavel(chave: str) -> str:
        try:
            return Variable.get(chave)
        except AirflowRuntimeError as e:
            if e.error.error == ErrorType.VARIABLE_NOT_FOUND:
                raise KeyError(chave) from None
            raise

    def obter_conexao(conn_id: str):
        try:
            return Connection.get(conn_id)
        except AirflowNotFoundException:
            raise KeyError(conn_id) from None

    _executar(
        nome, contexto, config=carregar_config(),
        obter_variavel=obter_variavel, obter_conexao=obter_conexao, mascarar=mask_secret,
    )


def _ao_falhar(contexto, *, config: Config, enviar_fn: Callable = enviar,
               agora: Callable[[], datetime] = lambda: datetime.now(_FUSO)) -> None:
    try:
        dag_id, run_id = _ids(contexto)
        exc = contexto.get("exception")
        if isinstance(exc, FalhaRotina):
            erro, linhas = exc.mensagem, exc.ultimas_linhas
        else:
            erro, linhas = str(exc), []

        avisar, destinatarios = True, list(config.aviso_destinatarios)
        try:
            rotina = _carregar(dag_id, config)
            avisar = rotina.avisar_falha
            destinatarios = list(rotina.emails_aviso) or destinatarios
        except Exception:
            logger.exception("Não foi possível reler a rotina %s; usando destinatários padrão", dag_id)
        if not avisar:
            return

        link = f"{config.ui_url}/dags/{dag_id}/runs/{quote(run_id, safe='')}"
        assunto, corpo = montar_aviso_falha(dag_id, agora(), erro, linhas, link)
        enviar_fn(config, assunto, corpo, destinatarios)
    except Exception:
        logger.exception("Falha ao enviar o aviso de falha da rotina")


def ao_falhar(contexto: dict) -> None:
    """on_failure_callback: nunca levanta, para não mascarar a falha original."""
    try:
        config = carregar_config()
    except Exception:
        logger.exception("Configuração inválida; aviso de falha não enviado")
        return
    _ao_falhar(contexto, config=config)
