"""Execução de scripts de rotinas (Python puro, Linux; sem imports do Airflow)."""
from __future__ import annotations

import os
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

ESPERA_TERM_S = 10
MAX_LINHA = 64 * 1024


class ErroExecucao(Exception):
    pass


class SemShebang(ErroExecucao):
    pass


class TempoEsgotado(ErroExecucao):
    pass


class CodigoSaidaNaoZero(ErroExecucao):
    def __init__(self, codigo: int, mensagem: str):
        super().__init__(mensagem)
        self.codigo = codigo


def _msg_timeout(timeout_s: int) -> str:
    if timeout_s % 60 == 0:
        return f"Tempo limite de {timeout_s // 60} min excedido"
    return f"Tempo limite de {timeout_s} s excedido"


def _membros_vivos(pgid: int) -> bool:
    """Há algum processo não-zumbi no grupo? (zumbis não reaped não contam)"""
    for entrada in os.scandir("/proc"):
        if not entrada.name.isdigit():
            continue
        try:
            resto = Path(entrada.path, "stat").read_text().rsplit(")", 1)[1].split()
        except (OSError, IndexError):
            continue
        if resto[0] != "Z" and int(resto[2]) == pgid:
            return True
    return False


def _matar_grupo(pgid: int) -> None:
    """SIGTERM ao grupo, espera até 10 s e SIGKILL no que sobrar."""
    if not _membros_vivos(pgid):
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    fim = time.monotonic() + ESPERA_TERM_S
    while time.monotonic() < fim and _membros_vivos(pgid):
        time.sleep(0.1)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _ler(pipe, log: Callable[[str], None], erros: list) -> None:
    """Lê incrementalmente; linhas maiores que MAX_LINHA são fatiadas."""
    try:
        for bruta in iter(lambda: pipe.readline(MAX_LINHA), b""):
            texto = bruta.decode("utf-8", errors="replace").rstrip("\r\n")
            try:
                log(texto)
            except Exception as exc:  # não deixa o pipe encher e travar o script
                erros.append(exc)
                log = lambda _: None  # noqa: E731
    except (OSError, ValueError):
        pass


def _descrever_saida(rc: int) -> str:
    if rc < 0:
        try:
            nome = signal.Signals(-rc).name
        except ValueError:
            nome = str(-rc)
        return f"O script foi encerrado pelo sinal {nome} ({-rc})"
    return f"O script terminou com código de saída {rc}"


def executar(
    script: Path,
    argumentos: Sequence[str],
    env: Mapping[str, str],
    timeout_s: int,
    log: Callable[[str], None],
) -> None:
    with open(script, "rb") as f:
        if f.read(2) != b"#!":
            raise SemShebang("O script precisa começar com #! (ex.: #!/bin/bash)")

    pasta = Path(tempfile.mkdtemp(prefix="rotina-"))
    try:
        os.chmod(pasta, 0o700)
        copia = pasta / Path(script).name
        shutil.copyfile(script, copia)
        os.chmod(copia, stat.S_IRWXU)

        ambiente = {k: os.environ[k] for k in ("PATH", "HOME", "LANG") if k in os.environ}
        ambiente.update(env)

        proc = subprocess.Popen(
            [str(copia), *argumentos],
            cwd=pasta,
            env=ambiente,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        erros: list = []
        leitor = threading.Thread(target=_ler, args=(proc.stdout, log, erros), daemon=True)
        leitor.start()

        estourou = False
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            estourou = True
        finally:
            # líder terminou (ou estourou): nada pode sobrar no grupo
            _matar_grupo(proc.pid)
            proc.wait()
            leitor.join(5)  # se algo fugiu do grupo e segura o pipe, paramos de esperar
            if not leitor.is_alive():
                proc.stdout.close()

        if estourou:
            raise TempoEsgotado(_msg_timeout(timeout_s))
        if proc.returncode != 0:
            raise CodigoSaidaNaoZero(proc.returncode, _descrever_saida(proc.returncode))
        if erros:
            raise erros[0]
    finally:
        shutil.rmtree(pasta, ignore_errors=True)
