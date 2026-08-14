"""
scripts/sync_from_checkmk_master.py

Gera o inventory.yaml automaticamente a partir dos sites já cadastrados
no painel MASTER do CheckMK (Distributed Monitoring).

Esta é uma alternativa ao sync_from_awx.py, caso a Fonte da Verdade 
seja a própria configuração de monitoramento distribuído.

Requisitos de ambiente:
    CMK_MASTER_URL: URL do painel master (ex: https://checkmk-master.suaempresa.cloud)
    CMK_MASTER_SITE: Nome do site no master (ex: matriz)
    CMK_MASTER_USER: Usuário de automação
    CMK_MASTER_SECRET: Secret de automação
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
import yaml

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "inventory.yaml"


def buscar_sites_conectados(url_base: str, site_master: str, usuario: str, secret: str) -> list[dict]:
    """
    Consulta a API REST oficial do CheckMK (v1.0) para listar os sites 
    conectados via Distributed Monitoring.
    """
    url = f"{url_base}/{site_master}/check_mk/api/1.0/domain-types/site_connection/collections/all"
    
    headers = {
        "Authorization": f"Bearer {usuario} {secret}",
        "Accept": "application/json",
    }

    print(f"Conectando à API do CheckMK Master em: {url_base}/{site_master}...")

    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    
    dados = resp.json().get("value", [])
    if not dados:
        print("Aviso: A API retornou com sucesso, mas nenhum site conectado foi encontrado.")
        
    return dados


def converter_para_inventory_yaml(sites_master: list[dict]) -> dict:
    """
    Converte os metadados da API do CheckMK para o formato estruturado
    esperado pelo pipeline (inventory.yaml).
    """
    sites = []
    
    for entrada in sites_master:
        extensoes = entrada.get("extensions", {})
        
        # O ID na conexão distribuída normalmente corresponde à sigla do cliente
        sigla = entrada.get("id", "")
        
        if not sigla:
            continue

        # O alias/title configurado no master serve como nome do cliente
        cliente = extensoes.get("basic_settings", {}).get("alias", sigla)

        sites.append({
            "sigla": sigla,
            "cliente": cliente,
            "porta_web": 80,
            "porta_agent": 6556,
            "imagem_tag_atual": "2.5.0-latest",
            "diretorio_compose": f"/opt/checkmk-container/{sigla}"
        })

    return {"sites": sites}


def main() -> None:
    # Captura as variáveis de ambiente necessárias
    url_base = os.environ.get("CMK_MASTER_URL")
    site_master = os.environ.get("CMK_MASTER_SITE")
    usuario = os.environ.get("CMK_MASTER_USER")
    secret = os.environ.get("CMK_MASTER_SECRET")

    # Validação rigorosa para evitar falhas silenciosas
    faltando = [n for n, v in [
        ("CMK_MASTER_URL", url_base), 
        ("CMK_MASTER_SITE", site_master),
        ("CMK_MASTER_USER", usuario), 
        ("CMK_MASTER_SECRET", secret),
    ] if not v]
    
    if faltando:
        print(f"ERRO CRÍTICO: Variáveis de ambiente ausentes: {', '.join(faltando)}", file=sys.stderr)
        sys.exit(1)

    try:
        sites_master = buscar_sites_conectados(url_base, site_master, usuario, secret)
        print(f"Total de {len(sites_master)} site(s) extraído(s) do Master.")

        dados_inventario = converter_para_inventory_yaml(sites_master)

        # Salva o arquivo YAML mantendo a formatação legível
        with open(SAIDA, "w", encoding="utf-8") as f:
            yaml.dump(dados_inventario, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        print(f"Arquivo Fonte da Verdade ({SAIDA.name}) atualizado com {len(dados_inventario['sites'])} site(s).")

    except requests.RequestException as e:
        print(f"ERRO DE CONEXÃO COM A API DO CHECKMK: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERRO INESPERADO: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()