"""App FastAPI do plugin "Rotinas": lista, cria, edita, ativa/desativa e exclui rotinas.

Montado pelo Airflow em /rotinas-app (ver __init__.py). Toda rota exige papel Admin
(dependência global ``exigir_admin``); todo POST também passa por ``verificar_origem``.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from functools import lru_cache
from http import HTTPStatus
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from rotinas_core.agenda import FUSO, cron_para_preset, cron_valido, descrever, preset_para_cron, proximas
from rotinas_core.api_airflow import ClienteAirflow
from rotinas_core.armazenamento import LIMITE_SCRIPT, ArquivoEnviado, ErroRepositorio, RepositorioRotinas
from rotinas_core.config import carregar_config
from rotinas_core.modelo import CAMPOS_CONEXAO, PADROES, Rotina, RotinaInvalida
from rotinas_web.seguranca import exigir_admin, exigir_admin_post

log = logging.getLogger(__name__)

AVISO_PAUSA = ("Rotina salva, mas não foi possível aplicar a pausa no Airflow agora; "
               "a vigia apontará a divergência")
DIAS_SEMANA = ("domingo", "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado")
RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+$")
CAMPOS_DO_FORMULARIO = {
    "nome", "descricao", "agendamento", "script", "argumentos", "tentativas", "intervalo_tentativa_min",
    "timeout_min", "ativa", "avisar_falha", "emails_aviso", "segredos",
}

# autoescape em TODOS os templates: nomes, descrições e mensagens de erro vêm do usuário.
TEMPLATES = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"), autoescape=True)

app = FastAPI(title="Rotinas", docs_url=None, redoc_url=None, openapi_url=None,
              dependencies=[Depends(exigir_admin)])


# ---------- dependências (sobrescritas nos testes) ----------

def obter_repo() -> RepositorioRotinas:
    return RepositorioRotinas(carregar_config().dados_dir)


@lru_cache(maxsize=1)
def _cliente_cacheado(api_url: str, usuario: str, senha: str) -> ClienteAirflow:
    return ClienteAirflow(api_url, usuario, senha)  # reaproveita o token entre requisições


def obter_cliente() -> ClienteAirflow:
    c = carregar_config()
    return _cliente_cacheado(c.api_url, c.api_usuario, c.api_senha)


# ---------- utilidades ----------

def _base(request: Request) -> str:
    return request.scope.get("root_path", "").rstrip("/")


def _pagina(request: Request, template: str, status: int = 200, **ctx) -> HTMLResponse:
    html = TEMPLATES.get_template(template).render(base=_base(request), **ctx)
    return HTMLResponse(html, status_code=status)


def _para_lista(request: Request) -> RedirectResponse:
    return RedirectResponse(f"{_base(request)}/", status_code=303)


def _data(dt: datetime) -> str:
    return dt.astimezone(FUSO).strftime("%d/%m/%Y %H:%M")


def _data_com_dia(dt: datetime) -> str:
    dt = dt.astimezone(FUSO)
    return f"{_data(dt)} ({DIAS_SEMANA[dt.isoweekday() % 7]})"


@app.exception_handler(StarletteHTTPException)
async def _erro_http(request: Request, exc: StarletteHTTPException):
    mensagens = {
        401: "Faça login no Airflow para acessar esta página.",
        403: "Acesso restrito a administradores do Airflow.",
        404: "Página não encontrada.",
        405: "Método não permitido.",
    }
    try:
        padrao = HTTPStatus(exc.status_code).phrase  # detalhe padrão do Starlette, em inglês
    except ValueError:
        padrao = None
    if isinstance(exc.detail, str) and exc.detail and exc.detail != padrao:
        mensagem = exc.detail  # mensagens nossas, já em português
    else:
        mensagem = mensagens.get(exc.status_code, "Não foi possível atender a requisição.")
    if request.url.path.endswith("/api/proximas"):
        return JSONResponse({"erro": mensagem}, status_code=exc.status_code)
    login = "/auth/login/?next=" + quote(f"{_base(request)}/", safe="") if exc.status_code == 401 else None
    return _pagina(request, "erro.html", status=exc.status_code, mensagem=mensagem, login=login,
                   titulo=f"Erro {exc.status_code}")


@app.exception_handler(ErroRepositorio)
async def _erro_repositorio(request: Request, exc: ErroRepositorio):
    log.error("Falha no repositório de rotinas: %s", exc)
    return _pagina(request, "erro.html", status=500, mensagem=f"Não foi possível gravar a alteração: {exc}",
                   login=None, titulo="Erro ao gravar")


def _nao_encontrada(nome: str):
    raise StarletteHTTPException(status_code=404, detail=f"Rotina não encontrada: {nome}")


# ---------- formulário ----------

def _texto(form, chave: str, padrao: str = "") -> str:
    valores = [v for v in form.getlist(chave) if isinstance(v, str)]
    return valores[-1] if valores else padrao


def _booleano(form, chave: str) -> bool:
    # o formulário manda um hidden "false" seguido do checkbox "true": vale o último
    valores = [v for v in form.getlist(chave) if isinstance(v, str)]
    return PADROES[chave] if not valores else valores[-1].strip().lower() in ("true", "on", "1", "sim")


def _numero_ou_texto(texto: str):
    texto = (texto or "").strip()
    if texto == "":
        return None
    return int(texto) if re.fullmatch(r"\d+", texto) else texto


def agendamento_do_formulario(valores: dict) -> str:
    """Monta o cron a partir do preset (tipo, hora, minuto, dia) ou do cron avançado; ValueError se inválido."""
    tipo = valores.get("tipo_horario", "")
    if tipo == "cron":
        expr = (valores.get("cron") or "").strip()
        if not cron_valido(expr):
            raise ValueError("Agendamento inválido (use cron de 5 campos ou @hourly, @daily, @weekly, @monthly).")
        return expr
    return preset_para_cron(
        tipo, _numero_ou_texto(valores.get("hora")), _numero_ou_texto(valores.get("minuto")),
        dia_semana=_numero_ou_texto(valores.get("dia_semana")) if tipo == "semanal" else None,
        dia_mes=_numero_ou_texto(valores.get("dia_mes")) if tipo == "mensal" else None,
    )


def _ler_formulario(form, origem_padrao: str) -> tuple[dict, dict, dict]:
    """Devolve (valores para reexibir, dados para o repositório, erros do próprio formulário)."""
    v = {c: _texto(form, c) for c in (
        "nome", "descricao", "tipo_horario", "hora", "minuto", "dia_semana", "dia_mes", "cron",
        "argumentos", "tentativas", "intervalo_tentativa_min", "timeout_min", "emails_aviso",
        "script_existente")}
    v["tipo_horario"] = v["tipo_horario"] or "diario"
    v["origem_script"] = _texto(form, "origem_script") or origem_padrao
    v["ativa"] = _booleano(form, "ativa")
    v["avisar_falha"] = _booleano(form, "avisar_falha")
    erros: dict[str, str] = {}
    dados: dict = {"nome": v["nome"].strip(), "descricao": v["descricao"].strip(),
                   "ativa": v["ativa"], "avisar_falha": v["avisar_falha"]}

    try:
        dados["agendamento"] = agendamento_do_formulario(v)
    except ValueError as e:
        erros["agendamento"] = str(e)

    for chave in ("tentativas", "intervalo_tentativa_min", "timeout_min"):
        texto = v[chave].strip()
        if texto == "":
            dados[chave] = PADROES[chave]
        elif re.fullmatch(r"\d+", texto):
            dados[chave] = int(texto)
        else:
            erros[chave] = "Deve ser um número inteiro."

    dados["argumentos"] = [l.rstrip("\r") for l in v["argumentos"].split("\n") if l.strip()]

    emails = [e for e in re.split(r"[,;\s]+", v["emails_aviso"]) if e]
    invalidos = [e for e in emails if not RE_EMAIL.fullmatch(e)]
    if invalidos:
        erros["emails_aviso"] = " ".join(f"E-mail inválido: {e}." for e in invalidos)
    dados["emails_aviso"] = emails

    nomes, tipos = form.getlist("segredo_nome"), form.getlist("segredo_tipo")
    refs, campos = form.getlist("segredo_ref"), form.getlist("segredo_campo")
    total = max(len(nomes), len(tipos), len(refs), len(campos))
    item = lambda lst, i: (lst[i] if i < len(lst) and isinstance(lst[i], str) else "").strip()
    linhas, segredos, problemas = [], {}, []
    for i in range(total):
        linha = {"nome": item(nomes, i), "tipo": item(tipos, i) or "variavel",
                 "ref": item(refs, i), "campo": item(campos, i) or "password"}
        if not linha["nome"] and not linha["ref"]:
            continue
        linhas.append(linha)
        if linha["nome"] in segredos:
            problemas.append(f"Segredo repetido: {linha['nome']}.")
        elif linha["tipo"] == "conexao":
            segredos[linha["nome"]] = {"conexao": linha["ref"], "campo": linha["campo"]}
        elif linha["tipo"] == "variavel":
            segredos[linha["nome"]] = {"variavel": linha["ref"]}
        else:
            problemas.append(f"{linha['nome']}: tipo de referência inválido.")
    if problemas:
        erros["segredos"] = " ".join(problemas)
    v["segredos"] = linhas
    dados["segredos"] = segredos

    if v["origem_script"] == "existente":
        if v["script_existente"]:
            dados["script"] = v["script_existente"]
        else:
            erros["script"] = "Escolha um script existente."
    elif v["origem_script"] not in ("upload", "manter"):
        erros["script"] = "Escolha entre enviar um script ou usar um existente."
    return v, dados, erros


async def _arquivo_enviado(form, valores: dict) -> ArquivoEnviado | None:
    if valores["origem_script"] != "upload":
        return None
    arquivo = form.get("script")
    if not isinstance(arquivo, UploadFile) or not arquivo.filename:
        return None
    conteudo = await arquivo.read(LIMITE_SCRIPT + 1)  # o repositório recusa acima de 1 MB
    return ArquivoEnviado(arquivo.filename, conteudo)


def _valores_da_rotina(r: Rotina) -> dict:
    v = {
        "nome": r.nome, "descricao": r.descricao, "argumentos": "\n".join(r.argumentos),
        "tentativas": str(r.tentativas), "intervalo_tentativa_min": str(r.intervalo_tentativa_min),
        "timeout_min": str(r.timeout_min), "emails_aviso": ", ".join(r.emails_aviso),
        "ativa": r.ativa, "avisar_falha": r.avisar_falha, "origem_script": "manter", "script_existente": "",
        "tipo_horario": "cron", "cron": r.agendamento, "hora": "2", "minuto": "0", "dia_semana": "1", "dia_mes": "1",
        "segredos": [
            {"nome": n, "tipo": "conexao" if ref.conexao else "variavel",
             "ref": ref.conexao or ref.variavel or "", "campo": ref.campo or "password"}
            for n, ref in r.segredos.items()
        ],
    }
    preset = cron_para_preset(r.agendamento)
    if preset:
        v.update({k: str(x) for k, x in preset.items() if k != "tipo"}, tipo_horario=preset["tipo"])
    return v


def _valores_novos() -> dict:
    return {
        "nome": "", "descricao": "", "argumentos": "", "emails_aviso": "", "cron": "",
        "tentativas": str(PADROES["tentativas"]), "intervalo_tentativa_min": str(PADROES["intervalo_tentativa_min"]),
        "timeout_min": str(PADROES["timeout_min"]), "ativa": True, "avisar_falha": True,
        "tipo_horario": "diario", "hora": "2", "minuto": "0", "dia_semana": "1", "dia_mes": "1",
        "origem_script": "upload", "script_existente": "", "segredos": [],
    }


def _formulario(request, repo, usuario, valores, erros=None, rotina=None, status=200, reenviar=False):
    erros = erros or {}
    gerais = {k: m for k, m in erros.items() if k not in CAMPOS_DO_FORMULARIO}
    return _pagina(
        request, "formulario.html", status=status, usuario=usuario, v=valores, erros=erros, gerais=gerais,
        rotina=rotina, scripts=repo.scripts_existentes(), campos_conexao=CAMPOS_CONEXAO, reenviar=reenviar,
        titulo=f"Editar {rotina.nome}" if rotina else "Nova rotina",
    )


# ---------- lista ----------

def _linhas(rotinas: list[Rotina], estados: dict | None) -> list[dict]:
    agora = datetime.now(FUSO)
    linhas = []
    for r in rotinas:
        try:
            proxima = _data(proximas(r.agendamento, 1, agora)[0]) if r.ativa else "— (inativa)"
        except ValueError:
            proxima = "—"
        e = estados.get(r.nome) if estados is not None else None
        divergente = False
        if e is None:
            status, ultima = "indisponível", "indisponível"
        elif not e.existe:
            status, ultima = "Aguardando o Airflow carregar", "—"
        else:
            status = "Pausado" if e.pausado else "Ativo"
            divergente = e.pausado == r.ativa
            if e.ultima_execucao_ok:
                ultima = f"Sucesso em {_data(e.ultima_execucao_ok)}"
            else:
                ultima = "Sem sucesso registrado" if e.tem_execucoes else "Nunca executou"
        linhas.append({"r": r, "horario": descrever(r.agendamento), "proxima": proxima,
                       "status": status, "ultima": ultima, "divergente": divergente})
    return linhas


def _lista(request, repo, cliente, usuario, aviso: str | None = None) -> HTMLResponse:
    rotinas, erros_yaml = repo.listar()
    try:
        estados = cliente.estados([r.nome for r in rotinas]) if rotinas else {}
    except Exception:  # API fora: a lista aparece mesmo assim
        log.exception("Não foi possível consultar o estado das rotinas na API do Airflow")
        estados = None
    return _pagina(request, "lista.html", usuario=usuario, linhas=_linhas(rotinas, estados),
                   erros_yaml=erros_yaml, aviso=aviso, api_fora=estados is None, titulo="Rotinas")


def _aplicar_pausa(cliente, nome: str, ativa: bool) -> str | None:
    try:
        cliente.definir_pausa(nome, not ativa)
    except Exception:
        log.exception("Não foi possível aplicar a pausa do DAG %s no Airflow", nome)
        return AVISO_PAUSA
    return None


# ---------- rotas ----------

@app.get("/", response_class=HTMLResponse)
def lista(request: Request, usuario: str = Depends(exigir_admin), repo=Depends(obter_repo),
          cliente=Depends(obter_cliente)):
    return _lista(request, repo, cliente, usuario)


@app.get("/nova", response_class=HTMLResponse)
def nova(request: Request, usuario: str = Depends(exigir_admin), repo=Depends(obter_repo)):
    return _formulario(request, repo, usuario, _valores_novos())


@app.post("/nova", response_class=HTMLResponse)
async def criar(request: Request, usuario: str = Depends(exigir_admin_post), repo=Depends(obter_repo)):
    form = await request.form()
    valores, dados, erros = _ler_formulario(form, origem_padrao="upload")
    arquivo = await _arquivo_enviado(form, valores)
    if not erros:
        try:
            await run_in_threadpool(repo.criar, dados, arquivo, usuario)
            return _para_lista(request)
        except RotinaInvalida as e:
            erros = dict(e.erros)
            if arquivo is not None and "nome" in erros and erros.get("script", "").startswith("Informe o caminho"):
                erros.pop("script")  # validado antes de o upload ser aplicado; o arquivo em si não foi o problema
        except ErroRepositorio as e:
            log.exception("Falha ao gravar a rotina nova")
            return _formulario(request, repo, usuario, valores, {"geral": f"Não foi possível salvar: {e}"},
                               status=500, reenviar=arquivo is not None)
    return _formulario(request, repo, usuario, valores, erros, status=422, reenviar=arquivo is not None)


@app.get("/api/proximas")
def api_proximas(request: Request):
    params = request.query_params
    try:
        expr = (params.get("agendamento") or "").strip() if "agendamento" in params \
            else agendamento_do_formulario(dict(params))
        datas = proximas(expr, 3, datetime.now(FUSO))
    except ValueError as e:
        return JSONResponse({"erro": str(e)}, status_code=422)
    return {"agendamento": expr, "descricao": descrever(expr), "proximas": [_data_com_dia(d) for d in datas]}


@app.get("/{nome}/editar", response_class=HTMLResponse)
def editar(request: Request, nome: str, usuario: str = Depends(exigir_admin), repo=Depends(obter_repo)):
    rotina = repo.obter(nome)
    if rotina is None:
        _nao_encontrada(nome)
    return _formulario(request, repo, usuario, _valores_da_rotina(rotina), rotina=rotina)


@app.post("/{nome}/editar", response_class=HTMLResponse)
async def salvar_edicao(request: Request, nome: str, usuario: str = Depends(exigir_admin_post),
                        repo=Depends(obter_repo), cliente=Depends(obter_cliente)):
    atual = await run_in_threadpool(repo.obter, nome)
    if atual is None:
        _nao_encontrada(nome)
    form = await request.form()
    valores, dados, erros = _ler_formulario(form, origem_padrao="manter")
    valores["nome"] = dados["nome"] = nome  # renomear não é permitido
    arquivo = await _arquivo_enviado(form, valores)
    if valores["origem_script"] == "manter":
        dados["script"] = atual.script
    elif valores["origem_script"] == "upload" and arquivo is None:
        erros["script"] = "Escolha o arquivo do script para enviar (ou mantenha o atual)."
    if not erros:
        try:
            nova_rotina = await run_in_threadpool(repo.atualizar, nome, dados, arquivo, usuario)
        except RotinaInvalida as e:
            erros = dict(e.erros)
        except ErroRepositorio as e:
            log.exception("Falha ao gravar a rotina %s", nome)
            return _formulario(request, repo, usuario, valores, {"geral": f"Não foi possível salvar: {e}"},
                               rotina=atual, status=500, reenviar=arquivo is not None)
        else:
            if nova_rotina.ativa != atual.ativa:
                aviso = await run_in_threadpool(_aplicar_pausa, cliente, nome, nova_rotina.ativa)
                if aviso:
                    return await run_in_threadpool(_lista, request, repo, cliente, usuario, aviso)
            return _para_lista(request)
    return _formulario(request, repo, usuario, valores, erros, rotina=atual, status=422,
                       reenviar=arquivo is not None)


@app.post("/{nome}/ativa", response_class=HTMLResponse)
async def definir_ativa(request: Request, nome: str, usuario: str = Depends(exigir_admin_post),
                        repo=Depends(obter_repo), cliente=Depends(obter_cliente)):
    form = await request.form()
    valor = _texto(form, "ativa").strip().lower()
    if valor not in ("true", "false"):
        raise StarletteHTTPException(status_code=400, detail="Valor inválido para 'ativa' (use true ou false).")
    if await run_in_threadpool(repo.obter, nome) is None:
        _nao_encontrada(nome)
    ativa = valor == "true"
    await run_in_threadpool(repo.definir_ativa, nome, ativa, usuario)
    aviso = await run_in_threadpool(_aplicar_pausa, cliente, nome, ativa)
    if aviso:
        return await run_in_threadpool(_lista, request, repo, cliente, usuario, aviso)
    return _para_lista(request)


@app.get("/{nome}/excluir", response_class=HTMLResponse)
def confirmar_exclusao(request: Request, nome: str, usuario: str = Depends(exigir_admin), repo=Depends(obter_repo)):
    rotina = repo.obter(nome)
    if rotina is None:
        _nao_encontrada(nome)
    compartilhado = [r.nome for r in repo.listar()[0] if r.nome != nome and r.script == rotina.script]
    return _pagina(request, "confirmar_exclusao.html", usuario=usuario, rotina=rotina,
                   compartilhado=compartilhado, titulo=f"Excluir {nome}")


@app.post("/{nome}/excluir", response_class=HTMLResponse)
async def excluir(request: Request, nome: str, usuario: str = Depends(exigir_admin_post), repo=Depends(obter_repo)):
    if await run_in_threadpool(repo.obter, nome) is None:
        _nao_encontrada(nome)
    await run_in_threadpool(repo.excluir, nome, usuario)
    return _para_lista(request)
