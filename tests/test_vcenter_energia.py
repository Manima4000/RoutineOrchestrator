"""Testes de vcenter_energia.py contra um vCenter falso (HTTPS local, certificado autoassinado).

O falso imita só o pedaço da API REST do vCenter (7.0U2+) que o script usa.
"""
import base64
import json
import os
import ssl
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts_base/exemplos/scripts/vcenter_energia.py"
USUARIO = "svc@vsphere.local"
SENHA = "senha-de-teste-123"


class VCenterFalso:
    def __init__(self):
        self.vms = {}  # id -> dict(name, power, tools, desliga_no_shutdown)
        self.sessoes = set()
        self.encerradas = 0
        self.acoes = []  # (vm_id, ação) recebidas

    def add(self, vm_id, nome, power="POWERED_ON", tools="RUNNING", desliga_no_shutdown=True):
        self.vms[vm_id] = dict(name=nome, power=power, tools=tools, desliga_no_shutdown=desliga_no_shutdown)


def _handler(vc: VCenterFalso):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, codigo, corpo=None):
            dados = b"" if corpo is None else json.dumps(corpo).encode()
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)

        def _erro(self, codigo, tipo, msg):
            self._json(codigo, {"error_type": tipo, "messages": [{"id": "x", "default_message": msg, "args": []}]})

        def _autenticado(self):
            if self.headers.get("vmware-api-session-id") in vc.sessoes:
                return True
            self._erro(401, "UNAUTHENTICATED", "sessão inválida")
            return False

        def do_POST(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == "/api/session":
                esperado = "Basic " + base64.b64encode(f"{USUARIO}:{SENHA}".encode()).decode()
                if self.headers.get("Authorization") != esperado:
                    return self._erro(401, "UNAUTHENTICATED", "credenciais inválidas")
                token = f"tok{len(vc.sessoes) + vc.encerradas + 1}"
                vc.sessoes.add(token)
                return self._json(201, token)
            if not self._autenticado():
                return
            partes = u.path.strip("/").split("/")  # api vcenter vm ID power | api vcenter vm ID guest power
            vm = vc.vms.get(partes[3]) if len(partes) > 3 else None
            if vm is None:
                return self._erro(404, "NOT_FOUND", "vm não existe")
            acao = q.get("action", [""])[0]
            vc.acoes.append((partes[3], acao))
            if partes[4:] == ["power"]:
                alvo = {"start": "POWERED_ON", "stop": "POWERED_OFF"}[acao]
                if vm["power"] == alvo:
                    return self._erro(400, "ALREADY_IN_DESIRED_STATE", "já está no estado")
                vm["power"] = alvo
                return self._json(204)
            if partes[4:] == ["guest", "power"] and acao == "shutdown":
                if vm["tools"] != "RUNNING":
                    return self._erro(503, "SERVICE_UNAVAILABLE", "VMware Tools não está rodando")
                if vm["desliga_no_shutdown"]:
                    vm["power"] = "POWERED_OFF"
                    vm["tools"] = "NOT_RUNNING"
                return self._json(204)
            return self._erro(404, "NOT_FOUND", "rota")

        def do_GET(self):
            u = urlparse(self.path)
            if not self._autenticado():
                return
            partes = u.path.strip("/").split("/")
            if partes == ["api", "vcenter", "vm"]:
                nomes = parse_qs(u.query).get("names", [])
                lista = [
                    {"vm": i, "name": v["name"], "power_state": v["power"]}
                    for i, v in vc.vms.items()
                    if not nomes or v["name"] in nomes
                ]
                return self._json(200, lista)
            vm = vc.vms.get(partes[3]) if len(partes) > 3 else None
            if vm is None:
                return self._erro(404, "NOT_FOUND", "vm não existe")
            if partes[4:] == ["power"]:
                return self._json(200, {"state": vm["power"]})
            if partes[4:] == ["tools"]:
                return self._json(200, {"run_state": vm["tools"]})
            return self._erro(404, "NOT_FOUND", "rota")

        def do_DELETE(self):
            if urlparse(self.path).path == "/api/session" and self._autenticado():
                vc.sessoes.discard(self.headers["vmware-api-session-id"])
                vc.encerradas += 1
                return self._json(204)

    return H


@pytest.fixture(scope="module")
def certificado(tmp_path_factory):
    d = tmp_path_factory.mktemp("cert")
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=localhost",
         "-addext", "subjectAltName=IP:127.0.0.1", "-keyout", str(d / "key.pem"), "-out", str(d / "cert.pem")],
        check=True, capture_output=True,
    )
    return d / "cert.pem", d / "key.pem"


@pytest.fixture
def vc(certificado):
    falso = VCenterFalso()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _handler(falso))
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(*certificado)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    falso.host = f"127.0.0.1:{srv.server_address[1]}"
    falso.ca = str(certificado[0])
    yield falso
    srv.shutdown()
    srv.server_close()


def rodar(vc, *args, **env_extra):
    env = {"PATH": os.environ["PATH"], "VCENTER_HOST": vc.host, "VCENTER_USUARIO": USUARIO,
           "VCENTER_SENHA": SENHA, "VCENTER_CA": vc.ca}
    env.update(env_extra)
    env = {k: v for k, v in env.items() if v is not None}
    r = subprocess.run([sys.executable, str(SCRIPT), *args], env=env, capture_output=True, text=True,
                       timeout=60, stdin=subprocess.DEVNULL)
    r.saida = r.stdout + r.stderr
    assert SENHA not in r.saida
    return r


# ---------- status ----------

def test_status_mostra_estado_e_encerra_sessao(vc):
    vc.add("vm-1", "apache01")
    r = rodar(vc, "status", "apache01")
    assert r.returncode == 0, r.saida
    assert "POWERED_ON" in r.stdout and "apache01" in r.stdout
    assert vc.sessoes == set() and vc.encerradas == 1
    assert vc.acoes == []


def test_vm_inexistente_falha_sem_agir(vc):
    vc.add("vm-1", "apache01")
    r = rodar(vc, "desligar", "apache02")
    assert r.returncode == 1
    assert "apache02" in r.stderr and "não encontrada" in r.stderr
    assert vc.acoes == [] and vc.sessoes == set()


def test_nome_ambiguo_falha_sem_agir(vc):
    vc.add("vm-1", "web")
    vc.add("vm-2", "web")
    r = rodar(vc, "desligar", "web")
    assert r.returncode == 1 and "mais de uma" in r.stderr
    assert vc.acoes == []


def test_nome_parecido_nao_conta(vc):
    # o filtro do falso devolve só nomes exatos; aqui garantimos que o script também confere
    vc.add("vm-1", "apache01")
    r = rodar(vc, "status", "APACHE01")
    assert r.returncode == 1 and "não encontrada" in r.stderr


# ---------- ligar ----------

def test_ligar_vm_desligada(vc):
    vc.add("vm-1", "apache01", power="POWERED_OFF", tools="NOT_RUNNING")
    r = rodar(vc, "ligar", "apache01")
    assert r.returncode == 0, r.saida
    assert vc.vms["vm-1"]["power"] == "POWERED_ON"
    assert ("vm-1", "start") in vc.acoes


def test_ligar_vm_ja_ligada_e_sucesso_sem_acao(vc):
    vc.add("vm-1", "apache01")
    r = rodar(vc, "ligar", "apache01")
    assert r.returncode == 0, r.saida
    assert "já está ligada" in r.stdout
    assert vc.acoes == []


# ---------- desligar ----------

def test_desligar_faz_shutdown_limpo_pelo_tools(vc):
    vc.add("vm-1", "apache01")
    r = rodar(vc, "desligar", "apache01")
    assert r.returncode == 0, r.saida
    assert vc.acoes == [("vm-1", "shutdown")]
    assert vc.vms["vm-1"]["power"] == "POWERED_OFF"


def test_desligar_sem_tools_falha_e_nao_corta_energia(vc):
    vc.add("vm-1", "apache01", tools="NOT_RUNNING")
    r = rodar(vc, "desligar", "apache01")
    assert r.returncode == 1
    assert "--forcar" in r.stderr
    assert vc.acoes == [] and vc.vms["vm-1"]["power"] == "POWERED_ON"


def test_desligar_forcar_corta_energia(vc):
    vc.add("vm-1", "apache01", tools="NOT_RUNNING")
    r = rodar(vc, "desligar", "apache01", "--forcar")
    assert r.returncode == 0, r.saida
    assert vc.acoes == [("vm-1", "stop")]
    assert vc.vms["vm-1"]["power"] == "POWERED_OFF"


def test_desligar_vm_ja_desligada_e_sucesso_sem_acao(vc):
    vc.add("vm-1", "apache01", power="POWERED_OFF", tools="NOT_RUNNING")
    r = rodar(vc, "desligar", "apache01")
    assert r.returncode == 0, r.saida
    assert "já está desligada" in r.stdout
    assert vc.acoes == []


def test_desligar_que_nao_termina_no_prazo_falha(vc):
    vc.add("vm-1", "apache01", desliga_no_shutdown=False)
    r = rodar(vc, "desligar", "apache01", "--espera", "1")
    assert r.returncode == 1
    assert "não desligou" in r.stderr
    assert vc.sessoes == set()


def test_vm_suspensa_desligar_sem_forcar_falha(vc):
    vc.add("vm-1", "apache01", power="SUSPENDED", tools="NOT_RUNNING")
    r = rodar(vc, "desligar", "apache01")
    assert r.returncode == 1 and "--forcar" in r.stderr
    assert vc.acoes == []


# ---------- travas e configuração ----------

def test_lista_permitida_recusa_outra_vm_antes_de_conectar(vc):
    vc.add("vm-1", "apache01")
    r = rodar(vc, "desligar", "apache01", VCENTER_VMS_PERMITIDAS="teste01, teste02")
    assert r.returncode == 2 and "VCENTER_VMS_PERMITIDAS" in r.stderr
    assert vc.encerradas == 0 and vc.acoes == []


def test_lista_permitida_aceita_vm_listada(vc):
    vc.add("vm-1", "teste02")
    r = rodar(vc, "status", "teste02", VCENTER_VMS_PERMITIDAS="teste01, teste02")
    assert r.returncode == 0, r.saida


def test_senha_errada_falha_com_mensagem_clara(vc):
    vc.add("vm-1", "apache01")
    r = rodar(vc, "status", "apache01", VCENTER_SENHA="errada")
    assert r.returncode == 1 and "recusou" in r.stderr


def test_certificado_nao_confiavel_falha_por_padrao(vc):
    vc.add("vm-1", "apache01")
    r = rodar(vc, "status", "apache01", VCENTER_CA=None)
    assert r.returncode == 1 and "certificado" in r.stderr.lower()
    assert vc.encerradas == 0


def test_inseguro_explicito_aceita_e_avisa(vc):
    vc.add("vm-1", "apache01")
    r = rodar(vc, "status", "apache01", VCENTER_CA=None, VCENTER_INSEGURO="1")
    assert r.returncode == 0, r.saida
    assert "AVISO" in r.stderr


def test_falta_variavel_de_ambiente(vc):
    r = rodar(vc, "status", "apache01", VCENTER_SENHA=None)
    assert r.returncode == 2 and "VCENTER_SENHA" in r.stderr


@pytest.mark.parametrize("args", [[], ["reiniciar", "x"], ["ligar"], ["ligar", "a", "b"], ["ligar", "x\nrm"]])
def test_uso_invalido_sai_com_2(vc, args):
    r = rodar(vc, *args)
    assert r.returncode == 2
