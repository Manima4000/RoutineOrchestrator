from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from rotinas_core.agenda import (
    cron_para_preset,
    cron_valido,
    descrever,
    preset_para_cron,
    proximas,
)

MANAUS = ZoneInfo("America/Manaus")


def test_presets():
    assert preset_para_cron("diario", 2, 0) == "0 2 * * *"
    assert preset_para_cron("semanal", 23, 30, dia_semana=0) == "30 23 * * 0"
    assert preset_para_cron("mensal", 3, 15, dia_mes=1) == "15 3 1 * *"
    with pytest.raises(ValueError):
        preset_para_cron("mensal", 3, 0, dia_mes=31)


@pytest.mark.parametrize(
    "args",
    [
        ("diario", 24, 0, None, None),
        ("diario", -1, 0, None, None),
        ("diario", 0, 60, None, None),
        ("semanal", 0, 0, None, None),
        ("semanal", 0, 0, 7, None),
        ("mensal", 0, 0, None, None),
        ("mensal", 0, 0, None, 0),
        ("anual", 0, 0, None, None),
    ],
)
def test_preset_invalido(args):
    tipo, hora, minuto, ds, dm = args
    with pytest.raises(ValueError):
        preset_para_cron(tipo, hora, minuto, dia_semana=ds, dia_mes=dm)


def test_ida_e_volta():
    assert cron_para_preset("30 23 * * 0") == {"tipo": "semanal", "hora": 23, "minuto": 30, "dia_semana": 0}
    assert cron_para_preset("0 2 * * *") == {"tipo": "diario", "hora": 2, "minuto": 0}
    assert cron_para_preset("15 3 1 * *") == {"tipo": "mensal", "hora": 3, "minuto": 15, "dia_mes": 1}
    assert cron_para_preset("*/5 * * * *") is None
    assert cron_para_preset("15 3 31 * *") is None
    assert cron_para_preset("0 2 * * 1-5") is None
    assert cron_para_preset("0 2 * * 7") is None
    assert cron_para_preset("0 99 * * *") is None
    assert cron_para_preset("@daily") == {"tipo": "diario", "hora": 0, "minuto": 0}
    assert cron_para_preset("@weekly") == {"tipo": "semanal", "hora": 0, "minuto": 0, "dia_semana": 0}
    assert cron_para_preset("@monthly") == {"tipo": "mensal", "hora": 0, "minuto": 0, "dia_mes": 1}
    assert cron_para_preset("@hourly") is None


def test_cron_valido():
    assert cron_valido("0 2 * * *")
    assert cron_valido("@hourly")
    assert not cron_valido("@yearly")
    assert not cron_valido("isso nao e cron")
    assert not cron_valido("0 0 2 * * *")  # 6 campos
    assert not cron_valido("0 0 2 * * * 2026")  # 7 campos
    assert not cron_valido("")
    assert not cron_valido("61 * * * *")


def test_descrever():
    assert descrever("0 2 * * *") == "Diário às 02:00"
    assert descrever("30 23 * * 0") == "Semanal, domingo às 23:30"
    assert descrever("15 3 1 * *") == "Mensal, dia 1 às 03:15"
    assert descrever("@daily") == "Diário às 00:00"
    assert descrever("@hourly") == "De hora em hora"
    assert descrever("@weekly") == "Semanal, domingo às 00:00"
    assert descrever("@monthly") == "Mensal, dia 1 às 00:00"
    assert descrever("*/5 * * * *") == "Cron: */5 * * * *"
    assert descrever("0 8 * * 1") == "Semanal, segunda-feira às 08:00"
    assert descrever("0 8 * * 6") == "Semanal, sábado às 08:00"


def test_proximas_em_manaus():
    agora = datetime(2026, 11, 10, 12, 0, tzinfo=MANAUS)
    p = proximas("0 2 * * *", 2, agora)
    assert p[0] == datetime(2026, 11, 11, 2, 0, tzinfo=MANAUS)
    assert p[1] == datetime(2026, 11, 12, 2, 0, tzinfo=MANAUS)
    assert len(p) == 2
    assert all(d.tzinfo is not None and d.utcoffset().total_seconds() == -4 * 3600 for d in p)


def test_proximas_converte_fuso_e_presets():
    agora = datetime(2026, 11, 10, 16, 0, tzinfo=ZoneInfo("UTC"))  # 12:00 em Manaus
    p = proximas("@daily", 1, agora)
    assert p == [datetime(2026, 11, 11, 0, 0, tzinfo=MANAUS)]


def test_proximas_erros():
    agora = datetime(2026, 11, 10, 12, 0, tzinfo=MANAUS)
    with pytest.raises(ValueError):
        proximas("lixo", 1, agora)
    with pytest.raises(ValueError):
        proximas("0 2 * * *", 1, datetime(2026, 11, 10, 12, 0))
