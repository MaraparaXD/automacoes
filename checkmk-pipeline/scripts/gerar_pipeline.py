"""
scripts/gerar_pipeline.py

Lê o inventory.yaml e gera um arquivo YAML de "child pipeline" do GitLab CI.
Diferente da versão anterior, este script agora implementa a segurança do 
ORQUESTRADOR: ele separa os clientes em um estágio de PILOTO e divide o 
restante em LOTES sequenciais. Se um lote falhar, o GitLab interrompe o deploy.

Uso:
    export PILOTOS="abc,xyz" (opcional)
    export TAMANHO_LOTE="10" (opcional)
    python3 scripts/gerar_pipeline.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
INVENTARIO = RAIZ / "inventory.yaml"
SAIDA = RAIZ / "generated-pipeline.yml"


def dividir_em_lotes(lista: list, tamanho: int):
    """Gera pedaços da lista baseados no tamanho do lote."""
    for i in range(0, len(lista), tamanho):
        yield lista[i : i + tamanho]


def gerar() -> None:
    if not INVENTARIO.exists():
        print(f"ERRO: {INVENTARIO} não encontrado.", file=sys.stderr)
        sys.exit(1)

    with open(INVENTARIO, encoding="utf-8") as f:
        dados = yaml.safe_load(f)

    sites = dados.get("sites", [])
    if not sites:
        print("ERRO: inventory.yaml não tem nenhum site em 'sites:'.", file=sys.stderr)
        sys.exit(1)

    # Configurações de segurança baseadas no ambiente
    pilotos_env = os.environ.get("PILOTOS", "").split(",")
    pilotos_siglas = [s.strip() for s in pilotos_env if s.strip()]
    tamanho_lote = int(os.environ.get("TAMANHO_LOTE", "10"))

    sites_piloto = [s for s in sites if s["sigla"] in pilotos_siglas]
    sites_resto = [s for s in sites if s["sigla"] not in pilotos_siglas]

    # Regra de segurança: Se nenhum piloto for definido explicitamente, 
    # pega o primeiro site da lista automaticamente para atuar como piloto.
    if not sites_piloto and sites_resto:
        sites_piloto = [sites_resto.pop(0)]

    lotes = list(dividir_em_lotes(sites_resto, tamanho_lote))

    # Estrutura base do pipeline do GitLab
    pipeline_gerado = {
        "stages": [],
        "variables": {
            "NOVA_VERSAO": "$NOVA_VERSAO",
        }
    }

    # Template do job executado em cada máquina
    base_job = {
        "before_script": [
            "python3 -m pip install -r requirements.txt --quiet --break-system-packages",
        ],
        "script": [
            'echo "==============================="',
            'echo "Deploy do site ${SITE_SIGLA} (${CLIENTE_NOME})"',
            'echo "==============================="',
            'test -n "$CMK_PASSWORD" || (echo "ERRO: CMK_PASSWORD não definida." && exit 1)',
            'python3 -m checkmk_pipeline.deploy_host --ip "$(hostname -I | awk \'{print $1}\')"',
        ]
    }

    estagio_anterior = None

    # 1. Criação do Job Piloto
    if sites_piloto:
        nome_estagio = "piloto"
        pipeline_gerado["stages"].append(nome_estagio)

        matriz_piloto = [{"SITE_SIGLA": s["sigla"], "CLIENTE_NOME": s.get("cliente", "desconhecido")} for s in sites_piloto]

        job_piloto = base_job.copy()
        job_piloto["stage"] = nome_estagio
        job_piloto["parallel"] = {"matrix": matriz_piloto}
        
        pipeline_gerado["deploy_piloto"] = job_piloto
        estagio_anterior = "deploy_piloto"

    # 2. Criação dos Jobs em Lotes (Sequenciais)
    for i, lote in enumerate(lotes, start=1):
        nome_estagio = f"lote_{i}"
        pipeline_gerado["stages"].append(nome_estagio)

        matriz_lote = [{"SITE_SIGLA": s["sigla"], "CLIENTE_NOME": s.get("cliente", "desconhecido")} for s in lote]

        job_lote = base_job.copy()
        job_lote["stage"] = nome_estagio
        job_lote["parallel"] = {"matrix": matriz_lote}
        
        # A tag 'needs' garante que este lote SÓ rode se o anterior passar
        if estagio_anterior:
            job_lote["needs"] = [estagio_anterior]

        pipeline_gerado[f"deploy_lote_{i}"] = job_lote
        estagio_anterior = f"deploy_lote_{i}"

    # Salva o arquivo YAML
    with open(SAIDA, "w", encoding="utf-8") as f:
        yaml.dump(pipeline_gerado, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"Pipeline gerado com segurança em {SAIDA}")
    print(f"  - Piloto: {len(sites_piloto)} site(s)")
    print(f"  - Restante: {len(sites_resto)} site(s) em {len(lotes)} lote(s) de até {tamanho_lote}.")


if __name__ == "__main__":
    gerar()