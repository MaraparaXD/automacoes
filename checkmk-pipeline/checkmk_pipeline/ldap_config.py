"""
checkmk_pipeline/ldap_config.py

Implementa a configuração do LDAP via API REST do CheckMK (Opção B).
Deve ser executada logo após o site passar na verificação de saúde.
"""

from __future__ import annotations

import logging
import os
import requests
from .core import SiteConfig

logger = logging.getLogger("checkmk_pipeline")

def configurar_ldap(site: SiteConfig, cmk_password: str, simulacao: bool = False) -> bool:
    if simulacao:
        logger.info("[%s] (simulação) Configuração de LDAP via API REST simulada.", site.sigla)
        return True

    # O AWX deve injetar essas credenciais de forma segura (não ficam no código)
    ldap_server = os.environ.get("LDAP_SERVER", "ad01.suaempresa.cloud")
    ldap_bind_dn = os.environ.get("LDAP_BIND_DN", "CN=svc_checkmk,OU=Services,DC=suaempresa,DC=cloud")
    ldap_bind_password = os.environ.get("LDAP_BIND_PASSWORD")
    ldap_base_dn = os.environ.get("LDAP_BASE_DN", "DC=suaempresa,DC=cloud")

    if not ldap_bind_password:
        logger.warning("[%s] Senha do LDAP (LDAP_BIND_PASSWORD) vazia. Pulando configuração.", site.sigla)
        return True # Não falha o deploy inteiro por isso, apenas avisa

    # Endpoint oficial da API do CheckMK para conexões LDAP
    url = f"http://localhost:{site.porta_web}/{site.sigla}/check_mk/api/1.0/domain-types/ldap_connection/collections/all"
    
    headers = {
        # A API REST do CheckMK aceita Bearer token com o cmkadmin
        "Authorization": f"Bearer cmkadmin {cmk_password}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    # Estrutura baseada no template original do ambiente corporativo
    payload = {
        "id": "ad_corporativo",
        "title": "Autenticação via Active Directory corporativo",
        "server": ldap_server,
        "port": 636,
        "use_ssl": True,
        "bind_dn": ldap_bind_dn,
        "bind_password": ldap_bind_password,
        "base_dn": ldap_base_dn,
        "role_mappings": [
            {
                "group_dn": f"CN=TI-CheckMK-Admin,{ldap_base_dn}",
                "role": "admin"
            },
            {
                "group_dn": f"CN=TI-CheckMK-Visualizacao,{ldap_base_dn}",
                "role": "guest"
            }
        ],
        "active": True
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        if resp.status_code in (200, 201):
            logger.info("[%s] Conexão LDAP 'ad_corporativo' configurada com sucesso.", site.sigla)
            return True
        elif resp.status_code == 409: # 409 Conflict: a conexão já existe
            logger.info("[%s] Conexão LDAP já existe no site.", site.sigla)
            return True
        else:
            logger.error("[%s] Falha na API ao configurar LDAP: HTTP %s - %s", site.sigla, resp.status_code, resp.text)
            return False
    except requests.RequestException as e:
        logger.error("[%s] Erro de rede ao tentar configurar LDAP via API: %s", site.sigla, e)
        return False