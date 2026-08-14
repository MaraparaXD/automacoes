# Pipeline CI/CD — Atualização de Sites CheckMK

> Versão generalizada de um pipeline de automação que desenvolvi em ambiente
> profissional. Nomes de empresa, domínio interno e identificadores de
> cliente foram removidos ou substituídos por exemplos genéricos — a lógica
> e a arquitetura são as mesmas.

Automação da atualização de versão dos sites CheckMK rodando em Docker
Compose, para centenas de clientes atendidos em um modelo multi-tenant. Cada site roda em seu próprio
host, isolado em `/opt/checkmk-container/<sigla>/`.

## Estrutura do projeto

```
checkmk-pipeline/
├── README.md                          este arquivo
├── requirements.txt                   dependências Python
├── inventory.example.yaml             exemplo — copie para inventory.yaml
├── .gitlab-ci.yml                     pipeline GitLab CI (chama deploy_host.py)
├── playbook.yml                       wrapper Ansible fino (para o AWX)
├── ldap-connection-template.py        esqueleto da config de LDAP (pendente de confirmação com o time responsável)
├── templates/
│   └── docker-compose.yml             template canônico, copiado para cada site
├── scripts/
│   ├── gerar_pipeline.py              lê inventory.yaml, gera o child pipeline do GitLab CI
│   ├── sync_from_awx.py               gera inventory.yaml a partir do AWX
│   └── sync_from_checkmk_master.py    gera inventory.yaml a partir do CheckMK Master
├── checkmk_pipeline/                  pacote Python com a lógica real
│   ├── __init__.py
│   ├── core.py                        lógica de UM site: backup, docker compose, saúde, reversão
│   ├── host_bootstrap.py              Etapa 3 (DNS) + Etapa 6 (agente no host)
│   ├── ldap_config.py                 configura LDAP via API REST do CheckMK
│   ├── deploy_host.py                 entrada minimalista: --ip + variáveis de ambiente
│   └── orchestrator.py                entrada em lote: piloto + lotes paralelos
```

## Como cada site é organizado no host

```
/opt/checkmk-container/<sigla>/
├── docker-compose.yml     <- copiado automaticamente do template a cada execução
└── dados/                  <- bind mount, vira /omd/sites dentro do container
```

- Porta web: **80** (fixa, padrão, igual em todos os sites)
- Porta do agente: **6556** (fixa, padrão clássico do Check_MK)
- Sem conflito de porta porque cada site roda em host próprio

## Dois pontos de entrada — quando usar cada um

### `deploy_host.py` — um site por vez, via IP + variáveis de ambiente

Pensado para o **AWX** chamar (via `playbook.yml`) ou para o **GitLab CI**
chamar (via `.gitlab-ci.yml`, um job por site usando `parallel: matrix`).

```bash
export SITE_SIGLA=abc
export NOVA_VERSAO=2.5.0-latest
export CMK_PASSWORD=senha123
export CLIENTE_NOME="Cliente ABC"
python3 -m checkmk_pipeline.deploy_host --ip 192.168.1.50
```

### `orchestrator.py` — vários sites de uma vez, com piloto + lotes

Útil se você quiser rodar o pipeline **sem depender do AWX/GitLab CI**
controlando o paralelismo — a lógica de piloto e lotes fica dentro do
próprio Python.

```bash
export CMK_PASSWORD=senha123
python3 -m checkmk_pipeline.orchestrator \
  --inventario inventory.yaml \
  --versao 2.5.0p9 \
  --piloto abc \
  --tamanho-lote 10 \
  --paralelismo 4
```

> 📌 Ainda não decidido: se o AWX vai controlar o
> paralelismo/lotes (chamando `deploy_host.py` várias vezes) ou se o
> `orchestrator.py` continua fazendo esse controle. Ver seção de
> assunções abaixo.

## Testando com segurança (simulação)

Os dois pontos de entrada aceitam modo simulação — não roda nenhum
comando de verdade, só mostra o que seria executado:

```bash
# deploy_host.py
SIMULACAO=1 python3 -m checkmk_pipeline.deploy_host --ip 192.168.1.50

# orchestrator.py
python3 -m checkmk_pipeline.orchestrator --versao 2.5.0p9 --simulacao
```

## Instalação

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp inventory.example.yaml inventory.yaml   # ajuste com os seus sites
```

## Integração com GitLab CI

O `.gitlab-ci.yml` já está pronto para uso — só falta:

1. Cadastrar `CMK_PASSWORD` em **Settings → CI/CD → Variables**
   (marcada como **Protected** e **Masked** — nunca hardcoded no YAML)
2. Ajustar a lista de sites no bloco `matrix` (hoje só tem 3 de exemplo)
3. Garantir que o `gitlab-runner` tem permissão de root (ou sudo
   configurado) para instalar o agente e mexer em `/opt/checkmk-container`

## Integração com AWX

O `playbook.yml` é um wrapper fino — não reimplementa lógica, só resolve
host/credenciais via AWX e chama `deploy_host.py`. Ver comentários no
próprio arquivo para detalhes de `become: true` e variáveis esperadas.

---

## ⚠️ Assunções que ainda precisam de validação

1. **Motor de execução**: confirmado com o time responsável — é **Docker Compose**,
   um projeto isolado por site (`docker compose -p <sigla>`). ✅ Resolvido.
2. **Estrutura de diretório**: confirmado — `/opt/checkmk-container/<sigla>/`
   com `docker-compose.yml` + `dados/` juntos. ✅ Resolvido.
3. **Portas**: confirmado — web fixa em `80`, agente fixo em `6556`,
   já que cada site tem host próprio. ✅ Resolvido.
4. **Backup**: usa `docker compose exec omd backup`. Confirmar se a empresa
   já tem outra estratégia (snapshot de disco, backup do host) para não
   duplicar.
5. **Template visual do ambiente corporativo** (logo, CSS): fora de escopo por decisão
   explícita (Etapa 8 ignorada).
6. **AWX vs orchestrator.py**: quem controla paralelismo/lotes — o AWX
   (chamando `deploy_host.py` várias vezes) ou o `orchestrator.py`
   (fazendo isso internamente)? Ver decisão pendente sobre a
   integração AWX/Ansible.
7. **Login via LDAP/AD**: pendente — falta endereço/porta do servidor
   LDAP, usuário de bind, base DN e grupos de AD por nível de acesso.
   Ver `ldap-connection-template.py`.
8. **Permissões do host**: instalação do agente (Etapa 6) e escrita em
   `/opt/checkmk-container` exigem root. Confirmar se o `gitlab-runner`
   já roda como root nesse ambiente ou se precisa de sudoers dedicado
   (mesmo padrão que resolvemos no lab: `NOPASSWD` restrito a comandos
   específicos, nunca sudo geral).
