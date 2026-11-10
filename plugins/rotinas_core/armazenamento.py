"""Repositório de rotinas: YAMLs + scripts no diretório de dados, com Git e auditoria."""
from __future__ import annotations

import fcntl
import json
import logging
import os
import re
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from rotinas_core.modelo import RE_NOME, Rotina, RotinaInvalida, carregar_rotinas, validar

LIMITE_SCRIPT = 1024 * 1024
IGNORADOS = ("auditoria.log", ".lock")


class ErroRepositorio(RuntimeError):
    """Falha ao gravar ou versionar (ex.: erro do git)."""


@dataclass
class ArquivoEnviado:
    nome_arquivo: str
    conteudo: bytes


def _agora() -> str:
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Manaus")
    except Exception:  # sem tzdata: Manaus é UTC-4 fixo
        tz = timezone(timedelta(hours=-4))
    return datetime.now(tz).isoformat(timespec="seconds")


def _sanear_nome(nome_arquivo: str) -> str:
    base = re.split(r"[\\/]", nome_arquivo or "")[-1]
    limpo = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    if not limpo or limpo.startswith("."):
        raise RotinaInvalida({"script": "Nome de arquivo inválido para o script"})
    return limpo


def _preparar_script(arq: ArquivoEnviado) -> bytes:
    c = arq.conteudo
    if len(c) > LIMITE_SCRIPT:
        raise RotinaInvalida({"script": "O script excede 1 MB"})
    try:
        c.decode("utf-8")
    except UnicodeDecodeError:
        c = None
    if c is None or b"\x00" in c:
        raise RotinaInvalida({"script": "O arquivo enviado não parece ser um script de texto"})
    if not c.startswith(b"#!"):
        raise RotinaInvalida({"script": "O script precisa começar com #! (ex.: #!/bin/bash)"})
    return c.replace(b"\r\n", b"\n")


class _Transacao:
    """Grava arquivos de forma atômica e sabe desfazer tudo se algo falhar."""

    def __init__(self):
        self._antes: dict[Path, bytes | None] = {}
        self._modos: dict[Path, int] = {}
        self._dirs: list[Path] = []

    def _guardar(self, caminho: Path):
        if caminho not in self._antes:
            if caminho.exists():
                self._antes[caminho] = caminho.read_bytes()
                self._modos[caminho] = caminho.stat().st_mode & 0o777
            else:
                self._antes[caminho] = None

    def gravar(self, caminho: Path, conteudo: bytes, modo: int = 0o640):
        self._guardar(caminho)
        faltando = [p for p in reversed(caminho.parents) if not p.exists()]
        caminho.parent.mkdir(parents=True, exist_ok=True)
        self._dirs.extend(faltando)
        fd, tmp = tempfile.mkstemp(dir=caminho.parent, prefix=f".{caminho.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(conteudo)
            os.chmod(tmp, modo)
            os.replace(tmp, caminho)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def remover(self, caminho: Path):
        self._guardar(caminho)
        caminho.unlink(missing_ok=True)

    def reverter(self):
        for caminho, conteudo in self._antes.items():
            try:
                if conteudo is None:
                    caminho.unlink(missing_ok=True)
                else:
                    caminho.parent.mkdir(parents=True, exist_ok=True)
                    caminho.write_bytes(conteudo)
                    os.chmod(caminho, self._modos[caminho])
            except OSError:
                logging.getLogger(__name__).exception("Falha ao restaurar %s", caminho)
        for d in reversed(self._dirs):
            try:
                d.rmdir()
            except OSError:
                pass


class RepositorioRotinas:
    def __init__(self, dados_dir: Path):
        self.dados_dir = Path(dados_dir)
        self.rotinas_dir = self.dados_dir / "rotinas"
        self.scripts_dir = self.dados_dir / "scripts"

    # ---- leitura ----
    def listar(self) -> tuple[list[Rotina], dict[str, str]]:
        return carregar_rotinas(self.rotinas_dir, self.scripts_dir)

    def obter(self, nome: str) -> Rotina | None:
        return next((r for r in self.listar()[0] if r.nome == nome), None)

    def scripts_existentes(self) -> list[str]:
        if not self.scripts_dir.is_dir():
            return []
        return sorted(
            p.relative_to(self.scripts_dir).as_posix()
            for p in self.scripts_dir.rglob("*") if p.is_file()
        )

    # ---- escrita ----
    def criar(self, dados: dict, script: ArquivoEnviado | None, usuario: str) -> Rotina:
        dados = dict(dados)
        nome = dados.get("nome")
        with self._operacao("Cria", nome, usuario) as tx:
            if not isinstance(nome, str) or not RE_NOME.fullmatch(nome):
                validar(dados, self.scripts_dir)  # levanta com o erro de nome
                raise RotinaInvalida({"nome": "Nome inválido"})
            if (self.rotinas_dir / f"{nome}.yaml").exists() or self.obter(nome):
                raise RotinaInvalida({"nome": "Já existe uma rotina com esse nome"})
            if script is None and not dados.get("script"):
                raise RotinaInvalida({"script": "Envie um script ou escolha um existente"})
            self._aplicar_script(tx, dados, nome, script)
            dados["criado_por"] = usuario
            return self._gravar_rotina(tx, dados)

    def atualizar(self, nome: str, dados: dict, script: ArquivoEnviado | None, usuario: str) -> Rotina:
        dados = dict(dados)
        with self._operacao("Atualiza", nome, usuario) as tx:
            atual = self._exigir(nome)
            if dados.get("nome", nome) != nome:
                raise RotinaInvalida({"nome": "Não é possível renomear uma rotina"})
            dados["nome"] = nome
            dados.setdefault("script", atual.script)
            dados.setdefault("ativa", atual.ativa)
            self._aplicar_script(tx, dados, nome, script)
            dados["criado_por"] = atual.criado_por
            nova = self._gravar_rotina(tx, dados)
            if nova.script != atual.script:
                self._remover_script_orfao(tx, atual.script, ignorar=nome)
            return nova

    def definir_ativa(self, nome: str, ativa: bool, usuario: str) -> Rotina:
        with self._operacao("Ativa" if ativa else "Desativa", nome, usuario) as tx:
            atual = self._exigir(nome)
            if atual.ativa == ativa:
                return atual
            dados = atual.para_dict()
            dados["ativa"] = ativa
            return self._gravar_rotina(tx, dados)

    def excluir(self, nome: str, usuario: str) -> None:
        with self._operacao("Exclui", nome, usuario) as tx:
            atual = self._exigir(nome)
            tx.remover(self.rotinas_dir / f"{nome}.yaml")
            self._remover_script_orfao(tx, atual.script, ignorar=nome)

    # ---- internos ----
    def _exigir(self, nome: str) -> Rotina:
        r = self.obter(nome)
        if r is None:
            raise RotinaInvalida({"nome": "Rotina não encontrada"})
        return r

    def _aplicar_script(self, tx: _Transacao, dados: dict, nome: str, script: ArquivoEnviado | None):
        if script is None:
            return
        arquivo = _sanear_nome(script.nome_arquivo)
        conteudo = _preparar_script(script)
        rel = f"rotinas/{nome}/{arquivo}"
        outra = next((r.nome for r in self.listar()[0] if r.nome != nome and r.script == rel), None)
        if outra:
            raise RotinaInvalida({
                "script": f"O arquivo {rel} é usado também pela rotina {outra}; envie com outro nome"})
        tx.gravar(self.scripts_dir / rel, conteudo, 0o750)
        dados["script"] = rel

    def _gravar_rotina(self, tx: _Transacao, dados: dict) -> Rotina:
        dados["atualizado_em"] = _agora()
        rotina = validar(dados, self.scripts_dir)
        texto = yaml.safe_dump(rotina.para_dict(), allow_unicode=True, sort_keys=False)
        tx.gravar(self.rotinas_dir / f"{rotina.nome}.yaml", texto.encode("utf-8"))
        return rotina

    def _remover_script_orfao(self, tx: _Transacao, script: str, ignorar: str):
        # só apaga scripts enviados pela interface (rotinas/...) que ninguém mais usa
        if not script.startswith("rotinas/"):
            return
        if any(r.script == script for r in self.listar()[0] if r.nome != ignorar):
            return
        alvo = self.scripts_dir / script
        if alvo.is_file():
            tx.remover(alvo)
            try:
                alvo.parent.rmdir()
            except OSError:
                pass

    @contextmanager
    def _operacao(self, acao: str, nome, usuario: str):
        self.dados_dir.mkdir(parents=True, exist_ok=True)
        with open(self.dados_dir / ".lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                tx = _Transacao()
                try:
                    yield tx
                    if tx._antes:
                        self._versionar(acao, nome, usuario)
                except BaseException:
                    tx.reverter()
                    self._git("reset", "-q", checar=False)
                    raise
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _git(self, *args: str, checar: bool = True, env_extra: dict | None = None):
        try:
            r = subprocess.run(
                ["git", "-c", f"safe.directory={self.dados_dir}", *args],
                cwd=self.dados_dir, capture_output=True, text=True,
                env={**os.environ, **(env_extra or {})},
            )
        except OSError as e:
            if checar:
                raise ErroRepositorio(f"Não foi possível executar o git: {e}") from e
            return None
        if checar and r.returncode != 0:
            raise ErroRepositorio(
                f"O git falhou ao executar 'git {' '.join(args)}': {(r.stderr or r.stdout).strip()}"
            )
        return r

    def _garantir_gitignore(self):
        caminho = self.dados_dir / ".gitignore"
        linhas = caminho.read_text(encoding="utf-8").splitlines() if caminho.exists() else []
        faltam = [i for i in IGNORADOS if i not in linhas]
        if faltam:
            caminho.write_text("\n".join(linhas + faltam) + "\n", encoding="utf-8")

    def _versionar(self, acao: str, nome: str, usuario: str):
        self._garantir_gitignore()
        self._git("add", "-A")
        if self._git("diff", "--cached", "--quiet", checar=False).returncode == 0:
            return  # nada a commitar: sem commit e sem auditoria
        ident = self._git("config", "user.name", checar=False)
        env = {}
        if ident is None or not ident.stdout.strip():
            env = {"GIT_COMMITTER_NAME": "Airflow Rotinas", "GIT_COMMITTER_EMAIL": "rotinas@airflow"}
        self._git("commit", "-q", "--author", f"{usuario} <{usuario}@airflow>",
                  "-m", f"{acao} rotina {nome}", env_extra=env)
        linha = {"quando": _agora(), "usuario": usuario, "acao": acao, "rotina": nome}
        with open(self.dados_dir / "auditoria.log", "a", encoding="utf-8") as f:
            f.write(json.dumps(linha, ensure_ascii=False) + "\n")
