"""Configuração do ambiente de rotinas, lida das variáveis de ambiente."""
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class Config:
    rotinas_dir: Path
    scripts_dir: Path
    dados_dir: Path
    known_hosts: Path
    lib_dir: Path
    backups_dir: Path
    smtp_host: str
    smtp_porta: int
    smtp_tls: bool
    smtp_usuario: str | None
    smtp_senha: str | None
    smtp_remetente: str
    aviso_destinatarios: list[str]
    api_url: str
    api_usuario: str
    api_senha: str
    ui_url: str


def _opcional(env: Mapping[str, str], chave: str) -> str | None:
    return env.get(chave) or None


def carregar_config(env: Mapping[str, str] = os.environ) -> Config:
    """Lê a configuração; levanta KeyError se faltar variável obrigatória."""
    return Config(
        rotinas_dir=Path(env["ROTINAS_DIR"]),
        scripts_dir=Path(env["SCRIPTS_DIR"]),
        dados_dir=Path(env["DADOS_DIR"]),
        known_hosts=Path(env["SSH_KNOWN_HOSTS"]),
        lib_dir=Path(env["ROTINAS_LIB"]),
        backups_dir=Path(env["BACKUPS_DIR"]),
        smtp_host=env["SMTP_HOST"],
        smtp_porta=int(env["SMTP_PORTA"]),
        smtp_tls=env["SMTP_TLS"].strip().lower() in ("1", "true", "sim", "yes"),
        smtp_usuario=_opcional(env, "SMTP_USUARIO"),
        smtp_senha=_opcional(env, "SMTP_SENHA"),
        smtp_remetente=env["SMTP_REMETENTE"],
        aviso_destinatarios=[e.strip() for e in env["AVISO_DESTINATARIOS"].split(",") if e.strip()],
        api_url=env["AIRFLOW_API_URL"].rstrip("/"),
        api_usuario=env["AIRFLOW_API_USUARIO"],
        api_senha=env["AIRFLOW_API_SENHA"],
        ui_url=env["AIRFLOW_UI_URL"].rstrip("/"),
    )
