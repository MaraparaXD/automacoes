"""
checkmk_pipeline/host_bootstrap.py

Prepara o HOST (não o container) antes do deploy do site:
  - Etapa 3: Valida DNS (LDAP corporativo)
  - Etapa 6: Instala/valida o agente Check_MK no host

Suporte expandido para múltiplas distribuições:
  - Oracle Linux / RHEL / CentOS (yum / dnf)
  - Ubuntu / Debian (apt-get)
  - SUSE (zypper)
"""

from __future__ import annotations

import logging
import shutil
import socket
import subprocess
import time

logger = logging.getLogger("checkmk_pipeline")

LDAP_HOST = "ad01.suaempresa.cloud"


def verificar_dns(host: str = LDAP_HOST, simulacao: bool = False) -> bool:
    if simulacao:
        logger.info("(simulação) DNS de %s considerado OK", host)
        return True

    try:
        ip = socket.gethostbyname(host)
        logger.info("DNS OK: %s resolve para %s", host, ip)
        return True
    except socket.gaierror as e:
        logger.error(
            "DNS não resolve %s (%s). Verifique se a VPN está ativa "
            "e se o DNS corporativo está configurado neste host.",
            host, e,
        )
        return False


def _rodar(comando: list[str], simulacao: bool, permitir_falha: bool = False) -> subprocess.CompletedProcess | None:
    logger.info("Executando: %s", " ".join(comando))
    if simulacao:
        logger.info("(simulação) comando não executado de verdade")
        return None

    resultado = subprocess.run(comando, capture_output=True, text=True)
    if resultado.returncode != 0 and not permitir_falha:
        logger.error("Comando falhou (%s): %s", resultado.returncode, resultado.stderr.strip())
        raise RuntimeError(f"Falha ao executar {' '.join(comando)}: {resultado.stderr.strip()}")
    return resultado


def _detectar_gerenciador() -> str:
    """Detecta dinamicamente qual gerenciador de pacotes está disponível no OS."""
    for cmd in ["apt-get", "zypper", "dnf", "yum"]:
        if shutil.which(cmd):
            return cmd
    raise RuntimeError("Nenhum gerenciador de pacotes suportado foi encontrado (apt, zypper, dnf, yum).")


def _pacote_instalado(pacote: str, gerenciador: str, simulacao: bool) -> bool:
    """Valida a instalação verificando o banco de dados do gerenciador correspondente."""
    if simulacao:
        return False

    if gerenciador == "apt-get":
        res = _rodar(["dpkg", "-s", pacote], simulacao, permitir_falha=True)
        return res is not None and "Status: install ok installed" in res.stdout
    else:
        # rpm funciona para zypper, dnf e yum
        res = _rodar(["rpm", "-q", pacote], simulacao, permitir_falha=True)
        return res is not None and res.returncode == 0


def _instalar_pacote(pacote_caminho_ou_nome: str, gerenciador: str, simulacao: bool) -> None:
    """Executa a instalação com a sintaxe correta do gerenciador."""
    if gerenciador == "apt-get":
        _rodar(["apt-get", "install", "-y", pacote_caminho_ou_nome], simulacao)
    elif gerenciador == "zypper":
        _rodar(["zypper", "--non-interactive", "install", pacote_caminho_ou_nome], simulacao)
    else:
        _rodar([gerenciador, "install", "-y", pacote_caminho_ou_nome], simulacao)


def instalar_agente(pacote_agente: str, simulacao: bool = False) -> bool:
    """Instala o agente Check_MK de forma agnóstica ao sistema operacional."""
    try:
        gerenciador = _detectar_gerenciador()
        logger.info("Gerenciador de pacotes detectado: %s", gerenciador)

        # Na base apt o nome do pacote interno não leva o final '.deb' da mesma forma
        nome_pacote_base = "check-mk-agent" 
        ja_instalado = _pacote_instalado(nome_pacote_base, gerenciador, simulacao)

        if ja_instalado and not simulacao:
            logger.info("Agente Check_MK já instalado, pulando instalação.")
        else:
            _instalar_pacote(pacote_agente, gerenciador, simulacao)

        status_socket = _rodar(["systemctl", "is-active", "check_mk.socket"], simulacao, permitir_falha=True)
        if status_socket and status_socket.stdout.strip() == "active":
            logger.info("Desabilitando check_mk.socket (conflita com xinetd)...")
            _rodar(["systemctl", "disable", "--now", "check_mk.socket"], simulacao)

        xinetd_instalado = _pacote_instalado("xinetd", gerenciador, simulacao)
        if not xinetd_instalado and not simulacao:
            _instalar_pacote("xinetd", gerenciador, simulacao)

        _rodar(["systemctl", "enable", "--now", "xinetd"], simulacao)

        if not simulacao:
            time.sleep(5)

        checagem_porta = _rodar(["ss", "-ntlp"], simulacao, permitir_falha=True)
        if not simulacao and checagem_porta and "6556" not in checagem_porta.stdout:
            logger.warning("Porta 6556 do agente não aparece escutando ainda — verificar manualmente.")

        logger.info("Agente Check_MK pronto no host.")
        return True

    except RuntimeError as e:
        logger.error("Falha ao instalar/configurar o agente: %s", e)
        return False


def preparar_host(pacote_agente: str, simulacao: bool = False) -> bool:
    """Executa toda a preparação do host em sequência."""
    if not verificar_dns(simulacao=simulacao):
        return False
    if not instalar_agente(pacote_agente, simulacao=simulacao):
        return False
    return True