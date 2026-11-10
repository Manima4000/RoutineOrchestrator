import os
import time
from pathlib import Path

import pytest

from rotinas_core.execucao import (
    CodigoSaidaNaoZero,
    SemShebang,
    TempoEsgotado,
    executar,
)


def script(tmp_path, conteudo, nome="s.sh"):
    p = tmp_path / nome
    p.write_text(conteudo)
    return p


def pid_vivo(pid):
    try:
        estado = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (FileNotFoundError, ProcessLookupError):
        return False
    return estado != "Z"


def test_sucesso_e_log(tmp_path):
    s = script(tmp_path, "#!/bin/bash\necho ola $1\necho erro >&2\n")
    linhas = []
    executar(s, ["mundo"], {}, 30, linhas.append)
    assert "ola mundo" in linhas and "erro" in linhas


def test_codigo_nao_zero(tmp_path):
    with pytest.raises(CodigoSaidaNaoZero) as e:
        executar(script(tmp_path, "#!/bin/bash\nexit 3\n"), [], {}, 30, lambda _: None)
    assert e.value.codigo == 3 and "código de saída 3" in str(e.value)


def test_morto_por_sinal(tmp_path):
    with pytest.raises(CodigoSaidaNaoZero) as e:
        executar(script(tmp_path, "#!/bin/bash\nkill -KILL $$\n"), [], {}, 30, lambda _: None)
    assert e.value.codigo == -9 and "SIGKILL" in str(e.value)


def test_sem_shebang(tmp_path):
    with pytest.raises(SemShebang) as e:
        executar(script(tmp_path, "echo oi\n"), [], {}, 30, lambda _: None)
    assert "#!" in str(e.value)


def test_env_chega_ao_script(tmp_path):
    linhas = []
    executar(script(tmp_path, "#!/bin/bash\necho $SEGREDO_X\n"), [], {"SEGREDO_X": "abc"}, 30, linhas.append)
    assert linhas == ["abc"]


def test_timeout_mata_grupo_inclusive_filhos_que_ignoram_term(tmp_path):
    marca = tmp_path / "filho.pid"
    s = script(tmp_path, f"#!/bin/bash\ntrap '' TERM\n(trap '' TERM; echo $BASHPID > {marca}; sleep 300) &\nsleep 300\n")
    with pytest.raises(TempoEsgotado) as e:
        executar(s, [], {}, 1, lambda _: None)
    assert "1 s excedido" in str(e.value)
    pid = int(marca.read_text())
    assert not pid_vivo(pid)


def test_timeout_sem_nenhuma_saida_e_mensagem_em_minutos(tmp_path):
    s = script(tmp_path, "#!/bin/bash\nexec sleep 300\n")
    t0 = time.monotonic()
    with pytest.raises(TempoEsgotado) as e:
        executar(s, [], {}, 2, lambda _: None)
    assert time.monotonic() - t0 < 8
    from rotinas_core.execucao import _msg_timeout

    assert _msg_timeout(60) == "Tempo limite de 1 min excedido"
    assert _msg_timeout(90) == "Tempo limite de 90 s excedido"


def test_filho_em_segundo_plano_nao_trava_nem_fica_orfao(tmp_path):
    marca = tmp_path / "bg.pid"
    s = script(tmp_path, f"#!/bin/bash\nsleep 300 &\necho $! > {marca}\necho fim\n")
    t0 = time.monotonic()
    linhas = []
    executar(s, [], {}, 60, linhas.append)
    assert time.monotonic() - t0 < 15
    assert linhas == ["fim"]
    assert not pid_vivo(int(marca.read_text()))


def test_bytes_invalidos_e_saida_grande(tmp_path):
    s = script(tmp_path, "#!/bin/bash\nprintf '\\xff\\xfe ok\\n'\nseq 1 200000\n")
    linhas = []
    executar(s, [], {}, 60, linhas.append)
    assert linhas[0].endswith(" ok") and len(linhas) == 200001


def test_diretorio_temporario_removido(tmp_path):
    linhas = []
    executar(script(tmp_path, "#!/bin/bash\npwd\n"), [], {}, 30, linhas.append)
    assert not Path(linhas[0]).exists()
