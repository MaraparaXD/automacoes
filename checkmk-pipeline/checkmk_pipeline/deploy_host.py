"""
checkmk_pipeline/deploy_host.py

Ponto de entrada MINIMALISTA para uso com AWX/Ansible: recebe só o IP
(ou hostname) do destino; todo o resto vem de variáveis de ambiente.
Usa `docker compose` (via core.py), NÃO o SDK Python do Docker.

Variáveis de ambiente esperadas:
  SITE_SIGLA          (obrigatório)  ex: "abc"
  (Portas web=80 e agente=6556 são FIXAS no template docker-compose.yml,
  não precisam mais ser informadas via variável de ambiente.)
  NOVA_VERSAO         (obrigatório)  tag da imagem, ex: "2.5.0-latest"
  CMK_PASSWORD        (obrigatório)  senha do cmkadmin
  DIRETORIO_COMPOSE   (opcional)     pasta do site (default:
                                      /opt/checkmk-container/<SITE_SIGLA>)
  CLIENTE_NOME        (opcional)     nome do cliente, só para log/relatório
  PACOTE_AGENTE       (opcional)     nome/caminho do pacote do agente
                                      (default: "check-mk-agent")
  SIMULACAO           (opcional)     "1" para rodar em modo simulação

Uso:
    export SITE_SIGLA=abc
    export NOVA_VERSAO=2.5.0-latest
    export CMK_PASSWORD=senha123
    export DIRETORIO_COMPOSE=/opt/checkmk-pipeline
    python3 -m checkmk_pipeline.deploy_host --ip 192.168.1.50
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from .core import AtualizadorDeSite, SiteConfig
from .host_bootstrap import preparar_host
from .orchestrator import configurar_log, salvar_relatorio


def ler_env_obrigatoria(nome: str) -> str:
    valor = os.environ.get(nome)
    if not valor:
        raise SystemExit(f"Variável de ambiente obrigatória não definida: {nome}")
    return valor


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy de UM site CheckMK via docker compose, IP + variáveis de ambiente")
    parser.add_argument("--ip", required=True, help="IP ou hostname do host de destino (informativo/log)")
    parser.add_argument("--pular-bootstrap-host", action="store_true",
                         help="Pula a etapa de DNS + instalação do agente (útil se o host já foi preparado)")
    args = parser.parse_args()

    configurar_log()
    logger = logging.getLogger("checkmk_pipeline")

    simulacao = os.environ.get("SIMULACAO", "") == "1"

    sigla = ler_env_obrigatoria("SITE_SIGLA")
    nova_versao = ler_env_obrigatoria("NOVA_VERSAO")
    cmk_password = ler_env_obrigatoria("CMK_PASSWORD")
    cliente_nome = os.environ.get("CLIENTE_NOME", "desconhecido")
    pacote_agente = os.environ.get("PACOTE_AGENTE", "check-mk-agent")
    diretorio_compose = os.environ.get("DIRETORIO_COMPOSE", f"/opt/checkmk-container/{sigla}")

    logger.info("=== Deploy do site '%s' (cliente: %s) no host %s ===", sigla, cliente_nome, args.ip)

    if not args.pular_bootstrap_host:
        logger.info("--- Preparação do host (DNS + agente) ---")
        if not preparar_host(pacote_agente, simulacao=simulacao):
            logger.critical("Preparação do host falhou. Abortando antes de tocar no site.")
            sys.exit(1)
    else:
        logger.info("Preparação do host pulada (--pular-bootstrap-host).")

    logger.info("--- Deploy/atualização do site (docker compose) ---")
    site = SiteConfig(
        sigla=sigla,
        cliente=cliente_nome,
        diretorio_compose=diretorio_compose,
        # Primeira execução não tem uma tag "anterior" real para reverter;
        # usamos a mesma versão informada agora como fallback de rollback.
        imagem_tag_atual=nova_versao,
    )

    atualizador = AtualizadorDeSite(nova_versao=nova_versao, cmk_password=cmk_password, simulacao=simulacao)
    resultado = atualizador.atualizar(site)

    salvar_relatorio([resultado], caminho=f"relatorio_{sigla}.csv")

    if resultado.sucesso:
        logger.info("=== Deploy de '%s' concluído com sucesso ===", sigla)
        sys.exit(0)
    else:
        logger.critical("=== Deploy de '%s' FALHOU: %s ===", sigla, resultado.mensagem)
        sys.exit(1)


if __name__ == "__main__":
    main()
