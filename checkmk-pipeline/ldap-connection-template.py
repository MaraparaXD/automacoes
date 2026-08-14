# Template de conexão LDAP — CheckMK
#
# ⚠️ NÃO USAR EM PRODUÇÃO ainda — os valores abaixo são placeholders.
# Preencher depois de confirmar:
#   1. Endereço e porta do servidor LDAP
#   2. Usuário de bind (conta de serviço, só leitura)
#   3. Base DN
#   4. Grupos de AD para mapeamento de papéis (admin vs visualização)
#   5. Se o host de produção tem rota de rede até o LDAP
#
# Depois de preenchido, este arquivo pode ser injetado em cada site
# na criação (via volume/COPY) ou convertido em chamada de API REST
# do CheckMK (mais robusto — ver nota no final).

LDAP_CONNECTIONS = {
    'ad_corporativo': {
        'id': 'ad_corporativo',
        'description': 'Autenticação via Active Directory corporativo',

        # --- CONFIRMAR ANTES DE USAR EM PRODUÇÃO ---
        'server': 'SUBSTITUIR_ENDERECO_LDAP',       # ex: ad01.suaempresa.cloud
        'port': 636,                                  # 389 (LDAP) ou 636 (LDAPS) -- confirmar qual usar
        'use_ssl': True,                               # True se porta 636

        'bind_dn': 'SUBSTITUIR_USUARIO_DE_BIND',     # conta de serviço, só leitura
        # A senha do bind NUNCA deve ficar hardcoded aqui.
        # Usar variável protegida do GitLab CI/CD (mesma lógica do CMK_PASSWORD)
        # e injetar em tempo de execução.
        'bind_password': '${LDAP_BIND_PASSWORD}',

        'base_dn': 'SUBSTITUIR_BASE_DN',             # ex: DC=suaempresa,DC=cloud

        # --- MAPEAMENTO DE PAPÉIS ---
        # Confirmar com o time responsável se já existem grupos separados no AD.
        # Se não existirem, sugerir criar antes de automatizar isso.
        'role_mappings': {
            'CN=TI-CheckMK-Admin,SUBSTITUIR_BASE_DN': 'admin',
            'CN=TI-CheckMK-Visualizacao,SUBSTITUIR_BASE_DN': 'guest',
        },

        'active': True,
    },
}

# ---------------------------------------------------------------------
# NOTA SOBRE IMPLEMENTAÇÃO NO PIPELINE
#
# Opção A (arquivo): gerar este .mk já preenchido (uma vez, mesma config
# para todos os sites) e copiar para dentro de cada site em
# etc/check_mk/multisite.d/wato/ldap_connections.mk no momento da criação.
#
# Opção B (API REST): chamar o endpoint de configuração do CheckMK
# (/check_mk/api/1.0/domain-types/ldap_connection/collections/all)
# depois que o site estiver de pé, passando os mesmos dados via JSON.
# Mais robusto para automação contínua, mas exige esperar o site
# responder antes de configurar.
#
# Recomendo Opção B para o pipeline final, já que ela se encaixa bem
# na etapa "verificação de saúde" que já existe no core.py — dá pra
# configurar o LDAP logo depois do health check passar.
# ---------------------------------------------------------------------
