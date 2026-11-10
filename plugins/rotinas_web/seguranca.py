"""Segurança do plugin "Rotinas": só Admin entra, e POST só vindo da própria página.

Mecanismo de autenticação (verificado no Airflow 3.1.8 + provider FAB, Task 11):
- O login da interface (FAB, /auth/login/) grava o cookie ``_token`` (JWT do usuário,
  HttpOnly, Path=/). O app FastAPI do plugin é montado no mesmo api-server
  (``fastapi_apps``, prefixo /rotinas-app), então o navegador manda esse cookie — inclusive
  quando a página é aberta dentro da interface (``external_views`` com destination "nav",
  que a interface mostra num iframe da mesma origem).
- Lemos o token do cookie (ou de ``Authorization: Bearer``, como a API REST) e o
  resolvemos com ``airflow.api_fastapi.core_api.security.resolve_user_from_token``, que usa
  o auth manager configurado (FAB) para devolver o ``User`` do banco. É o usuário de
  verdade que está logado — não a conta de serviço do plugin.
- O papel vem de ``user.roles`` (modelo FAB); exige-se o papel "Admin".
- Sem token / token expirado / usuário inexistente -> 401; logado sem Admin -> 403.

Como a sessão é por cookie, todo POST também passa por ``verificar_origem`` (defesa contra
CSRF): ``Origin`` (ou, na falta dele, ``Referer``) precisa ter o mesmo esquema+host+porta da
própria requisição; sem os dois, recusa.
"""
from __future__ import annotations

import inspect
import logging
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request

PAPEL_ADMIN = "Admin"
log = logging.getLogger(__name__)


async def _usuario_do_token(request: Request):
    """Devolve o usuário do Airflow dono do token da requisição, ou None se não houver sessão válida."""
    from airflow.api_fastapi.auth.managers.base_auth_manager import COOKIE_NAME_JWT_TOKEN
    from airflow.api_fastapi.core_api.security import resolve_user_from_token

    token = None
    autorizacao = request.headers.get("authorization", "")
    if autorizacao.lower().startswith("bearer "):
        token = autorizacao[7:].strip()
    token = token or request.cookies.get(COOKIE_NAME_JWT_TOKEN)
    if not token:
        return None
    try:
        return await resolve_user_from_token(token)
    except HTTPException:  # expirado ou inválido
        return None
    except ValueError:  # token de um usuário que não existe mais
        return None


async def exigir_admin(request: Request) -> str:
    """Dependência FastAPI: devolve o nome do usuário logado se ele tiver o papel Admin."""
    usuario = _usuario_do_token(request)
    if inspect.isawaitable(usuario):  # nos testes pode ser substituída por função comum
        usuario = await usuario
    if usuario is None:
        raise HTTPException(status_code=401, detail="Faça login no Airflow para acessar esta página.")
    papeis = {getattr(p, "name", None) for p in (getattr(usuario, "roles", None) or [])}
    if PAPEL_ADMIN not in papeis:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores do Airflow.")
    return usuario.get_name()


def _origem(url: str) -> tuple[str, str, int] | None:
    try:
        partes = urlsplit(url)
        esquema, host, porta = partes.scheme.lower(), (partes.hostname or "").lower(), partes.port
    except ValueError:
        return None
    if esquema not in ("http", "https") or not host:
        return None
    return esquema, host, porta or (443 if esquema == "https" else 80)


def verificar_origem(request: Request) -> None:
    """Em POST, exige Origin/Referer igual à própria origem da requisição; senão 403."""
    if request.method != "POST":
        return
    enviada = request.headers.get("origin") or request.headers.get("referer")
    propria = _origem(str(request.url))
    if not enviada or propria is None or _origem(enviada) != propria:
        log.warning("POST recusado por origem diferente: %r (esperado %r)", enviada, propria)
        raise HTTPException(status_code=403, detail="Requisição recusada: origem diferente da página do Airflow.")


async def exigir_admin_post(request: Request, usuario: str = Depends(exigir_admin)) -> str:
    """Admin primeiro (401/403), depois a checagem de origem."""
    verificar_origem(request)
    return usuario
