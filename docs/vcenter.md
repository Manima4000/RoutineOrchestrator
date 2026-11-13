# Acesso do Airflow ao vCenter

Guia para deixar o servidor do Airflow controlar VMs do vCenter (hoje: ligar, desligar e consultar com `vcenter_energia.py`; depois: criar, destruir e recriar). Tem duas partes: o que o **administrador do vCenter** faz e o que se faz **no servidor do Airflow**.

## Como funciona

```
Servidor do Airflow (VM no vCenter)                    vCenter (VCSA)
 └─ container airflow-scheduler                         ┌──────────────────────┐
     └─ script da rotina ── HTTPS 443, API REST ──────▶ │ /api/session  (login)│
        (usuário, senha e CA vêm dos Segredos           │ /api/vcenter/vm/...  │
         da rotina: Connection + Variables)             └──────────────────────┘
```

- O script usa a **API REST do vCenter** (HTTPS, porta 443), a mesma da interface web. **Não usa SSH.**
- O SSH do appliance (shell `Command>`) serve para administrar o próprio VCSA e não liga nem cria VMs. Não habilite o bash do appliance para rodar automação: em produção isso fica fora do suportado pela VMware.
- Quem roda o script é o container do Airflow. Por isso é o **servidor do Airflow** que precisa alcançar o vCenter, não a sua máquina.
- Requisito: vCenter 7.0U2 ou mais novo (rotas `/api/...`).

---

## Parte 1: no vCenter (administrador do vCenter)

Tudo pelo vSphere Client (`https://VCENTER/ui`), com um usuário administrador.

### 1.1 Usuário de serviço

Crie um usuário só para a automação. Não use o `administrator@vsphere.local` nem o usuário pessoal de alguém.

1. **Administração > Single Sign On > Usuários e grupos > Usuários**, domínio `vsphere.local` (ou o domínio AD, se for o padrão da casa) **> Adicionar**.
2. Nome: `svc-airflow`. Senha longa e aleatória.
3. **Validade da senha.** No `vsphere.local`, a senha expira por padrão em **90 dias**. Quando expirar, todas as rotinas do vCenter começam a falhar com "recusou o usuário ou a senha". Escolha uma das opções:
   - ajuste a política em **Administração > Single Sign On > Configuração > Contas locais > Política de senha**, se a norma permitir;
   - ou registre a data de troca e, ao trocar a senha, atualize a Connection `vcenter` no Airflow (Parte 2).

> O `root` do appliance (usado no SSH) **não** serve para a API: ela só aceita usuários do SSO (`nome@vsphere.local` ou `nome@DOMINIO`).

### 1.2 Função (role) com o mínimo de privilégios

**Administração > Controle de acesso > Funções > Novo**. Nome sugerido: `Airflow - Energia de VMs`. Marque:

| Privilégio | Para quê |
|---|---|
| Máquina virtual > Interação > **Ligar** | `ligar` |
| Máquina virtual > Interação > **Desligar** | `desligar` (inclusive o desligamento limpo pelo sistema operacional e o `--forcar`) |

Na interface em inglês: *Virtual machine > Interaction > Power on* e *Power off*. Leitura (listar VMs, ver estado e VMware Tools) já vem em qualquer função.

Quando os scripts de **criar e destruir** entrarem, crie uma segunda função (`Airflow - Provisionamento`) com estes privilégios a mais:

| Privilégio | Para quê |
|---|---|
| Máquina virtual > Inventário > Criar a partir de existente, Remover | criar por clone e destruir |
| Máquina virtual > Provisionamento > Clonar máquina virtual, Implantar modelo | clonar do template |
| Máquina virtual > Configuração > CPU, Memória, Adicionar disco novo, Estender disco virtual, Configurações | ajustar CPU, RAM e disco |
| Máquina virtual > Edição de convidado / Personalizar | IP e hostname na criação |
| Recurso > Atribuir máquina virtual ao pool de recursos | colocar a VM no cluster/pool |
| Repositório de dados > Alocar espaço | disco no datastore |
| Rede > Atribuir rede | placa de rede no port group |

### 1.3 Permissão só onde a automação pode mexer

Dê a função **apenas** nas VMs ou pastas que a automação controla, nunca na raiz do vCenter:

1. Em **VMs e modelos**, crie (ou escolha) uma pasta, por exemplo `Automacao`, e mova para ela as VMs que as rotinas podem ligar e desligar.
2. Pasta **> Permissões > Adicionar**: usuário `svc-airflow`, função `Airflow - Energia de VMs`, marque **Propagar para filhos**.

Assim, mesmo que uma rotina seja configurada com o nome errado, o vCenter recusa agir em VMs fora da pasta. É a trava mais forte: vale mesmo se alguém editar o script.

Para os scripts de criação, a permissão vai também no cluster ou resource pool, no datastore e no port group de destino, e na pasta onde fica o template.

### 1.4 Rede

Libere, no firewall entre os dois, **TCP 443** do IP do servidor do Airflow para o IP do vCenter. Nenhuma outra porta é necessária. Saber o FQDN do vCenter ajuda: o certificado costuma ser emitido para o nome, não para o IP (ver 2.3).

### 1.5 O que entregar para quem configura o Airflow

- IP **e** FQDN do vCenter.
- Usuário (`svc-airflow@vsphere.local`) e senha, por canal seguro.
- Data de expiração da senha.
- Nome da pasta com as VMs liberadas.

---

## Parte 2: no servidor do Airflow

Na VM do Airflow, dentro do diretório do projeto. Os comandos `docker compose exec` rodam **dentro do container**, que é de onde as rotinas saem.

### 2.1 Imagem com as ferramentas do vCenter

O script `vcenter_energia.py` usa só o Python da imagem. Para os próximos scripts, a imagem já traz `govc`, `jq` e `pyvmomi` (ver [Ferramentas na imagem](#ferramentas-na-imagem)). Garanta que os containers estão com a imagem atual:

```bash
git pull
docker compose up -d --build
docker compose exec airflow-scheduler govc version     # govc 0.56.x
```

### 2.2 O container alcança o vCenter?

```bash
docker compose exec airflow-scheduler curl -sk -o /dev/null -w '%{http_code}\n' https://VCENTER/api
```

| Resultado | Significado |
|---|---|
| `404` | Alcança (é a resposta normal da raiz `/api`) |
| `000` | Não alcança: firewall (1.4), rota ou DNS. Confira também se a sub-rede do Docker (`DOCKER_SUBNET` no `.env`, padrão `172.30.0.0/24`) não coincide com a rede do vCenter. Se coincidir, troque-a e rode `docker compose up -d` |

Se a VM usa proxy para a internet: os containers não recebem proxy, e o acesso ao vCenter precisa ser direto, pela rede interna.

### 2.3 Certificado do vCenter (CA)

O vCenter assina o próprio certificado com uma CA interna (VMCA), que o container não conhece. Sem ela, o script para com "certificado do vCenter não é confiável". Para baixar e conferir a CA:

```bash
curl -sk -o certs.zip https://VCENTER/certs/download.zip
python3 -m zipfile -e certs.zip vcca/
cat vcca/certs/lin/*.0 > vcenter-ca.pem      # pode haver mais de um .0; vão todos
docker compose cp vcenter-ca.pem airflow-scheduler:/tmp/vcenter-ca.pem
docker compose exec airflow-scheduler curl --cacert /tmp/vcenter-ca.pem -s -o /dev/null -w '%{http_code}\n' https://VCENTER/api
```

- `404`: a CA está certa.
- Erro com `subject name` / `no alternative certificate subject name matches`: o certificado foi emitido para o FQDN. Use o **FQDN** no lugar do IP, no teste e no campo Host da Connection (2.4).

O conteúdo de `vcenter-ca.pem` vai para a Variable `vcenter_ca_pem` (2.5). Os arquivos baixados não precisam ficar no servidor depois disso. A CA é pública e não é segredo.

### 2.4 Connection `vcenter` (usuário e senha)

**Admin > Connections > Adicionar**:

| Campo | Valor |
|---|---|
| Connection Id | `vcenter` |
| Connection Type | `HTTP` (o tipo é só um rótulo; **não** use `SSH`) |
| Host | FQDN ou IP do vCenter, sem `https://` e sem porta |
| Login | `svc-airflow@vsphere.local` |
| Password | a senha |
| Port, Schema, Extra | em branco |

**Não** coloque nada disso no `.env`: o `.env` é a configuração do próprio Airflow e não chega aos scripts. Ao trocar a senha no vCenter, edite só esta Connection; as rotinas passam a usar a nova senha na próxima execução.

### 2.5 Variables

**Admin > Variables > Adicionar**:

| Key | Val | Obrigatória |
|---|---|---|
| `vcenter_ca_pem` | conteúdo inteiro de `vcenter-ca.pem`, de `-----BEGIN CERTIFICATE-----` até `-----END CERTIFICATE-----` (se houver mais de um certificado, todos) | sim |
| `vcenter_vms_permitidas` | nomes das VMs que as rotinas podem tocar, separados por vírgula (ex.: `web-teste01,web-teste02`) | recomendada |

`vcenter_vms_permitidas` é uma segunda trava, do lado do Airflow, além da permissão por pasta (1.3): o script recusa qualquer VM fora da lista antes mesmo de conectar.

### 2.6 Script no ambiente

Copie para a pasta de scripts do diretório de dados, para ele aparecer em *Usar um script já existente*:

```bash
mkdir -p /opt/airflow-rotinas/dados/scripts/vcenter
cp scripts_base/exemplos/scripts/vcenter_energia.py /opt/airflow-rotinas/dados/scripts/vcenter/
```

(Ou envie o arquivo direto no formulário da rotina com *Enviar arquivo*.) A rotina usa a cópia do diretório de dados: se o script for atualizado no repositório, copie de novo ou reenvie pela tela.

### 2.7 Criar a rotina

Tela **Rotinas > Nova rotina**. Os argumentos ficam fixos na rotina, então crie **uma rotina por ação** (ex.: `vcenter_status_web01`, `vcenter_desliga_web01`, `vcenter_liga_web01`). Comece pela de `status`, que só lê.

| Bloco | Preenchimento |
|---|---|
| Identificação | Nome como acima. **Rotina ativa desmarcada** enquanto testa (dispare com Trigger) |
| Horário | O desejado (ex.: desligar sexta 19:00 e ligar segunda 07:00). Com a rotina inativa, não importa |
| Script | `vcenter/vcenter_energia.py`. **Argumentos**, um por linha: `status` (ou `ligar`, `desligar`) e o nome exato da VM. `--forcar` numa terceira linha só se for para cortar a energia |
| Segredos | Tabela abaixo |
| Execução | *Novas tentativas* `0` nos testes (depois `1`, pode repetir sem dano). *Tempo máximo* `10` min (o desligamento espera até 5) |

Segredos:

| Variável | Origem |
|---|---|
| `VCENTER_HOST` | Connection `vcenter`, campo `host` |
| `VCENTER_USUARIO` | Connection `vcenter`, campo `login` |
| `VCENTER_SENHA` | Connection `vcenter`, campo `password` |
| `VCENTER_CA_PEM` | Variable `vcenter_ca_pem` |
| `VCENTER_VMS_PERMITIDAS` | Variable `vcenter_vms_permitidas` |

### 2.8 Conferir

Dispare com **Trigger**. Log esperado de `status`:

```
Conectando em *** como ***...
web01 (vm-1234): POWERED_ON (ligada), VMware Tools: RUNNING
```

Host e usuário aparecem como `***` porque vêm de segredos. Isso é normal.

Para descobrir o nome de uma VM pelo IP, use a busca do vSphere Client (digite o IP) ou o `govc` no container:

```bash
docker compose exec airflow-scheduler bash
export GOVC_URL=VCENTER GOVC_USERNAME='svc-airflow@vsphere.local' GOVC_TLS_CA_CERTS=/tmp/vcenter-ca.pem
read -rs -p 'Senha: ' GOVC_PASSWORD; export GOVC_PASSWORD; echo
govc vm.info -vm.ip=10.0.0.10        # linha "Name:"; exige VMware Tools rodando na VM
```

### 2.9 Problemas comuns

| Mensagem no log | Causa e solução |
|---|---|
| `certificado do vCenter não é confiável` | Falta `VCENTER_CA_PEM` nos Segredos ou a Variable está incompleta (2.3, 2.5) |
| `Hostname mismatch` / `doesn't match` | Certificado emitido para o FQDN: use o FQDN no Host da Connection |
| `não foi possível conectar` | Rede ou firewall (2.2, 1.4) |
| `o vCenter recusou o usuário ou a senha` | Senha errada ou **expirada** (1.1), ou usuário fora do SSO (ex.: `root`) |
| `variável de ambiente VCENTER_... não definida` | Falta a linha correspondente em Segredos (2.7) |
| `VM '...' não encontrada` | Nome diferente do vCenter (maiúsculas contam) ou a VM está fora das permissões do usuário (1.3) |
| `há mais de uma VM chamada` | Nomes repetidos no vCenter: renomeie uma delas |
| `fora da lista VCENTER_VMS_PERMITIDAS` | Acrescente a VM na Variable `vcenter_vms_permitidas` |
| `devolveu 403` / `NOT_ALLOWED` / `UNAUTHORIZED` | O usuário não tem o privilégio na VM: função ou permissão (1.2, 1.3) |
| `VMware Tools ... não está rodando` | Instale ou inicie o Tools na VM, ou use `--forcar` (corta a energia) |
| `não desligou em 300 s` | O sistema operacional travou no desligamento: veja o console da VM; se necessário, rode com `--forcar` |
| `VCENTER_CA_PEM não contém um certificado PEM válido` | Variable colada pela metade, sem as linhas `BEGIN`/`END` |

---

## Referência: `vcenter_energia.py`

```
vcenter_energia.py status   NOME_DA_VM
vcenter_energia.py ligar    NOME_DA_VM
vcenter_energia.py desligar NOME_DA_VM [--forcar] [--espera SEGUNDOS]
```

| Comportamento | Detalhe |
|---|---|
| Nome exato | Não achou, ou achou mais de uma VM com o nome: erro, nada é feito |
| `desligar` | Desligamento limpo pelo sistema operacional (VMware Tools) e espera até `--espera` s (padrão 300) |
| Sem VMware Tools | Falha e avisa; só corta a energia com `--forcar` |
| `--forcar` | Corta a energia na hora (como puxar o cabo) |
| Repetir | Ligar o que já está ligado (ou desligar o desligado) só informa e sai com 0 |
| Sessão | Sempre encerrada no fim, mesmo com erro |
| Saída | 0 sucesso, 1 falha, 2 uso ou configuração inválida |

| Variável de ambiente | Obrigatória | Para quê |
|---|---|---|
| `VCENTER_HOST` | sim | IP ou FQDN do vCenter (sem `https://`; aceita `HOST:PORTA`) |
| `VCENTER_USUARIO` | sim | Usuário do SSO |
| `VCENTER_SENHA` | sim | Senha |
| `VCENTER_CA_PEM` | não* | **Conteúdo** do `.pem` da CA do vCenter |
| `VCENTER_CA` | não* | Caminho de um arquivo `.pem` da CA (alternativa para rodar à mão) |
| `VCENTER_INSEGURO=1` | não | Não valida o certificado (como `curl -k`). Só para diagnóstico; imprime aviso. Não use em rotina |
| `VCENTER_VMS_PERMITIDAS` | não | Nomes separados por vírgula; outras VMs são recusadas antes de conectar |

\* Uma das duas é necessária, a menos que a CA do vCenter já seja confiável no sistema.

### Rodar à mão, fora do Airflow

Útil para testar de outra máquina que alcança o vCenter. Guarde o acesso num arquivo só seu, fora de qualquer repositório Git:

```bash
install -m 600 /dev/null ~/.vcenter.env
cat > ~/.vcenter.env <<'EOF'
export VCENTER_HOST=VCENTER
export VCENTER_USUARIO=svc-airflow@vsphere.local
export VCENTER_SENHA='a-senha'
export VCENTER_CA=$HOME/vcenter-ca.pem
export VCENTER_VMS_PERMITIDAS=web-teste01
EOF
source ~/.vcenter.env
python3 vcenter_energia.py status web-teste01
```

## Ferramentas na imagem

Para os próximos scripts (criar, destruir, recriar VMs):

| Ferramenta | Onde é declarada | Para quê |
|---|---|---|
| `govc` | `Dockerfile` (versão fixada, SHA-256 conferido no build) | CLI oficial da VMware: `govc vm.power -on NOME`, `govc vm.clone -vm TEMPLATE ...`, `govc vm.destroy`, `govc snapshot.*`. Lê `GOVC_URL`, `GOVC_USERNAME`, `GOVC_PASSWORD` e `GOVC_TLS_CA_CERTS` do ambiente |
| `jq` | `ferramentas/sistema.txt` | Ler o JSON da API REST em scripts bash |
| `pyvmomi` | `ferramentas/python.txt` | SDK Python oficial, para o que a API REST não cobre (customização de sistema, OVF, tarefas avançadas) |

Para atualizar o `govc`, troque `GOVC_VERSAO` e os dois `GOVC_SHA256_*` no `Dockerfile` (valores do `checksums.txt` da release em github.com/vmware/govmomi) e rode `docker compose up -d --build`.
