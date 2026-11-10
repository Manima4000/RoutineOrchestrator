"""Vigia: detecta rotinas que deveriam ter rodado e não rodaram, e divergências de estado."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from croniter import croniter

from .api_airflow import EstadoDag
from .modelo import Rotina
from .notificacao import montar_aviso_vigia

FUSO = ZoneInfo("America/Manaus")
MARGEM_SCHEDULER_MIN = 5
CARENCIA_DAG_NOVO_MIN = 10  # tempo para o dag-processor ler um YAML recém-criado


@dataclass(frozen=True)
class Problema:
    chave: str
    mensagem: str


def _tolerancia(r: Rotina) -> timedelta:
    return timedelta(minutes=r.timeout_min + r.tentativas * r.intervalo_tentativa_min + MARGEM_SCHEDULER_MIN)


def _referencia(r: Rotina) -> datetime | None:
    if not r.atualizado_em:
        return None
    try:
        t = datetime.fromisoformat(r.atualizado_em)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=FUSO)


def _ultimo_previsto(r: Rotina, agora: datetime) -> datetime | None:
    limite = (agora - _tolerancia(r)).astimezone(FUSO).replace(microsecond=0)
    try:
        return croniter(r.agendamento, limite + timedelta(seconds=1)).get_prev(datetime).astimezone(FUSO)
    except (ValueError, KeyError):
        return None


def _atraso(r: Rotina, e: EstadoDag, agora: datetime) -> Problema | None:
    p = _ultimo_previsto(r, agora)
    if p is None:
        return None
    ref = _referencia(r)
    if ref is not None:
        if p <= ref:
            return None
    elif not (e.tem_execucoes or e.ultima_execucao_ok is not None):
        return None
    ok = e.ultima_execucao_ok
    if ok is not None and ok >= p:
        return None
    ultima = ok.astimezone(FUSO).strftime("%d/%m/%Y %H:%M") if ok else "nunca"
    return Problema(
        f"atraso:{r.nome}",
        f"Rotina {r.nome} atrasada: esperada às {p:%H:%M} de {p:%d/%m/%Y}, última execução com sucesso: {ultima}",
    )


def avaliar(rotinas: list[Rotina], erros_yaml: dict[str, str], erros_importacao: list[str],
            estados: dict[str, EstadoDag], agora: datetime) -> list[Problema]:
    problemas = [Problema(f"yaml:{arq}", f"Arquivo {arq} inválido: {msg}") for arq, msg in erros_yaml.items()]
    for item in erros_importacao:
        arquivo, _, trace = item.partition("\n")
        ultima = (trace.strip().splitlines() or [""])[-1]
        problemas.append(Problema(f"importacao:{arquivo}", f"Erro ao importar {arquivo}: {ultima}".rstrip(": ")))
    for r in rotinas:
        e = estados.get(r.nome)
        if e is None or not e.existe:
            ref = _referencia(r)
            if ref is not None and agora - ref < timedelta(minutes=CARENCIA_DAG_NOVO_MIN):
                continue
            problemas.append(Problema(f"importacao:{r.nome}", f"DAG da rotina {r.nome} não encontrado no Airflow."))
            continue
        if r.ativa == e.pausado:
            est = "pausada" if e.pausado else "ativa"
            esp = "ativa" if r.ativa else "inativa"
            problemas.append(Problema(
                f"divergencia:{r.nome}", f"Rotina {r.nome} está {esp} no YAML, mas {est} no Airflow."))
            continue
        if r.ativa and not e.pausado and (p := _atraso(r, e, agora)):
            problemas.append(p)
    return problemas


def comparar(anteriores: set[str], atuais: list[Problema]) -> tuple[list[Problema], list[str]]:
    novos = [p for p in atuais if p.chave not in anteriores]
    ativas = {p.chave for p in atuais}
    return novos, sorted(anteriores - ativas)


def ciclo(*, rotinas: list[Rotina], erros_yaml: dict[str, str], cliente, agora: datetime,
          ler_estado: Callable[[], dict], gravar_estado: Callable[[dict], None],
          enviar: Callable[[str, str], None]) -> list[Problema]:
    """Um ciclo da vigia. Só grava o estado depois de o e-mail sair (falha de envio é refeita no próximo ciclo)."""
    estados = cliente.estados([r.nome for r in rotinas])
    atuais = avaliar(rotinas, erros_yaml, cliente.erros_importacao(), estados, agora)
    novos, resolvidos = comparar(set(ler_estado().get("chaves", [])), atuais)
    if novos or resolvidos:
        assunto, corpo = montar_aviso_vigia([p.mensagem for p in novos], resolvidos)
        enviar(assunto, corpo)
    gravar_estado({"chaves": sorted(p.chave for p in atuais)})
    return atuais
