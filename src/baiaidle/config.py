import os
from pathlib import Path

from dotenv import load_dotenv


# ============================================================
# LOCALIZAÇÃO DO PROJETO
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(ENV_FILE)


# ============================================================
# BAIak IDLE
# ============================================================

BAIAKIDLE_URL = os.getenv(
    "BAIAKIDLE_URL",
    "https://baiakidle.com",
)

BAIAKIDLE_LOGIN = os.getenv(
    "BAIAKIDLE_LOGIN",
    "",
)

BAIAKIDLE_PASSWORD = os.getenv(
    "BAIAKIDLE_PASSWORD",
    "",
)


# ============================================================
# CHROMIUM
# ============================================================

CHROMIUM_BINARY = os.getenv(
    "CHROMIUM_BINARY",
    "",
)

_chromium_user_data_dir = os.getenv(
    "CHROMIUM_USER_DATA_DIR",
    "",
)


if _chromium_user_data_dir:

    CHROMIUM_USER_DATA_DIR = Path(
        _chromium_user_data_dir
    ).expanduser()

else:

    if os.name == "nt":

        CHROMIUM_USER_DATA_DIR = (
            Path(os.environ["LOCALAPPDATA"])
            / "baiaidle-bot"
            / "chromium-profile"
        )

    else:

        CHROMIUM_USER_DATA_DIR = (
            Path.home()
            / ".config"
            / "baiaidle-bot-chromium"
        )


# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    "",
)

# Opcional.
#
# Se configurado, somente este usuário poderá controlar
# o bot.
#
# Exemplo:
#
# TELEGRAM_ALLOWED_USER_ID=123456789

_telegram_allowed_user_id = os.getenv(
    "TELEGRAM_ALLOWED_USER_ID",
    "",
).strip()


if _telegram_allowed_user_id:

    try:

        TELEGRAM_ALLOWED_USER_ID = int(
            _telegram_allowed_user_id
        )

    except ValueError:

        raise RuntimeError(
            "TELEGRAM_ALLOWED_USER_ID precisa ser "
            "um número inteiro."
        )

else:

    TELEGRAM_ALLOWED_USER_ID = None


# ============================================================
# TWITCH (recompensa de Streaming Coin)
# ============================================================
# Token OAuth da conta Twitch vinculada ao jogo (escopo chat:read).
# Gere em: https://twitchtokengenerator.com
TWITCH_OAUTH_TOKEN = os.getenv("TWITCH_OAUTH_TOKEN", "").strip()

# Canal da live (opcional). Se vazio, o bot escolhe automaticamente
# a partir da aba "Ao vivo" do jogo.
TWITCH_CHANNEL = os.getenv("TWITCH_CHANNEL", "").strip()


# ============================================================
# VALIDAÇÃO
# ============================================================

def validate_config():

    if not BAIAKIDLE_URL:

        raise RuntimeError(
            "BAIAKIDLE_URL não configurado."
        )

    if not BAIAKIDLE_LOGIN:

        raise RuntimeError(
            "BAIAKIDLE_LOGIN não configurado no .env."
        )

    if not BAIAKIDLE_PASSWORD:

        raise RuntimeError(
            "BAIAKIDLE_PASSWORD não configurado no .env."
        )

    if not TELEGRAM_BOT_TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN não configurado no .env."
        )