"""Modelo da rotina e validação do YAML (Python puro, sem imports do Airflow)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from croniter import croniter

RE_NOME = re.compile(r"^[a-z0-9_]{3,64}$")
RE_SEGREDO = re.compile(r"^[A-Z_][A-Z0-9_]*$")
CAMPOS_CONEXAO = ("login", "password", "host", "port", "schema", "extra")
PRESETS = ("@hourly", "@daily", "@weekly", "@monthly")
PADROES = {
    "descricao": "",
    "ativa": True,
    "tentativas": 1,
    "intervalo_tentativa_min": 5,
    "timeout_min": 60,
    "avisar_falha": True,
}
CAMPOS_CONHECIDOS = {
    "nome", "descricao", "ativa", "agendamento", "script", "argumentos", "tentativas",
    "intervalo_tentativa_min", "timeout_min", "avisar_falha", "emails_aviso", "segredos",
    "criado_por", "atualizado_em",
}


def _cron_valido(expr: str) -> bool:
    # Task 3 move isto para agenda.cron_valido.
    return expr in PRESETS or croniter.is_valid(expr)


@dataclass(frozen=True)
class RefSegredo:
    variavel: str | None = None
    conexao: str | None = None
    campo: str | None = None

    def para_dict(self) -> dict:
        return {k: v for k, v in (("variavel", self.variavel), ("conexao", self.conexao), ("campo", self.campo)) if v is not None}


@dataclass(frozen=True)
class Rotina:
    nome: str
    agendamento: str
    script: str
    descricao: str = ""
    ativa: bool = True
    argumentos: tuple[str, ...] = ()
    tentativas: int = 1
    intervalo_tentativa_min: int = 5
    timeout_min: int = 60
    avisar_falha: bool = True
    emails_aviso: tuple[str, ...] = ()
    segredos: dict[str, RefSegredo] = field(default_factory=dict)
    criado_por: str | None = None
    atualizado_em: str | None = None

    def para_dict(self) -> dict:
        d = {
            "nome": self.nome,
            "descricao": self.descricao,
            "ativa": self.ativa,
            "agendamento": self.agendamento,
            "script": self.script,
            "argumentos": list(self.argumentos),
            "tentativas": self.tentativas,
            "intervalo_tentativa_min": self.intervalo_tentativa_min,
            "timeout_min": self.timeout_min,
            "avisar_falha": self.avisar_falha,
            "emails_aviso": list(self.emails_aviso),
            "segredos": {k: v.para_dict() for k, v in self.segredos.items()},
            "criado_por": self.criado_por,
            "atualizado_em": self.atualizado_em,
        }
        return {k: v for k, v in d.items() if v is not None}


class RotinaInvalida(Exception):
    def __init__(self, erros: dict[str, str]):
        self.erros = erros
        super().__init__("; ".join(f"{k}: {v}" for k, v in erros.items()))


def _inteiro(dados: dict, chave: str, minimo: int, erros: dict) -> int:
    v = dados.get(chave, PADROES[chave])
    if isinstance(v, bool) or not isinstance(v, int) or v < minimo:
        erros[chave] = f"Deve ser um número inteiro maior ou igual a {minimo}."
        return PADROES[chave]
    return v


def _booleano(dados: dict, chave: str, erros: dict) -> bool:
    v = dados.get(chave, PADROES[chave])
    if not isinstance(v, bool):
        erros[chave] = "Deve ser verdadeiro ou falso."
        return PADROES[chave]
    return v


def _lista_texto(dados: dict, chave: str, erros: dict) -> tuple[str, ...]:
    v = dados.get(chave, [])
    if not isinstance(v, (list, tuple)) or not all(isinstance(i, str) for i in v):
        erros[chave] = "Deve ser uma lista de textos."
        return ()
    return tuple(v)


def _segredos(dados: dict, erros: dict) -> dict[str, RefSegredo]:
    bruto = dados.get("segredos", {})
    if not isinstance(bruto, dict):
        erros["segredos"] = "Deve ser um mapa de NOME para referência."
        return {}
    problemas, saida = [], {}
    for nome, ref in bruto.items():
        if not isinstance(nome, str) or not RE_SEGREDO.match(nome):
            problemas.append(f"Nome de segredo inválido: {nome!r} (use MAIÚSCULAS, dígitos e _).")
            continue
        if not isinstance(ref, dict) or not set(ref) <= {"variavel", "conexao", "campo"}:
            problemas.append(f"{nome}: referência inválida (use variavel, ou conexao e campo).")
            continue
        var, con, campo = ref.get("variavel"), ref.get("conexao"), ref.get("campo")
        if var is not None and con is None and campo is None and isinstance(var, str) and var:
            saida[nome] = RefSegredo(variavel=var)
        elif var is None and isinstance(con, str) and con and campo in CAMPOS_CONEXAO:
            saida[nome] = RefSegredo(conexao=con, campo=campo)
        else:
            problemas.append(
                f"{nome}: informe 'variavel' ou ('conexao' e 'campo' entre {', '.join(CAMPOS_CONEXAO)})."
            )
    if problemas:
        erros["segredos"] = " ".join(problemas)
    return saida


def _checar_script(script, scripts_dir: Path, erros: dict) -> None:
    if not isinstance(script, str) or not script:
        erros["script"] = "Informe o caminho do script, relativo à pasta de scripts."
        return
    base = Path(scripts_dir).resolve()
    alvo = (base / script).resolve()
    if Path(script).is_absolute() or not alvo.is_relative_to(base):
        erros["script"] = "O script deve ficar dentro da pasta de scripts."
    elif not alvo.is_file():
        erros["script"] = f"Script não encontrado: {script}"


def validar(dados: dict, scripts_dir: Path) -> Rotina:
    """Valida os dados e devolve a Rotina; levanta RotinaInvalida com todos os erros."""
    erros: dict[str, str] = {}
    if not isinstance(dados, dict):
        raise RotinaInvalida({"campos": "O conteúdo deve ser um mapa de campos."})

    desconhecidos = sorted(str(k) for k in dados if k not in CAMPOS_CONHECIDOS)
    if desconhecidos:
        erros["campos"] = " ".join(f"Campo desconhecido: {c}" for c in desconhecidos)

    nome = dados.get("nome")
    if not isinstance(nome, str) or not RE_NOME.match(nome):
        erros["nome"] = "Use de 3 a 64 caracteres: letras minúsculas, dígitos e _."

    agendamento = dados.get("agendamento")
    if not isinstance(agendamento, str) or not _cron_valido(agendamento.strip()):
        erros["agendamento"] = "Agendamento inválido (use cron de 5 campos ou @hourly, @daily, @weekly, @monthly)."

    script = dados.get("script")
    _checar_script(script, scripts_dir, erros)

    descricao = dados.get("descricao", "")
    if not isinstance(descricao, str):
        erros["descricao"] = "Deve ser um texto."
        descricao = ""

    ativa = _booleano(dados, "ativa", erros)
    avisar = _booleano(dados, "avisar_falha", erros)
    tentativas = _inteiro(dados, "tentativas", 0, erros)
    intervalo = _inteiro(dados, "intervalo_tentativa_min", 1, erros)
    timeout = _inteiro(dados, "timeout_min", 1, erros)
    argumentos = _lista_texto(dados, "argumentos", erros)
    emails = _lista_texto(dados, "emails_aviso", erros)
    segredos = _segredos(dados, erros)

    for chave in ("criado_por", "atualizado_em"):
        v = dados.get(chave)
        if v is not None and not isinstance(v, str):
            erros[chave] = "Deve ser um texto."

    if erros:
        raise RotinaInvalida(erros)
    return Rotina(
        nome=nome, agendamento=agendamento.strip(), script=script, descricao=descricao,
        ativa=ativa, argumentos=argumentos, tentativas=tentativas,
        intervalo_tentativa_min=intervalo, timeout_min=timeout, avisar_falha=avisar,
        emails_aviso=emails, segredos=segredos,
        criado_por=dados.get("criado_por"), atualizado_em=dados.get("atualizado_em"),
    )


def carregar_rotinas(rotinas_dir: Path, scripts_dir: Path) -> tuple[list[Rotina], dict[str, str]]:
    """Lê os *.yaml da pasta; devolve (válidas ordenadas por nome, erros por arquivo)."""
    validas: dict[str, tuple[str, Rotina]] = {}
    erros: dict[str, str] = {}
    duplicados: dict[str, list[str]] = {}
    for arq in sorted(Path(rotinas_dir).glob("*.yaml")):
        try:
            dados = yaml.safe_load(arq.read_text(encoding="utf-8"))
            if not isinstance(dados, dict):
                raise RotinaInvalida({"campos": "O arquivo deve conter um mapa de campos."})
            r = validar(dados, scripts_dir)
        except RotinaInvalida as e:
            erros[arq.name] = str(e)
            continue
        except (yaml.YAMLError, OSError, UnicodeDecodeError) as e:
            erros[arq.name] = f"Não foi possível ler o arquivo: {e}"
            continue
        if r.nome in validas:
            duplicados.setdefault(r.nome, [validas[r.nome][0]]).append(arq.name)
        else:
            validas[r.nome] = (arq.name, r)
    for nome, arquivos in duplicados.items():
        del validas[nome]
        for a in arquivos:
            erros[a] = f"Nome de rotina duplicado: {nome}"
    return sorted((r for _, r in validas.values()), key=lambda r: r.nome), erros
