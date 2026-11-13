#!/usr/bin/env python3
"""Liga, desliga ou mostra o estado de uma VM no vCenter, pela API REST (vCenter 7.0U2 ou mais novo).

Uso:
  vcenter_energia.py status   NOME_DA_VM
  vcenter_energia.py ligar    NOME_DA_VM
  vcenter_energia.py desligar NOME_DA_VM [--forcar] [--espera SEGUNDOS]

desligar   desligamento limpo pelo sistema operacional (exige VMware Tools rodando) e espera
           até --espera segundos (padrão 300) a VM desligar.
--forcar   corta a energia na hora, como puxar o cabo. Use quando o Tools não responde.

Variáveis de ambiente (na rotina do Airflow, cadastre como "segredos"):
  VCENTER_HOST            IP ou nome do vCenter (aceita HOST:PORTA)
  VCENTER_USUARIO         usuário do SSO (ex.: svc-automacao@vsphere.local)
  VCENTER_SENHA           senha
  VCENTER_CA_PEM          (opcional) CONTEÚDO do .pem da CA do vCenter (cadastre como Variable no Airflow)
  VCENTER_CA              (opcional) caminho de um arquivo .pem da CA, alternativa ao VCENTER_CA_PEM
  VCENTER_INSEGURO=1      (opcional) não valida o certificado. Só para teste; imprime aviso
  VCENTER_VMS_PERMITIDAS  (opcional) nomes separados por vírgula; outras VMs são recusadas

Códigos de saída: 0 sucesso (inclusive "já estava no estado pedido"), 1 falha, 2 uso inválido.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import quote

TIMEOUT_HTTP_S = 30
INTERVALO_S = 5
ESTADOS = {"POWERED_ON": "ligada", "POWERED_OFF": "desligada", "SUSPENDED": "suspensa"}


class Falha(Exception):
    """Erro já explicado em português; vira código de saída 1."""


class Uso(Exception):
    """Argumento ou configuração inválida; vira código de saída 2."""


class VCenter:
    def __init__(self, host: str, contexto: ssl.SSLContext):
        self.base = f"https://{host}/api"
        self.ctx = contexto
        self.token: str | None = None

    def _pedir(self, metodo: str, caminho: str, cabecalhos: dict | None = None):
        req = urllib.request.Request(self.base + caminho, method=metodo, headers=cabecalhos or {})
        if self.token:
            req.add_header("vmware-api-session-id", self.token)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_HTTP_S, context=self.ctx) as resp:
                corpo = resp.read()
        except urllib.error.HTTPError as e:
            return e.code, _ler_json(e.read())
        except urllib.error.URLError as e:
            motivo = e.reason
            if isinstance(motivo, ssl.SSLCertVerificationError):
                raise Falha(
                    f"certificado do vCenter não é confiável ({motivo.verify_message}). "
                    "Aponte a CA em VCENTER_CA ou, só para teste, use VCENTER_INSEGURO=1."
                ) from None
            raise Falha(f"não foi possível conectar em {self.base}: {motivo}") from None
        except TimeoutError:
            raise Falha(f"o vCenter não respondeu em {TIMEOUT_HTTP_S} s ({metodo} {caminho})") from None
        return resp.status, _ler_json(corpo)

    def chamar(self, metodo: str, caminho: str, aceitar: tuple[int, ...] = (200, 201, 204)):
        codigo, dados = self._pedir(metodo, caminho)
        if codigo not in aceitar:
            raise Falha(f"{metodo} {caminho} devolveu {codigo}: {_mensagem_erro(dados)}")
        return codigo, dados

    def entrar(self, usuario: str, senha: str) -> None:
        cred = base64.b64encode(f"{usuario}:{senha}".encode()).decode()
        codigo, dados = self._pedir("POST", "/session", {"Authorization": f"Basic {cred}"})
        if codigo == 401:
            raise Falha(f"o vCenter recusou o usuário ou a senha de {usuario}")
        if codigo not in (200, 201) or not isinstance(dados, str):
            raise Falha(f"login no vCenter devolveu {codigo}: {_mensagem_erro(dados)}")
        self.token = dados

    def sair(self) -> None:
        if self.token:
            try:
                self._pedir("DELETE", "/session")
            except Falha:
                pass
            self.token = None


def _ler_json(corpo: bytes):
    if not corpo:
        return None
    try:
        return json.loads(corpo)
    except ValueError:
        return corpo.decode(errors="replace")[:200]


def _mensagem_erro(dados) -> str:
    if isinstance(dados, dict):
        msgs = [m.get("default_message", "") for m in dados.get("messages", []) if isinstance(m, dict)]
        texto = "; ".join(m for m in msgs if m)
        return f"{dados.get('error_type', 'erro')}: {texto}" if texto else str(dados.get("error_type", dados))
    return str(dados)


def _contexto_ssl() -> ssl.SSLContext:
    if os.environ.get("VCENTER_INSEGURO") == "1":
        print("AVISO: VCENTER_INSEGURO=1, o certificado do vCenter NÃO está sendo validado.", file=sys.stderr)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    pem = os.environ.get("VCENTER_CA_PEM", "").strip()
    if pem:
        try:
            return ssl.create_default_context(cadata=pem)
        except (ssl.SSLError, ValueError):
            raise Uso("VCENTER_CA_PEM não contém um certificado PEM válido (-----BEGIN CERTIFICATE-----...)") from None
    ca = os.environ.get("VCENTER_CA")
    if ca and not os.path.isfile(ca):
        raise Uso(f"VCENTER_CA aponta para um arquivo que não existe: {ca}")
    return ssl.create_default_context(cafile=ca or None)


def _ambiente(nome: str) -> str:
    valor = os.environ.get(nome, "")
    if not valor:
        raise Uso(f"variável de ambiente {nome} não definida")
    return valor


def _argumentos(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="vcenter_energia.py", description="Liga/desliga uma VM no vCenter.")
    p.add_argument("acao", choices=["status", "ligar", "desligar"])
    p.add_argument("vm", help="nome exato da VM no vCenter")
    p.add_argument("--forcar", action="store_true", help="desligar cortando a energia (sem o sistema operacional)")
    p.add_argument("--espera", type=int, default=300, help="segundos de espera pelo desligamento (padrão 300)")
    a = p.parse_args(argv)  # erro de uso: argparse sai com 2
    if not a.vm.strip() or len(a.vm) > 80 or any(ord(c) < 32 or ord(c) == 127 for c in a.vm):
        raise Uso(f"nome de VM inválido: {a.vm!r}")
    if a.espera < 1:
        raise Uso("--espera precisa ser pelo menos 1")
    return a


def _achar_vm(vc: VCenter, nome: str) -> dict:
    _, lista = vc.chamar("GET", f"/vcenter/vm?names={quote(nome, safe='')}")
    achadas = [v for v in (lista or []) if v.get("name") == nome]  # o filtro do vCenter já é exato; confere
    if not achadas:
        raise Falha(f"VM '{nome}' não encontrada no vCenter (o nome precisa ser exato)")
    if len(achadas) > 1:
        ids = ", ".join(v["vm"] for v in achadas)
        raise Falha(f"há mais de uma VM chamada '{nome}' ({ids}); nada foi feito")
    return achadas[0]


def _estado(vc: VCenter, vm_id: str) -> str:
    return vc.chamar("GET", f"/vcenter/vm/{vm_id}/power")[1]["state"]


def _tools(vc: VCenter, vm_id: str) -> str:
    return vc.chamar("GET", f"/vcenter/vm/{vm_id}/tools")[1].get("run_state", "DESCONHECIDO")


def status(vc: VCenter, nome: str, vm_id: str) -> None:
    estado = _estado(vc, vm_id)
    print(f"{nome} ({vm_id}): {estado} ({ESTADOS.get(estado, '?')}), VMware Tools: {_tools(vc, vm_id)}")


def ligar(vc: VCenter, nome: str, vm_id: str) -> None:
    if _estado(vc, vm_id) == "POWERED_ON":
        print(f"{nome} já está ligada; nada a fazer.")
        return
    print(f"Ligando {nome} ({vm_id})...")
    vc.chamar("POST", f"/vcenter/vm/{vm_id}/power?action=start")
    estado = _estado(vc, vm_id)
    if estado != "POWERED_ON":
        raise Falha(f"pedido de ligar aceito, mas {nome} está {estado}")
    print(f"{nome} ligada.")


def desligar(vc: VCenter, nome: str, vm_id: str, forcar: bool, espera_s: int) -> None:
    estado = _estado(vc, vm_id)
    if estado == "POWERED_OFF":
        print(f"{nome} já está desligada; nada a fazer.")
        return
    if forcar:
        print(f"Cortando a energia de {nome} ({vm_id}) (--forcar)...")
        vc.chamar("POST", f"/vcenter/vm/{vm_id}/power?action=stop")
    else:
        if estado != "POWERED_ON":
            raise Falha(f"{nome} está {estado}; o desligamento limpo não se aplica. Use --forcar.")
        tools = _tools(vc, vm_id)
        if tools != "RUNNING":
            raise Falha(
                f"VMware Tools de {nome} não está rodando ({tools}), então não dá para desligar pelo sistema "
                "operacional. Nada foi feito. Para cortar a energia, use --forcar."
            )
        print(f"Pedindo desligamento limpo de {nome} ({vm_id}) pelo sistema operacional...")
        vc.chamar("POST", f"/vcenter/vm/{vm_id}/guest/power?action=shutdown")
    limite = time.monotonic() + espera_s
    while True:
        estado = _estado(vc, vm_id)
        if estado == "POWERED_OFF":
            print(f"{nome} desligada.")
            return
        resta = limite - time.monotonic()
        if resta <= 0:
            raise Falha(f"{nome} não desligou em {espera_s} s (estado: {estado}). Veja o console ou use --forcar.")
        time.sleep(min(INTERVALO_S, resta))


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(line_buffering=True)  # no Airflow a saída é um pipe: sem isso o log sai fora de ordem
    vc = None
    try:
        a = _argumentos(argv)
        permitidas = [n.strip() for n in os.environ.get("VCENTER_VMS_PERMITIDAS", "").split(",") if n.strip()]
        if permitidas and a.vm not in permitidas:
            raise Uso(f"VM '{a.vm}' fora da lista VCENTER_VMS_PERMITIDAS; nada foi feito")
        host = _ambiente("VCENTER_HOST")
        if not re.fullmatch(r"[A-Za-z0-9.-]+(:[0-9]{1,5})?", host):
            raise Uso(f"VCENTER_HOST inválido: {host!r} (use IP ou nome, sem https://)")
        usuario, senha = _ambiente("VCENTER_USUARIO"), _ambiente("VCENTER_SENHA")
        vc = VCenter(host, _contexto_ssl())
        print(f"Conectando em {host} como {usuario}...")
        vc.entrar(usuario, senha)
        vm = _achar_vm(vc, a.vm)
        if a.acao == "status":
            status(vc, a.vm, vm["vm"])
        elif a.acao == "ligar":
            ligar(vc, a.vm, vm["vm"])
        else:
            desligar(vc, a.vm, vm["vm"], a.forcar, a.espera)
        return 0
    except Uso as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 2
    except Falha as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 1
    finally:
        if vc is not None:
            vc.sair()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
