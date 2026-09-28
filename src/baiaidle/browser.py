import os
import platform
import shutil
from pathlib import Path

from pydoll.browser import Chrome
from pydoll.browser.options import ChromiumOptions

from .config import CHROMIUM_BINARY, CHROMIUM_USER_DATA_DIR


# ============================================================
# DISPLAY VIRTUAL (Xvfb)
# ============================================================
#
# No Linux, rodar o Chromium em modo --headless costuma disparar
# a verificação humana do Cloudflare Turnstile (o navegador
# headless é facilmente identificado por fingerprinting).
#
# Para evitar isso, rodamos o Chromium em modo "headed" normal,
# porém dentro de um display virtual (Xvfb), que não exige um
# monitor físico. Do ponto de vista do site, é indistinguível
# de um Chrome comum.
#
# Requer:
#   pip install pyvirtualdisplay
#   sudo apt install xvfb
#
# ============================================================

_virtual_display = None


def start_virtual_display():
    """
    Inicia um display virtual (Xvfb) no Linux, se necessário.

    Não faz nada no Windows/macOS ou se já existir um display
    real disponível (variável DISPLAY já definida).
    """

    global _virtual_display

    if platform.system() != "Linux":
        return

    if os.getenv("DISPLAY"):
        print(
            "DISPLAY já definido "
            f"({os.getenv('DISPLAY')}), "
            "não iniciando Xvfb."
        )
        return

    if _virtual_display is not None:
        return

    try:
        from pyvirtualdisplay import Display
    except ImportError:
        raise RuntimeError(
            "pyvirtualdisplay não está instalado. "
            "Execute: pip install pyvirtualdisplay "
            "e sudo apt install xvfb"
        )

    _virtual_display = Display(
        visible=0,
        size=(1280, 720),
    )

    _virtual_display.start()

    print(
        "Display virtual (Xvfb) iniciado: "
        f"{os.environ.get('DISPLAY')}"
    )


def stop_virtual_display():
    """
    Para o display virtual (Xvfb), se estiver rodando.
    """

    global _virtual_display

    if _virtual_display is None:
        return

    try:
        _virtual_display.stop()
    except Exception:
        pass

    _virtual_display = None

    print("Display virtual (Xvfb) encerrado.")


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
            Path("/usr/bin/google-chrome-stable"),
            Path("/usr/bin/google-chrome"),
            Path("/usr/bin/chromium-browser"),
            Path("/usr/bin/chromium"),
            Path("/snap/bin/chromium"),
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

    # ============================================================
    # Linux (Sandbox)
    # ============================================================
    if platform.system() == "Linux":
        options.add_argument("--no-sandbox")

    # ============================================================
    # Configurações Universais (Windows e Linux)
    # ============================================================
    # Garante que a página sempre tenha espaço para renderizar os elementos
    options.add_argument("--window-size=1280,720")
    options.add_argument("--start-maximized")

    # ============================================================
    # Anti-fingerprinting e Perfil
    # ============================================================
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-dev-shm-usage")
    
    # NOVAS FLAGS: Evitam que o Chrome bloqueie o carregamento do jogo
    options.add_argument("--disable-features=IsolateOrigins,site-per-process")
    options.add_argument("--disable-web-security")

    profile_path = str(CHROMIUM_USER_DATA_DIR).replace('\\', '/')
    options.add_argument(f"--user-data-dir={profile_path}")

    return Chrome(options=options)