"""
scripts/sync_from_awx.py

Gera o inventory.yaml automaticamente a partir do inventário do AWX.
Este script é fundamental para manter a Fonte da Verdade sincronizada
sem intervenção manual. Deve ser executado no início do pipeline do GitLab CI.

Requisitos de ambiente:
    AWX_URL: URL base do AWX (ex: https://awx.suaempresa.cloud)
    AWX_TOKEN: Token de acesso à API (cadastrado no GitLab como Masked Variable)
    AWX_INVENTARIO_NOME: Nome do inventário alvo (Padrão: "Clientes CheckMK")
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
import yaml

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "inventory.yaml"


def buscar_hosts_awx(url_base: str, token: str, nome_inventario: str) -> list[dict]:
    """
    Busca os hosts de um inventário específico no AWX via API REST (v2),
    tratando a paginação nativa da ferramenta.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }

    print(f"Buscando ID do inventário '{nome_inventario}' no AWX...")
    
    # 1. Resolver o ID do inventário pelo nome
    resp = requests.get(
        f"{url_base}/api/v2/inventories/",
        headers=headers,
        params={"name": nome_inventario},
        timeout=15,
    )
    resp.raise_for_status()
    resultados = resp.json().get("results", [])
    
    if not resultados:
        raise RuntimeError(f"Inventário '{nome_inventario}' não encontrado no AWX. Verifique o nome configurado.")
    
    inventario_id = resultados[0]["id"]
    print(f"Inventário localizado (ID: {inventario_id}). Baixando hosts...")

    # 2. Listar todos os hosts desse inventário processando a paginação
    hosts = []
    url_hosts = f"{url_base}/api/v2/inventories/{inventario_id}/hosts/"
    
    while url_hosts:
        resp_hosts = requests.get(url_hosts, headers=headers, timeout=15)
        resp_hosts.raise_for_status()
        dados = resp_hosts.json()
        
        hosts.extend(dados.get("results", []))
        url_hosts = dados.get("next")  # O AWX retorna o link da próxima página se houver mais resultados

    return hosts


def converter_para_inventory_yaml(hosts_awx: list[dict]) -> dict:
    """
    Processa os dados brutos da API do AWX e formata no padrão esperado
    pelo orchestrator.py e gerar_pipeline.py.
    """
    sites = []
    
    for host in hosts_awx:
        # O AWX retorna as variáveis do host em formato de string (JSON ou YAML)
        raw_vars = host.get("variables", "{}")
        if not raw_vars:
            raw_vars = "{}"
            
        variaveis = yaml.safe_load(raw_vars) or {}
        
        # Mapeamento de variáveis corporativas
        sigla = variaveis.get("sigla") or host.get("name")
        cliente = variaveis.get("cliente", host.get("name"))

        sites.append({
            "sigla": sigla,
            "cliente": cliente,
            "porta_web": variaveis.get("porta_web", 80),
            "porta_agent": variaveis.get("porta_agent", 6556),
            "imagem_tag_atual": variaveis.get("imagem_tag_atual", "2.5.0-latest"),
            "diretorio_compose": variaveis.get("diretorio_compose", f"/opt/checkmk-container/{sigla}")
        })

    return {"sites": sites}


def main() -> None:
    url_base = os.environ.get("AWX_URL")
    token = os.environ.get("AWX_TOKEN")
    nome_inventario = os.environ.get("AWX_INVENTARIO_NOME", "Clientes CheckMK")

    if not url_base or not token:
        print("ERRO CRÍTICO: As variáveis de ambiente AWX_URL e AWX_TOKEN são obrigatórias.", file=sys.stderr)
        sys.exit(1)

    try:
        hosts = buscar_hosts_awx(url_base, token, nome_inventario)
        print(f"Total de {len(hosts)} host(s) extraído(s) do AWX.")

        dados_inventario = converter_para_inventory_yaml(hosts)

        with open(SAIDA, "w", encoding="utf-8") as f:
            yaml.dump(dados_inventario, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        print(f"Arquivo Fonte da Verdade ({SAIDA.name}) atualizado com sucesso com {len(dados_inventario['sites'])} site(s).")
        
    except requests.RequestException as e:
        print(f"ERRO DE CONEXÃO COM O AWX: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERRO INESPERADO: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()