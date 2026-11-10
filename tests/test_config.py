from pathlib import Path

import pytest

from rotinas_core.config import carregar_config


def test_carregar_config_le_valores_e_padroes():
    env = {"ROTINAS_DIR": "/d/rotinas", "SCRIPTS_DIR": "/d/scripts", "DADOS_DIR": "/d",
           "SSH_KNOWN_HOSTS": "/s/kh", "ROTINAS_LIB": "/l", "BACKUPS_DIR": "/b",
           "SMTP_HOST": "mailpit", "SMTP_PORTA": "1025", "SMTP_TLS": "false",
           "SMTP_REMETENTE": "airflow@cta", "AVISO_DESTINATARIOS": "a@x, b@x",
           "AIRFLOW_API_URL": "http://api:8080", "AIRFLOW_API_USUARIO": "svc",
           "AIRFLOW_API_SENHA": "s", "AIRFLOW_UI_URL": "http://vm:8080"}
    c = carregar_config(env)
    assert c.rotinas_dir == Path("/d/rotinas")
    assert c.smtp_porta == 1025 and c.smtp_tls is False
    assert c.aviso_destinatarios == ["a@x", "b@x"]
    assert c.smtp_usuario is None


def test_carregar_config_falta_variavel_obrigatoria():
    with pytest.raises(KeyError):
        carregar_config({})
