from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from rotinas_core.api_airflow import EstadoDag
from rotinas_core.modelo import Rotina
from rotinas_core.vigia import Problema, avaliar, comparar, ciclo

MAO = ZoneInfo("America/Manaus")
AGORA = datetime(2026, 11, 10, 12, 0, tzinfo=MAO)


def rot(nome="r", **kw):
    return Rotina(nome=nome, agendamento="0 2 * * *", script="a.sh", **kw)


def chaves(p):
    return [x.chave for x in p]


def test_sem_problemas():
    est = {"r": EstadoDag(False, AGORA.replace(hour=2, minute=1), True)}
    assert avaliar([rot()], {}, [], est, AGORA) == []


def test_atraso_quando_ultima_ok_antes_do_previsto():
    est = {"r": EstadoDag(False, AGORA - timedelta(days=1, hours=10), True)}
    p = avaliar([rot()], {}, [], est, AGORA)
    assert chaves(p) == ["atraso:r"]
    assert "esperada às 02:00 de 10/11/2026" in p[0].mensagem
    assert "r atrasada" in p[0].mensagem


def test_atraso_mensagem_nunca():
    p = avaliar([rot()], {}, [], {"r": EstadoDag(False, None, True, True)}, AGORA)
    assert chaves(p) == ["atraso:r"] and p[0].mensagem.endswith("última execução com sucesso: nunca")


def test_sem_atraso_dentro_da_tolerancia():
    agora = AGORA.replace(hour=2, minute=30)  # tolerância 60+5+5 min
    ontem = EstadoDag(False, agora - timedelta(days=1) - timedelta(minutes=29), True, True)
    assert avaliar([rot()], {}, [], {"r": ontem}, agora) == []


def test_atraso_apos_tolerancia():
    agora = AGORA.replace(hour=3, minute=16)
    est = {"r": EstadoDag(False, None, True, True)}
    assert chaves(avaliar([rot()], {}, [], est, agora)) == ["atraso:r"]


def test_tolerancia_inclui_tentativas():
    r = rot(tentativas=2, intervalo_tentativa_min=10)  # 60+20+5 = 85 min
    est = {"r": EstadoDag(False, AGORA.replace(hour=2, minute=1) - timedelta(days=1), True, True)}
    assert avaliar([r], {}, [], est, AGORA.replace(hour=3, minute=20)) == []
    assert chaves(avaliar([r], {}, [], est, AGORA.replace(hour=3, minute=26))) == ["atraso:r"]


def test_sem_disparo_desde_a_criacao_nao_gera_atraso():
    r = rot(atualizado_em="2026-11-10T09:00:00-04:00")  # depois do disparo das 02:00
    assert avaliar([r], {}, [], {"r": EstadoDag(False, None, True, True)}, AGORA) == []


def test_disparo_depois_da_criacao_gera_atraso():
    r = rot(atualizado_em="2026-11-09T09:00:00-04:00")
    assert chaves(avaliar([r], {}, [], {"r": EstadoDag(False, None, True, True)}, AGORA)) == ["atraso:r"]


def test_sem_referencia_e_sem_execucoes_nao_gera_atraso():
    assert avaliar([rot()], {}, [], {"r": EstadoDag(False, None, True, False)}, AGORA) == []


def test_pausada_inativa_nao_gera_atraso_nem_divergencia():
    est = {"r": EstadoDag(True, None, True, True)}
    assert avaliar([rot(ativa=False)], {}, [], est, AGORA) == []


def test_ativa_pausada_diverge_e_nao_atrasa():
    est = {"r": EstadoDag(True, None, True, True)}
    assert chaves(avaliar([rot()], {}, [], est, AGORA)) == ["divergencia:r"]


def test_inativa_rodando_diverge():
    est = {"r": EstadoDag(False, AGORA, True, True)}
    assert chaves(avaliar([rot(ativa=False)], {}, [], est, AGORA)) == ["divergencia:r"]


def test_dag_inexistente_e_problema_de_importacao():
    est = {"r": EstadoDag(False, None, False, False)}
    p = avaliar([rot()], {}, [], est, AGORA)
    assert chaves(p) == ["importacao:r"] and "DAG" in p[0].mensagem and "não encontrado" in p[0].mensagem


def test_erros_yaml_e_importacao():
    p = avaliar([], {"b.yaml": "campo x"}, ["dags/x.py\nTraceback\nValueError: ruim"], {}, AGORA)
    assert chaves(p) == ["yaml:b.yaml", "importacao:dags/x.py"]
    assert "campo x" in p[0].mensagem and "ValueError: ruim" in p[1].mensagem


def test_comparar():
    novos, resolvidos = comparar({"atraso:r", "yaml:b.yaml"},
                                 [Problema("atraso:r", "..."), Problema("divergencia:s", "...")])
    assert chaves(novos) == ["divergencia:s"] and resolvidos == ["yaml:b.yaml"]


# ---- ciclo (orquestração com dependências injetadas)

class Cli:
    def __init__(self, estados, erros=()):
        self._e, self._r = estados, list(erros)

    def estados(self, ids):
        return {i: self._e[i] for i in ids}

    def erros_importacao(self):
        return self._r


def _ciclo(estado, enviados, falha=False, yaml=None):
    guardado = {}

    def enviar(assunto, corpo):
        if falha:
            raise OSError("smtp fora")
        enviados.append((assunto, corpo))

    ciclo(rotinas=[], erros_yaml=yaml or {}, cliente=Cli({}), agora=AGORA,
          ler_estado=lambda: estado, gravar_estado=lambda d: guardado.update(d), enviar=enviar)
    return guardado


def test_ciclo_envia_novo_e_guarda_estado():
    env = []
    g = _ciclo({"chaves": []}, env, yaml={"b.yaml": "ruim"})
    assert len(env) == 1 and "yaml:b.yaml" not in g.get("chaves", []) or g == {"chaves": ["yaml:b.yaml"]}
    assert g == {"chaves": ["yaml:b.yaml"]}


def test_ciclo_sem_mudanca_nao_envia():
    env = []
    g = _ciclo({"chaves": ["yaml:b.yaml"]}, env, yaml={"b.yaml": "ruim"})
    assert env == [] and g == {"chaves": ["yaml:b.yaml"]}


def test_ciclo_resolvido_envia():
    env = []
    g = _ciclo({"chaves": ["yaml:b.yaml"]}, env)
    assert len(env) == 1 and "yaml:b.yaml" in env[0][1] and g == {"chaves": []}


def test_ciclo_falha_no_envio_nao_guarda_estado():
    g = {}
    try:
        g = _ciclo({"chaves": []}, [], falha=True, yaml={"b.yaml": "ruim"})
    except OSError:
        pass
    assert g == {}
