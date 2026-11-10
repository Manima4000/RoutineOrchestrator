import json
import smtplib
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from rotinas_core import notificacao
from rotinas_core.config import Config

MANAUS = ZoneInfo("America/Manaus")


def _config(**extra) -> Config:
    base = dict(
        rotinas_dir=Path("/r"), scripts_dir=Path("/s"), dados_dir=Path("/d"),
        known_hosts=Path("/k"), lib_dir=Path("/l"), backups_dir=Path("/b"),
        smtp_host="smtp.exemplo", smtp_porta=587, smtp_tls=False,
        smtp_usuario=None, smtp_senha=None, smtp_remetente="rotinas@exemplo.com",
        aviso_destinatarios=["a@exemplo.com"],
        api_url="http://x", api_usuario="u", api_senha="s", ui_url="http://ui",
    )
    base.update(extra)
    return Config(**base)


class FakeSMTP:
    instancias: list["FakeSMTP"] = []

    def __init__(self, host, porta, timeout=None):
        self.host, self.porta, self.timeout = host, porta, timeout
        self.chamadas: list[str] = []
        self.mensagem = None
        FakeSMTP.instancias.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, *a, **k):
        self.chamadas.append("starttls")

    def login(self, usuario, senha):
        self.chamadas.append(f"login:{usuario}:{senha}")

    def send_message(self, msg):
        self.mensagem = msg
        self.chamadas.append("send")


@pytest.fixture
def fake(monkeypatch):
    FakeSMTP.instancias = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


def test_aviso_falha_assunto_e_corpo():
    quando = datetime(2026, 11, 10, 14, 5, tzinfo=MANAUS)
    linhas = [f"linha {i}" for i in range(1, 41)]
    assunto, corpo = notificacao.montar_aviso_falha(
        "backup_banco", quando, "código de saída 2", linhas, "http://ui/log/1")
    assert assunto == "[Rotinas] FALHA: backup_banco"
    assert "backup_banco" in corpo
    assert "10/11/2026 14:05" in corpo
    assert "código de saída 2" in corpo
    assert "http://ui/log/1" in corpo
    assert "linha 40" in corpo and "linha 11" in corpo
    assert "linha 10\n" not in corpo and "linha 1\n" not in corpo


def test_aviso_falha_converte_fuso():
    quando = datetime(2026, 11, 10, 18, 30, tzinfo=timezone.utc)  # 14:30 em Manaus
    _, corpo = notificacao.montar_aviso_falha("rot", quando, "e", [], "l")
    assert "10/11/2026 14:30" in corpo


def test_aviso_vigia():
    assunto, corpo = notificacao.montar_aviso_vigia(["rotina x parada", "y"], ["z"])
    assert assunto == "[Rotinas] Vigia: 2 problema(s), 1 resolvido(s)"
    assert "Novos problemas:" in corpo and "rotina x parada" in corpo
    assert "Resolvidos:" in corpo and "z" in corpo


def test_aviso_vigia_omite_secao_vazia():
    _, corpo = notificacao.montar_aviso_vigia(["a"], [])
    assert "Resolvidos:" not in corpo
    _, corpo = notificacao.montar_aviso_vigia([], ["b"])
    assert "Novos problemas:" not in corpo


def test_enviar_sem_tls_nem_login(fake):
    notificacao.enviar(_config(), "Assunto ç", "Corpo ã", ["a@x.com", "b@x.com"])
    s = fake.instancias[0]
    assert (s.host, s.porta, s.timeout) == ("smtp.exemplo", 587, 30)
    assert s.chamadas == ["send"]
    assert s.mensagem["From"] == "rotinas@exemplo.com"
    assert s.mensagem["To"] == "a@x.com, b@x.com"
    assert s.mensagem["Subject"] == "Assunto ç"
    assert "Corpo ã" in s.mensagem.get_content()


def test_enviar_com_tls_e_login(fake):
    cfg = _config(smtp_tls=True, smtp_usuario="u", smtp_senha="p")
    notificacao.enviar(cfg, "a", "b", ["a@x.com"])
    assert fake.instancias[0].chamadas == ["starttls", "login:u:p", "send"]


def test_enviar_sem_destinatarios_nao_conecta(fake, caplog):
    with caplog.at_level("WARNING"):
        notificacao.enviar(_config(), "a", "b", [])
    assert fake.instancias == []
    assert caplog.records


def test_enviar_propaga_erro_smtp(monkeypatch):
    def falha(*a, **k):
        raise smtplib.SMTPConnectError(421, "fora")
    monkeypatch.setattr(smtplib, "SMTP", falha)
    with pytest.raises(smtplib.SMTPException):
        notificacao.enviar(_config(), "a", "b", ["a@x.com"])


@pytest.mark.integracao
def test_enviar_para_mailpit():
    nome = f"rot_{uuid.uuid4().hex[:8]}"
    cfg = _config(smtp_host="mailpit", smtp_porta=1025)
    assunto, corpo = notificacao.montar_aviso_falha(
        nome, datetime.now(MANAUS), "erro ç", ["l1"], "http://ui/x")
    notificacao.enviar(cfg, assunto, corpo, ["dest@exemplo.com"])
    q = urllib.parse.quote(nome)
    with urllib.request.urlopen(f"http://mailpit:8025/api/v1/search?query=subject:{q}") as r:
        dados = json.load(r)
    assert any(nome in m["Subject"] for m in dados["messages"])
