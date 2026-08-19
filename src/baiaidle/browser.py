import os
import platform
import shutil
from pathlib import Path

from pydoll.browser import Chrome
from pydoll.browser.options import ChromiumOptions

from .config import CHROMIUM_BINARY, CHROMIUM_USER_DATA_DIR


def find_browser() -> str:
    """
    Localiza automaticamente Chrome/Chromium.

    Ordem:
    1. CHROMIUM_BINARY do .env
    2. caminhos conhecidos do sistema
    3. PATH
    """

    # ============================================================
    # 1. Caminho definido no .env
    # ============================================================

    if CHROMIUM_BINARY:
        path = Path(CHROMIUM_BINARY).expanduser()

        if path.exists():
            return str(path)

        raise RuntimeError(
            f"CHROMIUM_BINARY foi configurado, "
            f"mas o arquivo não existe: {path}"
        )

    system = platform.system()

    # ============================================================
    # Linux
    # ============================================================

    if system == "Linux":

        candidates = [
            Path("/snap/bin/chromium"),
            Path("/usr/bin/chromium"),
            Path("/usr/bin/chromium-browser"),
            Path("/usr/bin/google-chrome"),
            Path("/usr/bin/google-chrome-stable"),
        ]

        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

    # ============================================================
    # Windows
    # ============================================================

    elif system == "Windows":

        candidates = [
            Path(
                r"C:\Program Files\Google\Chrome\Application\chrome.exe"
            ),
            Path(
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
            ),
        ]

        local_app_data = os.getenv("LOCALAPPDATA")

        if local_app_data:
            candidates.append(
                Path(local_app_data)
                / "Google"
                / "Chrome"
                / "Application"
                / "chrome.exe"
            )

        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

    # ============================================================
    # macOS
    # ============================================================

    elif system == "Darwin":

        candidates = [
            Path(
                "/Applications/Google Chrome.app/"
                "Contents/MacOS/Google Chrome"
            ),
            Path(
                "/Applications/Chromium.app/"
                "Contents/MacOS/Chromium"
            ),
        ]

        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

    # ============================================================
    # PATH
    # ============================================================

    commands = [
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
        "chrome",
    ]

    for command in commands:
        found = shutil.which(command)

        if found:
            return found

    raise RuntimeError(
        "Não foi possível encontrar Chrome/Chromium. "
        "Configure CHROMIUM_BINARY no arquivo .env."
    )


def create_browser() -> Chrome:
    """
    Cria uma instância do Chrome/Chromium usando Pydoll.

    A configuração é compatível com Windows e Linux.
    """

    binary = find_browser()

    print(f"Browser encontrado: {binary}")
    print(f"Perfil: {CHROMIUM_USER_DATA_DIR}")

    # ============================================================
    # Criar diretório do perfil
    # ============================================================

    CHROMIUM_USER_DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # ============================================================
    # Verificar permissões
    # ============================================================

    if not os.access(CHROMIUM_USER_DATA_DIR, os.W_OK):
        raise RuntimeError(
            "O diretório do perfil do Chromium não possui "
            f"permissão de escrita: {CHROMIUM_USER_DATA_DIR}"
        )

    # ============================================================
    # Opções do Chromium
    # ============================================================

    options = ChromiumOptions()

    options.binary_location = binary

    # Linux normalmente será executado sem interface gráfica.
    if platform.system() == "Linux":
        options.add_argument("--headless")

    # Necessário em muitos ambientes Linux/servidores.
    if platform.system() == "Linux":
        options.add_argument("--no-sandbox")

    options.add_argument("--disable-gpu")

    options.add_argument(
        "--disable-dev-shm-usage"
    )

    options.add_argument(
        f"--user-data-dir={CHROMIUM_USER_DATA_DIR}"
    )

    return Chrome(options=options)