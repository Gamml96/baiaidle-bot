import os
from pathlib import Path

from dotenv import load_dotenv


# ============================================================
# Localização do projeto
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(ENV_FILE)


# ============================================================
# Baiak Idle
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
# Chromium
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
    # Perfil padrão do bot.
    #
    # Windows:
    # C:\Users\<usuario>\AppData\Local\baiaidle-bot\chromium-profile
    #
    # Linux:
    # /home/<usuario>/.config/baiaidle-bot-chromium

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
# Validação
# ============================================================

def validate_config():
    """
    Verifica se as configurações obrigatórias estão presentes.
    """

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