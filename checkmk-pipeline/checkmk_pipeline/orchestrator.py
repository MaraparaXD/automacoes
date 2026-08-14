"""
checkmk_pipeline/orchestrator.py

Orquestra a atualização de MUITOS sites (400+), com:
  - execução em lotes controlados
  - modo "piloto" (testa em poucos sites antes de liberar o resto)
  - paralelismo limitado por lote
  - log estruturado de resultado por site

Uso:
    python -m checkmk_pipeline.orchestrator \\
        --inventario inventory.yaml \\
        --versao 2.5.0p9 \\
        --piloto abc,xyz \\
        --tamanho-lote 10 \\
        --paralelismo 4 \\
        --simulacao
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from .core import AtualizadorDeSite, SiteConfig, ResultadoAtualizacao, carregar_inventario

logger = logging.getLogger("checkmk_pipeline")


def configurar_log() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("pipeline.log", encoding="utf-8"),
        ],
    )


def dividir_em_lotes(sites: list[SiteConfig], tamanho: int) -> list[list[SiteConfig]]:
    return [sites[i : i + tamanho] for i in range(0, len(sites), tamanho)]


def executar_lote(
    lote: list[SiteConfig], atualizador: AtualizadorDeSite, paralelismo: int
) -> list[ResultadoAtualizacao]:
    """Atualiza os sites de um lote em paralelo (até `paralelismo` simultâneos)."""
    resultados: list[ResultadoAtualizacao] = []
    with ThreadPoolExecutor(max_workers=paralelismo) as executor:
        futuros = {executor.submit(atualizador.atualizar, site): site for site in lote}
        for futuro in as_completed(futuros):
            site = futuros[futuro]
            try:
                resultado = futuro.result()
            except Exception as e:  # segurança extra: nunca deixar a thread matar o lote
                logger.critical("[%s] Erro inesperado não tratado: %s", site.sigla, e)
                resultado = ResultadoAtualizacao(site.sigla, False, f"erro inesperado: {e}", 0.0)
            resultados.append(resultado)
    return resultados


def salvar_relatorio(resultados: list[ResultadoAtualizacao], caminho: str = "relatorio_atualizacao.csv") -> None:
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["sigla", "sucesso", "mensagem", "duracao_segundos", "reversao_executada"])
        for r in resultados:
            writer.writerow([r.sigla, r.sucesso, r.mensagem, f"{r.duracao_segundos:.1f}", r.reversao_executada])
    logger.info("Relatório salvo em %s", caminho)


def rodar_pipeline(
    caminho_inventario: str,
    nova_versao: str,
    cmk_password: str,
    siglas_piloto: list[str],
    tamanho_lote: int,
    paralelismo: int,
    simulacao: bool,
) -> list[ResultadoAtualizacao]:
    sites = carregar_inventario(caminho_inventario)
    atualizador = AtualizadorDeSite(nova_versao=nova_versao, cmk_password=cmk_password, simulacao=simulacao)

    todos_resultados: list[ResultadoAtualizacao] = []

    # ---- Fase Piloto ----
    if siglas_piloto:
        sites_piloto = [s for s in sites if s.sigla in siglas_piloto]
        restantes = [s for s in sites if s.sigla not in siglas_piloto]

        logger.info("=== FASE PILOTO: %s ===", ", ".join(siglas_piloto))
        resultados_piloto = executar_lote(sites_piloto, atualizador, paralelismo)
        todos_resultados.extend(resultados_piloto)

        falhas_piloto = [r for r in resultados_piloto if not r.sucesso]
        if falhas_piloto:
            logger.critical(
                "Piloto falhou para %s site(s): %s. Pipeline interrompido — "
                "resto do inventário NÃO foi atualizado.",
                len(falhas_piloto),
                ", ".join(f.sigla for f in falhas_piloto),
            )
            salvar_relatorio(todos_resultados)
            return todos_resultados

        logger.info("Piloto OK. Prosseguindo para o restante do inventário (%d sites).", len(restantes))
        sites = restantes

    # ---- Fase em lotes ----
    lotes = dividir_em_lotes(sites, tamanho_lote)
    logger.info("Atualizando %d sites em %d lote(s) de até %d.", len(sites), len(lotes), tamanho_lote)

    for i, lote in enumerate(lotes, start=1):
        logger.info("--- Lote %d/%d (%d sites) ---", i, len(lotes), len(lote))
        resultados = executar_lote(lote, atualizador, paralelismo)
        todos_resultados.extend(resultados)

        falhas = [r for r in resultados if not r.sucesso]
        if falhas:
            logger.warning(
                "Lote %d teve %d falha(s): %s",
                i,
                len(falhas),
                ", ".join(f.sigla for f in falhas),
            )
            # ASSUNÇÃO: por padrão o pipeline CONTINUA para o próximo lote
            # mesmo com falhas isoladas (a reversão já foi feita por site).
            # Validar com o time responsável se um % de falha deve interromper tudo
            # (circuit breaker).

    salvar_relatorio(todos_resultados)
    return todos_resultados


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline de atualização dos sites CheckMK")
    parser.add_argument("--inventario", default="inventory.yaml", help="Caminho do inventory.yaml")
    parser.add_argument("--versao", required=True, help="Tag da nova versão do CheckMK, ex: 2.5.0p9")
    parser.add_argument("--piloto", default="", help="Siglas separadas por vírgula para rodar primeiro")
    parser.add_argument("--tamanho-lote", type=int, default=10, help="Sites por lote")
    parser.add_argument("--paralelismo", type=int, default=4, help="Atualizações simultâneas por lote")
    parser.add_argument("--simulacao", action="store_true", help="Simula sem executar comandos reais")
    args = parser.parse_args()

    configurar_log()

    cmk_password = os.environ.get("CMK_PASSWORD", "")
    if not cmk_password and not args.simulacao:
        raise SystemExit("Variável de ambiente CMK_PASSWORD não definida.")

    siglas_piloto = [s.strip() for s in args.piloto.split(",") if s.strip()]

    resultados = rodar_pipeline(
        caminho_inventario=args.inventario,
        nova_versao=args.versao,
        cmk_password=cmk_password,
        siglas_piloto=siglas_piloto,
        tamanho_lote=args.tamanho_lote,
        paralelismo=args.paralelismo,
        simulacao=args.simulacao,
    )

    sucessos = sum(1 for r in resultados if r.sucesso)
    falhas = len(resultados) - sucessos
    logger.info("=== FIM DO PIPELINE: %d sucesso(s), %d falha(s) ===", sucessos, falhas)

    sys.exit(1 if falhas else 0)


if __name__ == "__main__":
    main()
