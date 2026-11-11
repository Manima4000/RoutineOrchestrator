#!/usr/bin/env python3
"""Backup cifrado de um diretório de uma VM: argumentos + segredo.

Uso: vm_backup_diretorio_cifrado.py HOST DIRETORIO [MANTER=7]

  HOST       VM de origem (acessada por SSH com a chave do ambiente)
  DIRETORIO  caminho absoluto na VM (ex.: /srv/dados). O usuário de serviço precisa conseguir lê-lo
  MANTER     quantos backups guardar por origem (padrão 7)

Segredo (variável de ambiente, definida em "Segredos" da rotina; nunca nos argumentos):
  BACKUP_SENHA   senha de cifragem do arquivo (mínimo 12 caracteres)

Fluxo: tar.gz na VM -> traz por SFTP -> cifra aqui com AES-256 (openssl) -> confere que decifra
e é um tar válido -> apaga o texto claro e os backups antigos. Resultado:
  $BACKUPS_DIR/dir-<HOST>-<DIRETORIO>/<data>.tar.gz.enc

Para restaurar (digite a senha quando pedir):
  openssl enc -d -aes-256-cbc -pbkdf2 -in ARQUIVO.tar.gz.enc | tar xz -C /destino
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from ssh_util import receber, remoto

_HOST = re.compile(r"^[A-Za-z0-9._-]+$")
_DIR = re.compile(r"^/[A-Za-z0-9._/-]*[A-Za-z0-9_-]$")  # absoluto, sem espaços/curingas, sem "/" final
SENHA_MIN = 12


def _openssl(*args: str, entrada=None) -> subprocess.CompletedProcess:
    # a senha vai por variável de ambiente (-pass env:), nunca na linha de comando
    return subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-pass", "env:BACKUP_SENHA", *args],
                          stdin=entrada, capture_output=True, text=False)


def main() -> int:
    if len(sys.argv) not in (3, 4):
        print(__doc__, file=sys.stderr)
        return 2
    host, diretorio = sys.argv[1], sys.argv[2]
    manter = sys.argv[3] if len(sys.argv) == 4 else "7"
    if not _HOST.match(host) or not _DIR.match(diretorio) or ".." in diretorio.split("/"):
        print(f"ERRO: host ou diretório inválido: {host} {diretorio}", file=sys.stderr)
        return 2
    if not manter.isdigit() or int(manter) < 1:
        print(f"ERRO: MANTER inválido: {manter}", file=sys.stderr)
        return 2
    if len(os.environ.get("BACKUP_SENHA", "")) < SENHA_MIN:
        print(f"ERRO: segredo BACKUP_SENHA ausente ou com menos de {SENHA_MIN} caracteres. "
              "Cadastre a Variable e ligue-a em 'Segredos' da rotina.", file=sys.stderr)
        return 2
    if not shutil.which("openssl"):
        print("ERRO: 'openssl' não está instalado no ambiente.", file=sys.stderr)
        return 1
    backups = os.environ.get("BACKUPS_DIR")
    if not backups:
        print("ERRO: BACKUPS_DIR não definida. Rode o script por uma rotina.", file=sys.stderr)
        return 2

    destino = Path(backups) / f"dir-{host}-{diretorio.strip('/').replace('/', '_')}"
    destino.mkdir(parents=True, exist_ok=True)
    nome = datetime.now().strftime("%Y%m%d-%H%M%S")
    remoto_tgz = f"/tmp/bk-{os.getpid()}-{nome}.tar.gz"

    with tempfile.TemporaryDirectory(prefix="bk-") as tmp:
        claro = Path(tmp) / "claro.tar.gz"
        parcial = destino / f"{nome}.tar.gz.enc.parcial"
        try:
            print(f"Compactando {diretorio} em {host}...")
            pai, base = os.path.split(diretorio)
            # umask 077: o arquivo temporário na VM fica legível só pelo usuário de serviço
            r = remoto(host, f"umask 077; tar czf {remoto_tgz} -C {pai or '/'} {base}", verificar=False, timeout=900)
            if r.codigo not in (0, 1):  # 1 = "arquivo mudou durante a leitura": backup válido
                print(f"ERRO: tar remoto falhou (código {r.codigo}): {r.erro.strip()[-400:]}", file=sys.stderr)
                return 1
            if r.codigo == 1:
                print("AVISO: arquivos mudaram durante a leitura; backup mantido.", file=sys.stderr)

            print("Copiando para o servidor...")
            receber(host, remoto_tgz, claro)
        finally:
            remoto(host, f"rm -f {remoto_tgz}", verificar=False)  # limpa a VM sempre

        print("Cifrando (AES-256)...")
        p = _openssl("-salt", "-in", str(claro), "-out", str(parcial))
        if p.returncode != 0:
            parcial.unlink(missing_ok=True)
            print(f"ERRO ao cifrar: {p.stderr.decode(errors='replace').strip()}", file=sys.stderr)
            return 1

        print("Conferindo que decifra e é um tar válido...")
        with open(parcial, "rb") as enc:
            dec = subprocess.Popen(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-pass", "env:BACKUP_SENHA"],
                                   stdin=enc, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            tar = subprocess.run(["tar", "tz"], stdin=dec.stdout, capture_output=True)
            dec.stdout.close()
            dec.wait()
        if dec.returncode != 0 or tar.returncode != 0:
            parcial.unlink(missing_ok=True)
            print("ERRO: o arquivo cifrado não passou na conferência; backup descartado.", file=sys.stderr)
            return 1
        arquivos = len(tar.stdout.splitlines())
        final = destino / f"{nome}.tar.gz.enc"
        parcial.rename(final)
    print(f"Backup criado: {final} ({final.stat().st_size / 1024:.0f} KB, {arquivos} itens)")

    for velho in sorted(destino.glob("*.tar.gz.enc"))[:-int(manter)]:
        velho.unlink()
        print(f"Removendo backup antigo: {velho.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
