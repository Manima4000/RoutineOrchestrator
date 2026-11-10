"""Agendamento: presets amigáveis, descrição em português e próximas execuções."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from croniter import croniter

FUSO = ZoneInfo("America/Manaus")
PRESETS = ("@hourly", "@daily", "@weekly", "@monthly")

_DIAS_SEMANA = (
    "domingo",
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
)
_PRESET_PARA_CRON = {
    "@daily": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
}


def cron_valido(expr: str) -> bool:
    """Aceita só cron padrão de 5 campos ou um dos presets (@hourly, @daily, @weekly, @monthly)."""
    if not isinstance(expr, str):
        return False
    if expr in PRESETS:
        return True
    return len(expr.split()) == 5 and croniter.is_valid(expr)


def _intervalo(nome: str, valor: int | None, minimo: int, maximo: int) -> int:
    if valor is None:
        raise ValueError(f"{nome} é obrigatório para este tipo de agendamento.")
    if isinstance(valor, bool) or not isinstance(valor, int) or not minimo <= valor <= maximo:
        raise ValueError(f"{nome} deve estar entre {minimo} e {maximo}.")
    return valor


def preset_para_cron(
    tipo: Literal["diario", "semanal", "mensal"],
    hora: int,
    minuto: int,
    dia_semana: int | None = None,
    dia_mes: int | None = None,
) -> str:
    hora = _intervalo("Hora", hora, 0, 23)
    minuto = _intervalo("Minuto", minuto, 0, 59)
    if tipo == "diario":
        return f"{minuto} {hora} * * *"
    if tipo == "semanal":
        dia_semana = _intervalo("Dia da semana", dia_semana, 0, 6)
        return f"{minuto} {hora} * * {dia_semana}"
    if tipo == "mensal":
        dia_mes = _intervalo("Dia do mês", dia_mes, 1, 28)
        return f"{minuto} {hora} {dia_mes} * *"
    raise ValueError("Tipo de agendamento inválido (use diario, semanal ou mensal).")


def _num(texto: str, minimo: int, maximo: int) -> int | None:
    if texto.isascii() and texto.isdigit() and minimo <= int(texto) <= maximo:
        return int(texto)
    return None


def cron_para_preset(expr: str) -> dict | None:
    """Inverso de preset_para_cron; None se a expressão não tiver exatamente essa forma."""
    if not isinstance(expr, str):
        return None
    expr = _PRESET_PARA_CRON.get(expr, expr)
    campos = expr.split()
    if len(campos) != 5:
        return None
    minuto, hora, dia_mes, mes, dia_semana = campos
    m, h = _num(minuto, 0, 59), _num(hora, 0, 23)
    if m is None or h is None or mes != "*":
        return None
    base = {"hora": h, "minuto": m}
    if dia_mes == "*" and dia_semana == "*":
        return {"tipo": "diario", **base}
    if dia_mes == "*":
        d = _num(dia_semana, 0, 6)
        return None if d is None else {"tipo": "semanal", **base, "dia_semana": d}
    if dia_semana == "*":
        d = _num(dia_mes, 1, 28)
        return None if d is None else {"tipo": "mensal", **base, "dia_mes": d}
    return None


def descrever(expr: str) -> str:
    if expr == "@hourly":
        return "De hora em hora"
    campos = expr.split() if isinstance(expr, str) else []
    if len(campos) == 5 and campos[4] == "7":  # 7 também é domingo
        campos[4] = "0"
    p = cron_para_preset(" ".join(campos))
    if p is None:
        return f"Cron: {expr}"
    hhmm = f"{p['hora']:02d}:{p['minuto']:02d}"
    if p["tipo"] == "diario":
        return f"Diário às {hhmm}"
    if p["tipo"] == "semanal":
        return f"Semanal, {_DIAS_SEMANA[p['dia_semana']]} às {hhmm}"
    return f"Mensal, dia {p['dia_mes']} às {hhmm}"


def proximas(expr: str, n: int, agora: datetime) -> list[datetime]:
    if not cron_valido(expr):
        raise ValueError(f"Agendamento inválido: {expr!r}.")
    if agora.tzinfo is None or agora.utcoffset() is None:
        raise ValueError("'agora' deve ter fuso horário.")
    it = croniter(expr, agora.astimezone(FUSO))
    return [it.get_next(datetime).astimezone(FUSO) for _ in range(n)]
