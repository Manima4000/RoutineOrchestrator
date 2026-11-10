"""Notificação por e-mail. Só `enviar` conhece SMTP (ponto único para outros canais)."""
import logging
import smtplib
from datetime import datetime
from email.message import EmailMessage
from typing import Sequence
from zoneinfo import ZoneInfo

from .config import Config

log = logging.getLogger(__name__)

_FUSO = ZoneInfo("America/Manaus")
_MAX_LINHAS = 30
_TIMEOUT_SMTP = 30


def enviar(config: Config, assunto: str, corpo: str, destinatarios: Sequence[str]) -> None:
    """Envia e-mail em texto. Erros de SMTP se propagam; o chamador decide."""
    if not destinatarios:
        log.warning("Nenhum destinatário configurado; e-mail não enviado: %s", assunto)
        return
    msg = EmailMessage()
    msg["From"] = config.smtp_remetente
    msg["To"] = ", ".join(destinatarios)
    msg["Subject"] = assunto
    msg.set_content(corpo, charset="utf-8")
    with smtplib.SMTP(config.smtp_host, config.smtp_porta, timeout=_TIMEOUT_SMTP) as smtp:
        if config.smtp_tls:
            smtp.starttls()
        if config.smtp_usuario:
            smtp.login(config.smtp_usuario, config.smtp_senha or "")
        smtp.send_message(msg)


def montar_aviso_falha(nome: str, quando: datetime, erro: str,
                       ultimas_linhas: Sequence[str], link_log: str) -> tuple[str, str]:
    if quando.tzinfo is not None:
        quando = quando.astimezone(_FUSO)
    linhas = list(ultimas_linhas)[-_MAX_LINHAS:]
    corpo = (
        f"A rotina {nome} falhou.\n\n"
        f"Quando: {quando.strftime('%d/%m/%Y %H:%M')}\n"
        f"Erro: {erro}\n\n"
        f"Últimas linhas do log:\n"
        + "\n".join(linhas)
        + f"\n\nLog completo: {link_log}\n"
    )
    return f"[Rotinas] FALHA: {nome}", corpo


def montar_aviso_vigia(novos: Sequence[str], resolvidos: Sequence[str]) -> tuple[str, str]:
    assunto = f"[Rotinas] Vigia: {len(novos)} problema(s), {len(resolvidos)} resolvido(s)"
    secoes = []
    if novos:
        secoes.append("Novos problemas:\n" + "\n".join(f"- {p}" for p in novos))
    if resolvidos:
        secoes.append("Resolvidos:\n" + "\n".join(f"- {r}" for r in resolvidos))
    return assunto, "\n\n".join(secoes) + "\n"
