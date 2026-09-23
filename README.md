# Automações

Automações de infraestrutura e DevOps em Python: pipelines de CI/CD, deploy em
Docker, integração com ferramentas de orquestração e monitoramento.

Cada projeto fica em uma pasta própria, com README, dependências e instruções
de uso.

## Projetos

| Projeto | O que faz | Stack |
|---|---|---|
| [`checkmk-pipeline`](./checkmk-pipeline) | Pipeline de CI/CD que atualiza a versão de sites Checkmk em Docker Compose para centenas de clientes (multi-tenant), com backup, health check e rollback automático | Python, Docker Compose, GitLab CI, Ansible/AWX, API REST do Checkmk, LDAP |

## Destaque: checkmk-pipeline

Versão generalizada de uma automação que desenvolvi em ambiente profissional.
Nomes de empresa, domínios internos e identificadores de clientes foram
removidos ou trocados por exemplos genéricos. A lógica e a arquitetura são as
mesmas.

**Problema:** atualizar manualmente, um por um, centenas de sites Checkmk, cada
um isolado em seu próprio host, é lento e arriscado.

**Solução:**

- **Atualização segura por site:** backup, troca de versão via Docker Compose,
  health check e rollback se algo falhar (`core.py`).
- **Execução em escala:** um site piloto primeiro, depois lotes paralelos com
  tamanho e paralelismo configuráveis (`orchestrator.py`).
- **Duas formas de disparar:** job por site no GitLab CI (`parallel: matrix`)
  ou via AWX/Ansible, com um playbook que só chama o Python, sem duplicar
  lógica.
- **Inventário gerado automaticamente** a partir do AWX ou do Checkmk Master.
- **Modo simulação** (`SIMULACAO=1` / `--simulacao`) que mostra o que seria
  executado sem tocar em nenhum host.
- **Boas práticas de segurança:** senhas só em variáveis de CI protegidas e
  mascaradas, nunca no código; sudo restrito a comandos específicos.

```bash
cd checkmk-pipeline
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp inventory.example.yaml inventory.yaml

# teste sem executar nada de verdade
python3 -m checkmk_pipeline.orchestrator --versao 2.5.0p9 --simulacao
```

Detalhes completos em [`checkmk-pipeline/README.md`](./checkmk-pipeline/README.md).

## Autor

**Tiago Marapara Leão**, Sistemas de Informação (UFOPA)
[LinkedIn](https://www.linkedin.com/in/tiagomaraparaleao) · [GitHub](https://github.com/MaraparaXD)
