# baiaidle-bot

Bot de automação do jogo web **Baiak Idle**, controlado via **Telegram**.
Roda em **Windows** e **Linux (VPS)** usando um Chromium real (Pydoll) em display virtual
(Xvfb no Linux) para evitar o desafio do Cloudflare Turnstile.

## Funcionalidades

- Login automático e recuperação de sessão (detecção de refresh/deslog).
- Venda periódica de loot com notificação no Telegram (gold, XP, stamina, gold/h, XP/h).
- Stash automático de itens valiosos (por tier mínimo e/ou atributos de raridade).
- Contabilização de moedas (crystal/platinum/gold) do Loot Analyser.
- Gerenciamento de stamina: treino online e casa (dummies), com reparo automático.
- Missões da Guilda e do Passe de Batalha (entrega e auto-seleção por nível).
- Codex (entrega global + foco por atributo/hunt).
- Árvore de talentos (distribuição automática por vocação).
- Invasão de Halloween (detecção/entrada/monitoramento).
- AutoBoss (fila de bosses, dificuldade configurável, agendamento à meia-noite BRT).
- Daily Reward (coleta + reagendamento).
- Watchdog anti-travamento e monitors em segundo plano (HP da party, Cloudflare, página).

## Requisitos

- Python >= 3.11
- Google Chrome / Chromium instalado (ou `CHROMIUM_BINARY` no `.env`)
- Linux: `xvfb` (`sudo apt install xvfb`) para o display virtual
- Conta no jogo Baiak Idle e um bot do Telegram (token via @BotFather)

## Instalação

```bash
git clone https://github.com/Gamml96/baiaidle-bot.git
cd baiaidle-bot
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux
source .venv/bin/activate

pip install -r requirements.txt
# para rodar os testes:
pip install -r requirements-dev.txt
```

## Configuração

Copie `.env.example` para `.env` e preencha:

```env
BAIAKIDLE_URL=https://baiakidle.com
BAIAKIDLE_LOGIN=seu_login
BAIAKIDLE_PASSWORD=sua_senha
TELEGRAM_BOT_TOKEN=token_do_bot
# Opcional: restringe o controle a um usuário
TELEGRAM_ALLOWED_USER_ID=123456789
# Opcional
CHROMIUM_BINARY=
CHROMIUM_USER_DATA_DIR=
```

Configurações de comportamento (stamina, tier de stash, atributos, watchdog, notificações,
Codex, hunt padrão) ficam em `config_user.json` e podem ser alteradas pelo Telegram (`/config`).

## Execução

```bash
python -m baiaidle.telegram_bot
```

Ou conforme o ponto de entrada configurado no seu ambiente. Depois, use `/start` no Telegram
para iniciar o bot e `/menu` para o painel principal.

## Testes

```bash
python -m pytest -q
```

## Estrutura

```
src/baiaidle/   # módulos do bot
tests/          # suíte de testes
config_user.json # configurações de comportamento
autoboss_preset.json # preset do AutoBoss
hunts_cache.json # cache de hunts
```

## Licença

Uso pessoal.