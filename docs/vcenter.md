# Scripts para o vCenter

Os scripts falam com a **API REST do vCenter** (HTTPS, porta 443), não com o SSH do appliance. O shell `Command>` do VCSA serve para administrar o próprio appliance e não cria nem liga VMs; não habilite o bash dele para rodar automação.

## Pré-requisitos

- A máquina que roda o script alcança `https://IP-DO-VCENTER/` (porta 443).
- Um usuário do **SSO** do vCenter (`nome@vsphere.local` ou `nome@DOMINIO`). O `root` do appliance não vale para a API.
- vCenter 7.0U2 ou mais novo (rotas `/api/...`).
- Python 3.9+ (só biblioteca padrão; nada para instalar).

Teste rápido de acesso, sem alterar nada (o curl pede a senha):

```bash
curl -sk -X POST -u 'USUARIO' https://IP/api/session          # devolve um token
curl -sk -H "vmware-api-session-id: TOKEN" https://IP/api/vcenter/vm
curl -sk -X DELETE -H "vmware-api-session-id: TOKEN" https://IP/api/session
```

## `vcenter_energia.py`: ligar e desligar uma VM

```
vcenter_energia.py status   NOME_DA_VM
vcenter_energia.py ligar    NOME_DA_VM
vcenter_energia.py desligar NOME_DA_VM [--forcar] [--espera SEGUNDOS]
```

| Comportamento | Detalhe |
|---|---|
| Nome exato | Não achou, ou achou mais de uma VM com o nome: erro, nada é feito |
| `desligar` | Desligamento limpo pelo sistema operacional (VMware Tools) e espera até 300 s |
| Sem VMware Tools | Falha e avisa; só corta a energia com `--forcar` |
| `--forcar` | Corta a energia na hora (como puxar o cabo) |
| Repetir | Ligar o que já está ligado (ou desligar o desligado) só informa e sai com 0 |
| Sessão | Sempre encerrada no fim, mesmo com erro |
| Saída | 0 sucesso, 1 falha, 2 uso ou configuração inválida |

### Variáveis de ambiente

| Variável | Obrigatória | Para quê |
|---|---|---|
| `VCENTER_HOST` | sim | IP ou nome do vCenter (sem `https://`; aceita `HOST:PORTA`) |
| `VCENTER_USUARIO` | sim | Usuário do SSO |
| `VCENTER_SENHA` | sim | Senha |
| `VCENTER_CA` | não | Arquivo `.pem` da CA do vCenter, se ela não estiver no sistema |
| `VCENTER_INSEGURO=1` | não | Não valida o certificado (equivale ao `curl -k`). Só para teste; imprime aviso |
| `VCENTER_VMS_PERMITIDAS` | não | Nomes separados por vírgula. Qualquer outra VM é recusada antes de conectar |

**Certificado do vCenter:** baixe a CA em `https://IP/certs/download.zip` (pasta `certs/lin/`, arquivo `.0`), salve como `vcenter-ca.pem` e aponte `VCENTER_CA` para ele.

### Rodar à mão (ex.: na VM do Apache)

Guarde o acesso num arquivo só seu, fora de qualquer repositório Git:

```bash
install -m 600 /dev/null ~/.vcenter.env
cat > ~/.vcenter.env <<'EOF'
export VCENTER_HOST=IP-DO-VCENTER
export VCENTER_USUARIO=usuario@vsphere.local
export VCENTER_SENHA='a-senha'
export VCENTER_CA=$HOME/vcenter-ca.pem
export VCENTER_VMS_PERMITIDAS=vm-teste01
EOF
```

E rode, começando sempre pelo `status`:

```bash
source ~/.vcenter.env
python3 vcenter_energia.py status vm-teste01
python3 vcenter_energia.py desligar vm-teste01
python3 vcenter_energia.py ligar vm-teste01
```

### Como rotina do Airflow

Cadastre `VCENTER_HOST`, `VCENTER_USUARIO` e `VCENTER_SENHA` (e, se usar, `VCENTER_VMS_PERMITIDAS`) em **Segredos** da rotina, e passe `ligar NOME` ou `desligar NOME` em **Argumentos**. Use `timeout_min` maior que `--espera` (padrão: 5 min de espera, então 10 min de timeout).

## Ferramentas na imagem do Airflow

Para os próximos scripts (criar, destruir, recriar VMs):

| Ferramenta | Para quê |
|---|---|
| `govc` (Dockerfile, versão fixada com SHA-256) | CLI oficial da VMware: `govc vm.power -on NOME`, `govc vm.clone -vm TEMPLATE ...`, `govc vm.destroy`, `govc snapshot.*`. Lê `GOVC_URL`, `GOVC_USERNAME`, `GOVC_PASSWORD` (e `GOVC_TLS_CA_CERTS`) do ambiente |
| `jq` | Ler o JSON da API REST em scripts bash |
| `pyvmomi` | SDK Python oficial, para o que a API REST não cobre (customização de sistema, OVF, tarefas avançadas) |
