import asyncio
import random
from dataclasses import dataclass

from baiaidle.actions import (
    get_sale_value,
    get_sell_button_state,
    open_sale_confirmation,
    confirm_sale,
    wait_for_cloudflare,
    wait_for_sell_cooldown,
)


# ================================================================
# CONFIGURAÇÃO
# ================================================================

BASE_INTERVAL = 120

MAIN_JITTER_MIN = 5
MAIN_JITTER_MAX = 10

RETRY_INTERVAL = 15

RETRY_JITTER_MIN = 5
RETRY_JITTER_MAX = 10


# ================================================================
# ESTATÍSTICAS
# ================================================================

@dataclass
class HuntStats:
    started_at: float
    total_gold: int = 0
    sales: int = 0

    def add_sale(self, value: int):
        self.total_gold += value
        self.sales += 1

    def elapsed(self) -> float:
        return (
            asyncio.get_running_loop().time()
            - self.started_at
        )

    def gold_per_hour(self) -> float:
        elapsed = self.elapsed()

        if elapsed <= 0:
            return 0

        return (
            self.total_gold
            / elapsed
            * 3600
        )


# ================================================================
# UTILITÁRIOS
# ================================================================

def format_gold(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def format_duration(seconds: float) -> str:
    total_seconds = int(seconds)

    hours = total_seconds // 3600

    minutes = (
        total_seconds % 3600
    ) // 60

    secs = total_seconds % 60

    return (
        f"{hours:02d}:"
        f"{minutes:02d}:"
        f"{secs:02d}"
    )


def random_main_delay() -> float:
    jitter = random.uniform(
        MAIN_JITTER_MIN,
        MAIN_JITTER_MAX,
    )

    return BASE_INTERVAL + jitter


def random_retry_delay() -> float:
    jitter = random.uniform(
        RETRY_JITTER_MIN,
        RETRY_JITTER_MAX,
    )

    return RETRY_INTERVAL + jitter


# ================================================================
# VERIFICAR DISPONIBILIDADE DA VENDA
# ================================================================

async def sell_available(tab) -> bool:
    state = await get_sell_button_state(tab)

    if not state.get("found"):
        print("Botão #sell-all não encontrado.")
        return False

    if not state.get("visible"):
        print("Botão #sell-all não está visível.")
        return False

    if state.get("disabled"):
        return False

    if state.get("has_disabled_attribute"):
        return False

    if str(
        state.get("aria_disabled", "")
    ).lower() == "true":
        return False

    return True


# ================================================================
# AGUARDAR VENDA DISPONÍVEL
# ================================================================

async def wait_until_sell_available(tab) -> bool:
    while True:

        if await sell_available(tab):

            print()
            print("Venda disponível.")

            return True

        delay = random_retry_delay()

        jitter = delay - RETRY_INTERVAL

        print()
        print("Venda ainda está em cooldown.")

        print(
            f"Nova verificação em "
            f"{delay:.1f} segundos."
        )

        print(
            f"Intervalo: {RETRY_INTERVAL}s"
        )

        print(
            f"Jitter: +{jitter:.1f}s"
        )

        await asyncio.sleep(delay)


# ================================================================
# EXECUTAR VENDA
# ================================================================

async def execute_sale(
    tab,
    stats: HuntStats,
) -> bool:

    print()
    print("=== NOVA VENDA ===")

    # ============================================================
    # DISPONIBILIDADE
    # ============================================================

    if not await wait_until_sell_available(tab):
        return False

    # ============================================================
    # ABRIR MODAL
    # ============================================================

    if not await open_sale_confirmation(tab):

        print(
            "ERRO: não foi possível "
            "abrir a confirmação da venda."
        )

        return False

    # ============================================================
    # CAPTURAR VALOR
    # ============================================================

    sale_value = await get_sale_value(tab)

    if sale_value:

        print(
            "Valor da venda:",
            f"{format_gold(sale_value)} gold",
        )

    else:

        print(
            "AVISO: não foi possível "
            "capturar o valor da venda."
        )

    # ============================================================
    # CONFIRMAR
    # ============================================================

    if not await confirm_sale(tab):

        print(
            "ERRO: não foi possível "
            "confirmar a venda."
        )

        return False

    # ============================================================
    # CLOUDFLARE
    # ============================================================

    if not await wait_for_cloudflare(
        tab,
        timeout=60,
    ):

        print(
            "ERRO: validação Cloudflare "
            "não concluída."
        )

        return False

    # ============================================================
    # PROCESSAMENTO
    # ============================================================

    print(
        "Aguardando processamento "
        "da venda..."
    )

    await asyncio.sleep(2)

    # ============================================================
    # COOLDOWN
    # ============================================================

    if not await wait_for_sell_cooldown(
        tab,
        timeout=15,
    ):

        print(
            "ERRO: venda não entrou "
            "em cooldown."
        )

        return False

    print(
        "Venda processada com sucesso."
    )

    # ============================================================
    # ESTATÍSTICAS
    # ============================================================

    if sale_value > 0:

        stats.add_sale(sale_value)

        elapsed = stats.elapsed()

        gold_hour = stats.gold_per_hour()

        print()
        print(
            "========================================"
        )

        print(
            f"VENDA #{stats.sales}"
        )

        print(
            f"Valor: "
            f"{format_gold(sale_value)} gold"
        )

        print(
            f"Acumulado: "
            f"{format_gold(stats.total_gold)} gold"
        )

        print(
            f"Tempo de hunt: "
            f"{format_duration(elapsed)}"
        )

        print(
            f"Gold/h: "
            f"{format_gold(int(gold_hour))}"
        )

        print(
            "========================================"
        )

    return True


# ================================================================
# LOOP PRINCIPAL
# ================================================================

async def run_hunt(tab):

    stats = HuntStats(
        started_at=(
            asyncio.get_running_loop().time()
        )
    )

    print()
    print(
        "========================================"
    )

    print("HUNT INICIADA")

    print(
        "========================================"
    )

    print(
        f"Intervalo base: "
        f"{BASE_INTERVAL} segundos"
    )

    print(
        "Jitter principal: "
        f"+{MAIN_JITTER_MIN}s / "
        f"+{MAIN_JITTER_MAX}s"
    )

    print(
        "Retry: "
        f"{RETRY_INTERVAL}s + "
        f"{RETRY_JITTER_MIN}s / "
        f"{RETRY_JITTER_MAX}s"
    )

    print(
        "========================================"
    )

    while True:

        # ========================================================
        # INTERVALO PRINCIPAL
        # ========================================================

        delay = random_main_delay()

        jitter = delay - BASE_INTERVAL

        print()
        print(
            "----------------------------------------"
        )

        print(
            f"Próxima venda em "
            f"{delay:.1f} segundos."
        )

        print(
            f"Intervalo base: "
            f"{BASE_INTERVAL}s"
        )

        print(
            f"Jitter: +{jitter:.1f}s"
        )

        print(
            "----------------------------------------"
        )

        await asyncio.sleep(delay)

        # ========================================================
        # VENDA
        # ========================================================

        success = await execute_sale(
            tab,
            stats,
        )

        if not success:

            print()
            print(
                "A venda não foi concluída."
            )

            print(
                "O loop continuará."
            )

            retry_delay = random_retry_delay()

            retry_jitter = (
                retry_delay
                - RETRY_INTERVAL
            )

            print(
                f"Nova tentativa em "
                f"{retry_delay:.1f} segundos."
            )

            print(
                f"Jitter: "
                f"+{retry_jitter:.1f}s"
            )

            await asyncio.sleep(
                retry_delay
            )