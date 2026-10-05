CONFIG_TEMPLATE = """# Konfigurasi QA Agent. Rahasia (API key, password) diisi di file .env, BUKAN di sini.
target:
  platform: web
  url: https://app-dev.kantor.local          # URL aplikasi yang dites
  allowed_domains: []                         # kosong = domain dari url
  login_endpoints: []                         # kosong = heuristik (login/auth/signin/token/session)
environment: dev                              # dev | production (bisa di-override: --env production)
accounts:
  - role: admin
    username_env: QA_ADMIN_USER
    password_env: QA_ADMIN_PASS
llm:
  provider: openai_compatible                 # openai_compatible (AI kantor) | anthropic (Claude)
  base_url: http://192.168.151.121/v1
  model: z-ai/glm-5.3-flash
  api_key_env: OFFICE_AI_KEY
  vision: true
  timeout_seconds: 60
limits:
  max_steps_per_tc: 25
  deep_max_tcs: 15
  explore_max_screens: 60
  explore_max_depth: 5
  explore_max_minutes: 45
guard:
  extra_risky_keywords: []
browser:
  headless: false                             # false = browser terlihat, kamu bisa menonton agent bekerja
  viewport: 1366x768
"""

ENV_TEMPLATE = """# Salin file ini menjadi .env lalu isi nilainya. File .env TIDAK BOLEH di-commit.
OFFICE_AI_KEY=
# ANTHROPIC_API_KEY=
QA_ADMIN_USER=
QA_ADMIN_PASS=
"""
