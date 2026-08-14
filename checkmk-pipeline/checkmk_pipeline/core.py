"""
checkmk_pipeline/core.py

Núcleo do pipeline de atualização em massa dos sites CheckMK (Docker Compose)
do ambiente corporativo.

TUDO é feito via `docker compose` (subprocess), NÃO via SDK Python do Docker.

Estrutura de diretórios padrão (uma pasta por site, isolada):
    /opt/checkmk-container/<sigla>/
        docker-compose.yml   <- copiado do template canônico do repositório
        dados/               <- bind mount, vira /omd/sites dentro do container
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests
import yaml

logger = logging.getLogger("checkmk_pipeline")

DIRETORIO_RAIZ_PADRAO = "/opt/checkmk-container"
TEMPLATE_COMPOSE = Path(__file__).resolve().parent.parent / "templates" / "docker-compose.yml"


@dataclass
class SiteConfig:
    sigla: str
    cliente: str
    diretorio_compose: str
    imagem_tag_atual: str
    porta_web: int = 80
    porta_agente: int = 6556

    @classmethod
    def a_partir_de_dicionario(cls, dados: dict) -> "SiteConfig":
        sigla = dados["sigla"]
        return cls(
            sigla=sigla,
            cliente=dados.get("cliente", "desconhecido"),
            diretorio_compose=dados.get("diretorio_compose", f"{DIRETORIO_RAIZ_PADRAO}/{sigla}"),
            porta_web=dados.get("porta_web", 80),
            porta_agente=dados.get("porta_agent", 6556),
            imagem_tag_atual=dados["imagem_tag_atual"],
        )


def provisionar_diretorio_site(site: SiteConfig, simulacao: bool = False) -> None:
    destino = Path(site.diretorio_compose)
    pasta_dados = destino / "dados"

    logger.info("[%s] Provisionando diretório %s", site.sigla, destino)

    if simulacao:
        logger.info("[%s] (simulação) mkdir + cópia do template simulados", site.sigla)
        return

    destino.mkdir(parents=True, exist_ok=True)
    pasta_dados.mkdir(parents=True, exist_ok=True)

    if not TEMPLATE_COMPOSE.exists():
        raise FileNotFoundError(
            f"Template canônico não encontrado em {TEMPLATE_COMPOSE}. "
            "Confirme se o repositório do pipeline está completo."
        )

    shutil.copyfile(TEMPLATE_COMPOSE, destino / "docker-compose.yml")


@dataclass
class ResultadoAtualizacao:
    sigla: str
    sucesso: bool
    mensagem: str
    duracao_segundos: float
    reversao_executada: bool = False


def carregar_inventario(caminho: str) -> list[SiteConfig]:
    with open(caminho, "r", encoding="utf-8") as f:
        dados = yaml.safe_load(f)
    return [SiteConfig.a_partir_de_dicionario(s) for s in dados["sites"]]


class AtualizadorDeSite:
    def __init__(self, nova_versao: str, cmk_password: str, simulacao: bool = False, tempo_limite_boot: int = 90):
        self.nova_versao = nova_versao
        self.cmk_password = cmk_password
        self.simulacao = simulacao
        self.tempo_limite_boot = tempo_limite_boot

    def _env_compose(self, site: SiteConfig, tag_imagem: str) -> dict:
        import os
        env = os.environ.copy()
        env.update({
            "SITE_SIGLA": site.sigla,
            "CMK_PASSWORD": self.cmk_password,
            "IMAGEM_TAG": tag_imagem,
        })
        return env

    def _compose(self, site: SiteConfig, args: list[str], tag_imagem: str, permitir_falha: bool = False) -> Optional[subprocess.CompletedProcess]:
        comando = ["docker", "compose", "-p", site.sigla] + args
        logger.info("[%s] $ %s", site.sigla, " ".join(comando))

        if self.simulacao:
            return None

        resultado = subprocess.run(
            comando,
            cwd=site.diretorio_compose,
            env=self._env_compose(site, tag_imagem),
            capture_output=True,
            text=True,
        )
        if resultado.returncode != 0 and not permitir_falha:
            logger.error("[%s] Comando falhou: %s", site.sigla, resultado.stderr.strip())
            raise RuntimeError(f"docker compose {' '.join(args)} falhou: {resultado.stderr.strip()}")
        return resultado

    def fazer_backup(self, site: SiteConfig) -> Path:
        destino = Path("backups") / site.sigla
        destino.mkdir(parents=True, exist_ok=True)
        nome_arquivo = f"{site.sigla}_{int(time.time())}.tar"
        caminho_local = destino / nome_arquivo

        logger.info("[%s] Iniciando backup do site...", site.sigla)

        if self.simulacao:
            logger.info("[%s] (simulação) backup simulado em %s", site.sigla, caminho_local)
            return caminho_local

        self._compose(site, ["exec", "-T", "checkmk", "omd", "backup", site.sigla, f"/tmp/{nome_arquivo}"], site.imagem_tag_atual)
        self._compose(site, ["cp", f"checkmk:/tmp/{nome_arquivo}", str(caminho_local)], site.imagem_tag_atual)

        logger.info("[%s] Backup salvo em %s", site.sigla, caminho_local)
        return caminho_local

    def _subir_com_tag(self, site: SiteConfig, tag_imagem: str) -> None:
        logger.info("[%s] Derrubando serviço atual (docker compose down)...", site.sigla)
        self._compose(site, ["down", "--remove-orphans"], tag_imagem, permitir_falha=True)

        logger.info("[%s] Subindo com imagem tag=%s (docker compose up -d)...", site.sigla, tag_imagem)
        self._compose(site, ["up", "-d"], tag_imagem)

    def _aguardar_inicializacao(self, site: SiteConfig, tag_imagem: str) -> bool:
        if self.simulacao:
            return True

        marcadores_ok = ["Finished update.", "Created new site", "STARTING SITE"]
        inicio = time.time()

        while time.time() - inicio < self.tempo_limite_boot:
            resultado = self._compose(site, ["logs", "--tail", "200"], tag_imagem, permitir_falha=True)
            logs = resultado.stdout if resultado else ""
            if any(m in logs for m in marcadores_ok):
                return True
            time.sleep(3)

        return False

    def verificar_saude(self, site: SiteConfig) -> bool:
        if self.simulacao:
            return True

        url = f"http://localhost:{site.porta_web}/{site.sigla}/check_mk/login.py"
        try:
            resp = requests.get(url, timeout=10)
            return resp.status_code == 200
        except requests.RequestException as e:
            logger.warning("[%s] Verificação de saúde falhou: %s", site.sigla, e)
            return False

    def reverter(self, site: SiteConfig, caminho_backup: Path | None = None) -> None:
        """Recria o serviço com a tag anterior e executa restauração do .tar se existir."""
        logger.warning("[%s] Executando REVERSÃO para tag=%s", site.sigla, site.imagem_tag_atual)
        self._subir_com_tag(site, site.imagem_tag_atual)
        
        if caminho_backup and caminho_backup.exists() and not self.simulacao:
            logger.warning("[%s] Restaurando dados a partir do backup físico: %s", site.sigla, caminho_backup)
            
            # Para o site (libera processos)
            self._compose(site, ["exec", "-T", "checkmk", "omd", "stop", site.sigla], site.imagem_tag_atual, permitir_falha=True)
            
            # Copia o backup de volta para o container
            self._compose(site, ["cp", str(caminho_backup), "checkmk:/tmp/restore.tar"], site.imagem_tag_atual)
            
            # Deleta a estrutura corrompida e restaura os dados limpos
            self._compose(site, ["exec", "-T", "checkmk", "omd", "rm", "--kill", "--force", site.sigla], site.imagem_tag_atual, permitir_falha=True)
            self._compose(site, ["exec", "-T", "checkmk", "omd", "restore", "/tmp/restore.tar"], site.imagem_tag_atual)
            
            # Reinicia
            self._compose(site, ["exec", "-T", "checkmk", "omd", "start", site.sigla], site.imagem_tag_atual)
            
        self._aguardar_inicializacao(site, site.imagem_tag_atual)

    def atualizar(self, site: SiteConfig) -> ResultadoAtualizacao:
        inicio = time.time()
        caminho_backup = None

        try:
            provisionar_diretorio_site(site, simulacao=self.simulacao)
            caminho_backup = self.fazer_backup(site)
            self._subir_com_tag(site, self.nova_versao)

            if not self._aguardar_inicializacao(site, self.nova_versao):
                raise TimeoutError("Serviço não sinalizou conclusão da inicialização/atualização a tempo")

            if not self.verificar_saude(site):
                raise RuntimeError("Verificação de saúde falhou após atualização")

            duracao = time.time() - inicio
            logger.info("[%s] Atualização concluída com sucesso (%.1fs)", site.sigla, duracao)
            return ResultadoAtualizacao(site.sigla, True, "OK", duracao)

        except Exception as e:
            logger.error("[%s] Falha na atualização: %s", site.sigla, e)
            reversao_ok = False
            try:
                # Passa o backup salvo para a função de reversão restaurar os dados
                self.reverter(site, caminho_backup)
                reversao_ok = True
            except Exception as erro_reversao:
                logger.critical("[%s] REVERSÃO TAMBÉM FALHOU: %s", site.sigla, erro_reversao)

            duracao = time.time() - inicio
            return ResultadoAtualizacao(site.sigla, False, str(e), duracao, reversao_executada=reversao_ok)