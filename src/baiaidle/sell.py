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
    get_hud_data,
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

    total_xp: int = 0

    def add_sale(
        self,
        value: int,
    ):

        self.total_gold += value

        self.sales += 1

    def add_xp(
        self,
        xp_value: int,
    ):
        if xp_value > 0:
            self.total_xp += xp_value

    def elapsed(
        self,
    ) -> float:

        return (
            asyncio.get_running_loop().time()
            - self.started_at
        )

    def gold_per_hour(
        self,
    ) -> float:

        elapsed = self.elapsed()

        if elapsed <= 0:

            return 0

        return (
            self.total_gold
            / elapsed
            * 3600
        )

    def xp_per_hour(
        self,
    ) -> float:

        elapsed = self.elapsed()

        if elapsed <= 0:

            return 0

        return (
            self.total_xp
            / elapsed
            * 3600
        )


# ================================================================
# UTILITÁRIOS
# ================================================================

def format_number(
    value: int,
) -> str:

    return f"{value:,}".replace(
        ",",
        ".",
    )


def format_duration(
    seconds: float,
) -> str:

    total_seconds = int(
        seconds
    )

    hours = (
        total_seconds // 3600
    )

    minutes = (
        total_seconds % 3600
    ) // 60

    secs = (
        total_seconds % 60
    )

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

    return (
        BASE_INTERVAL
        + jitter
    )


def random_retry_delay() -> float:

    jitter = random.uniform(
        RETRY_JITTER_MIN,
        RETRY_JITTER_MAX,
    )

    return (
        RETRY_INTERVAL
        + jitter
    )


def parse_clean_int(text: str) -> int:
    """
    Remove pontos e caracteres não numéricos para converter em inteiro.
    """
    import re
    cleaned = re.sub(r"[^0-9]", "", text)
    if not cleaned:
        return 0
    try:
        return int(cleaned)
    except ValueError:
        return 0


# ================================================================
# VENDA DISPONÍVEL
# ================================================================

async def sell_available(
    tab,
) -> bool:

    state = await get_sell_button_state(
        tab
    )

    if not state.get("found"):

        return False

    if not state.get("visible"):

        return False

    if state.get("disabled"):

        return False

    if state.get(
        "has_disabled_attribute"
    ):

        return False

    if str(
        state.get(
            "aria_disabled",
            "",
        )
    ).lower() == "true":

        return False

    return True


# ================================================================
# AGUARDAR VENDA
# ================================================================

async def wait_until_sell_available(
    tab,
    stop_event=None,
) -> bool:

    while True:

        if (
            stop_event
            and stop_event.is_set()
        ):

            return False

        if await sell_available(
            tab
        ):

            print()
            print(
                "Venda disponível."
            )

            return True

        delay = random_retry_delay()

        print()
        print(
            "Venda ainda está "
            "em cooldown."
        )

        print(
            f"Nova verificação em "
            f"{delay:.1f} segundos."
        )

        remaining = delay

        while remaining > 0:

            if (
                stop_event
                and stop_event.is_set()
            ):

                return False

            sleep_time = min(
                1,
                remaining,
            )

            await asyncio.sleep(
                sleep_time
            )

            remaining -= sleep_time


# ================================================================
# EXECUTAR VENDA
# ================================================================

async def execute_sale(
    tab,
    stats: HuntStats,
    stop_event=None,
    on_message=None,  # <--- NOVA LINHA: Recebe o callback do Telegram
) -> bool:

    print()
    print(
        "=== NOVA VENDA ==="
    )

    if not await wait_until_sell_available(
        tab,
        stop_event=stop_event,
    ):

        return False

    if (
        stop_event
        and stop_event.is_set()
    ):

        return False

    if not await open_sale_confirmation(
        tab
    ):

        print(
            "ERRO: não foi possível "
            "abrir a confirmação."
        )

        return False

    sale_value = await get_sale_value(
        tab
    )

    if sale_value:

        print(
            "Valor da venda:",
            f"{format_number(sale_value)} gold",
        )

    else:

        print(
            "AVISO: valor não capturado."
        )

    if not await confirm_sale(
        tab
    ):

        print(
            "ERRO: não foi possível "
            "confirmar a venda."
        )

        return False

    if not await wait_for_cloudflare(
        tab,
        timeout=60,
    ):

        print(
            "ERRO: Cloudflare."
        )

        return False

    print(
        "Aguardando processamento..."
    )

    await asyncio.sleep(2)

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

    # Coleta os dados atualizados do HUD após a venda processada
    hud_data = await get_hud_data(tab)
    
    current_balance_str = hud_data.get("gold", "0")
    current_xp_str = hud_data.get("xp", "0")
    stamina_pct = hud_data.get("stamina_pct", "0%")
    stamina_time = hud_data.get("stamina_time", "00:00")

    current_xp = parse_clean_int(current_xp_str)
    stats.add_xp(current_xp)

    if sale_value > 0:

        stats.add_sale(
            sale_value
        )

        # Printa no terminal
        print()
        print("========================================")
        print(f"VENDA #{stats.sales}")
        print(f"Tempo: {format_duration(stats.elapsed())}")
        print(f"Valor: {format_number(sale_value)} gold")
        print(f"Acumulado da Hunt: {format_number(stats.total_gold)} gold")
        print(f"Gold Total (HUD): {current_balance_str}")
        print(f"XP Obtida: {format_number(current_xp)}")
        print(f"XP/h: {format_number(int(stats.xp_per_hour()))}")
        print(f"Stamina: {stamina_pct} ({stamina_time})")
        print(f"Gold/h: {format_number(int(stats.gold_per_hour()))}")
        print("========================================")

        # ========================================================
        # ENVIA MENSAGEM PARA O TELEGRAM
        # ========================================================
        if on_message:
            msg_telegram = (
                f"💰 *VENDA #{stats.sales}*\n\n"
                f"⏱️ Duração: {format_duration(stats.elapsed())}\n"
                f"⚡ Stamina: {stamina_pct} ({stamina_time})\n\n"
                f"🪙 Valor: {format_number(sale_value)} gold\n"
                f"📈 Acumulado da Hunt: {format_number(stats.total_gold)} gold\n"
                f"⚖️ Gold/h: {format_number(int(stats.gold_per_hour()))}"
                f"🏦 Gold Total: {current_balance_str}\n\n"
                f"✨ XP Obtida: {format_number(current_xp)}\n"
                f"📊 XP/h: {format_number(int(stats.xp_per_hour()))}\n"
            )
            
            try:
                # O telegram permite usar parse_mode="Markdown" para renderizar negritos
                await on_message(msg_telegram)
            except Exception as e:
                print(f"Erro ao notificar Telegram: {e}")

    return True


# ================================================================
# LOOP DA HUNT
# ================================================================

async def run_sell(
    tab,
    stop_event,
    pause_event,
    on_message=None,  # <--- NOVA LINHA: Recebe o callback
):

    stats = HuntStats(
        started_at=(
            asyncio.get_running_loop().time()
        )
    )

    print()
    print(
        "========================================"
    )

    print(
        "HUNT INICIADA"
    )

    print(
        "========================================"
    )

    try:

        while not stop_event.is_set():

            # ====================================================
            # PAUSA
            # ====================================================

            if not pause_event.is_set():

                print()
                print(
                    "Hunt pausada."
                )

                await pause_event.wait()

                if stop_event.is_set():

                    break

                print()
                print(
                    "Hunt retomada."
                )

                continue

            # ====================================================
            # INTERVALO
            # ====================================================

            delay = random_main_delay()

            print()
            print(
                f"Próxima venda em "
                f"{delay:.1f}s."
            )

            remaining = delay

            while remaining > 0:

                if stop_event.is_set():

                    break

                if not pause_event.is_set():

                    break

                sleep_time = min(
                    1,
                    remaining,
                )

                await asyncio.sleep(
                    sleep_time
                )

                remaining -= sleep_time

            if stop_event.is_set():

                break

            if not pause_event.is_set():

                continue

            # ====================================================
            # VENDA
            # ====================================================

            success = await execute_sale(
                tab,
                stats,
                stop_event=stop_event,
                on_message=on_message,  # <--- NOVA LINHA: Passa para o execute_sale
            )

            if (
                not success
                and not stop_event.is_set()
                and pause_event.is_set()
            ):

                print()
                print(
                    "A venda não foi concluída."
                )

                retry_delay = (
                    random_retry_delay()
                )

                print(
                    f"Nova tentativa em "
                    f"{retry_delay:.1f}s."
                )

                remaining = retry_delay

                while remaining > 0:

                    if stop_event.is_set():

                        break

                    if not pause_event.is_set():

                        break

                    await asyncio.sleep(
                        min(1, remaining)
                    )

                    remaining -= min(
                        1,
                        remaining,
                    )

    except asyncio.CancelledError:

        print(
            "Task da Hunt cancelada."
        )

        raise

    finally:

        print()
        print(
            "Hunt encerrada."
        )