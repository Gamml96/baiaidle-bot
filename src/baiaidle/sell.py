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
    stash_valuable_items
)

# === IMPORTANDO FUNÇÕES DE HUNT E TREINO ===
from baiaidle.hunts import get_current_hunt, change_hunt, go_to_training


# ================================================================
# CONFIGURAÇÃO
# ================================================================

BASE_INTERVAL = 120

MAIN_JITTER_MIN = 5
MAIN_JITTER_MAX = 10

RETRY_INTERVAL = 15

RETRY_JITTER_MIN = 5
RETRY_JITTER_MAX = 10

IR_PARA_TREINO_ONLINE = 20
VOLTAR_PARA_HUNT = 95

# ================================================================
# ESTATÍSTICAS
# ================================================================

@dataclass
class HuntStats:

    started_at: float = 0.0
    total_gold: int = 0
    sales: int = 0
    initial_xp: int | None = None
    current_xp: int = 0
    min_tier_to_stash: int = 4

    def reset(self):
        """Zera todos os dados da sessão."""
        self.started_at = asyncio.get_running_loop().time()
        self.total_gold = 0
        self.sales = 0
        self.initial_xp = None
        self.current_xp = 0

    def add_sale(self, value: int):
        self.total_gold += value
        self.sales += 1

    def update_xp(self, current_hud_xp: int):
        if current_hud_xp > 0:
            if self.initial_xp is None:
                self.initial_xp = current_hud_xp
            self.current_xp = current_hud_xp

    def get_session_xp(self) -> int:
        if self.initial_xp is None or self.current_xp <= self.initial_xp:
            return 0
        return self.current_xp - self.initial_xp

    def elapsed(self) -> float:
        if self.started_at == 0.0:
            return 0
        return asyncio.get_running_loop().time() - self.started_at

    def gold_per_hour(self) -> float:
        elapsed = self.elapsed()
        if elapsed <= 0:
            return 0
        return self.total_gold / elapsed * 3600

    def xp_per_hour(self) -> float:
        elapsed = self.elapsed()
        if elapsed <= 0:
            return 0
        return self.get_session_xp() / elapsed * 3600


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
    on_message=None, 
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
    
    # === NOVO BLOCO: SALVAR ITENS VALIOSOS ===
    print("Verificando itens raros no inventário (Tier 4+)...")
    stash_result = await stash_valuable_items(tab, min_tier=stats.min_tier_to_stash)
    
    if stash_result and stash_result.get("stashed", 0) > 0:
        stashed_items = stash_result.get("items", [])
        stashed_msg = ", ".join(stashed_items)
        print(f"💎 {stash_result['stashed']} item(ns) guardado(s): {stashed_msg}")
        
        if on_message:
            await on_message(f"💎 *Item Raro Protegido!*\nEnviado para o Backpack: {stashed_msg}")
            
        # Aguarda 1 segundo para a animação do jogo retirar os itens da grid
        await asyncio.sleep(1)
    # ==========================================

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

    hud_data = await get_hud_data(tab)
    
    current_balance_str = hud_data.get("gold", "0")
    current_xp_str = hud_data.get("xp", "0")
    stamina_pct = hud_data.get("stamina_pct", "0%")
    stamina_time = hud_data.get("stamina_time", "00:00")

    current_xp = parse_clean_int(current_xp_str)
    stats.update_xp(current_xp)

    if sale_value > 0:

        stats.add_sale(
            sale_value
        )
        
        session_gained_xp = stats.get_session_xp()

        print()
        print("========================================")
        print(f"VENDA #{stats.sales}")
        print(f"Valor: {format_number(sale_value)} gold")
        print(f"Acumulado da Hunt: {format_number(stats.total_gold)} gold")
        print(f"Saldo Total (HUD): {current_balance_str}")
        print(f"XP Obtida na Sessão: {format_number(session_gained_xp)}")
        print(f"XP/h: {format_number(int(stats.xp_per_hour()))}")
        print(f"Stamina: {stamina_pct} (Regenera em: {stamina_time})")
        print(f"Tempo: {format_duration(stats.elapsed())}")
        print(f"Gold/h: {format_number(int(stats.gold_per_hour()))}")
        print("========================================")

        if on_message:
            msg_telegram = (
                f"💰 *VENDA #{stats.sales}*\n\n"
                f"⏱️ Duração: {format_duration(stats.elapsed())}\n"
                f"⚡ Stamina: {stamina_pct} (Tempo: {stamina_time})\n\n"
                f"🪙 Valor: {format_number(sale_value)} gold\n"
                f"📈 Acumulado da Hunt: {format_number(stats.total_gold)} gold\n"
                f"⚖️ Gold/h: {format_number(int(stats.gold_per_hour()))}\n"
                f"🏦 Saldo Total: {current_balance_str}\n\n"
                f"✨ XP Obtida na Sessão: {format_number(session_gained_xp)}\n"
                f"📊 XP/h: {format_number(int(stats.xp_per_hour()))}\n"
            )
            
            try:
                await on_message(msg_telegram)
            except Exception as e:
                print(f"Erro ao notificar Telegram: {e}")

    return True

# ================================================================
# GERENCIADOR DE TREINO
# ================================================================

async def manage_training(tab, stop_event, pause_event, on_message, current_hunt):
    """
    Controla o ciclo do bot enquanto a stamina regenera.
    Acorda a cada 60s, mas avisa o Telegram apenas a cada 10 minutos.
    """
    success = await go_to_training(tab)
    if not success:
        if on_message:
            await on_message("❌ Falha ao tentar ir para o Treino Online. O bot tentará continuar as vendas.")
        return False
        
    training = True
    last_report_time = asyncio.get_running_loop().time()
    
    while training and not stop_event.is_set():
        if not pause_event.is_set():
            await pause_event.wait()
            continue
            
        for _ in range(60):
            if stop_event.is_set() or not pause_event.is_set():
                break
            await asyncio.sleep(1)
            
        if stop_event.is_set() or not pause_event.is_set():
            continue
            
        hud_data = await get_hud_data(tab)
        current_stam_str = hud_data.get("stamina_pct", "0%")
        current_stam_val = parse_clean_int(current_stam_str)
        stam_time = hud_data.get("stamina_time", "00:00")
        
        now = asyncio.get_running_loop().time()
        
        if current_stam_val >= VOLTAR_PARA_HUNT:
            msg_done = f"🔋 Stamina recuperada ({current_stam_val}%). Retornando para a hunt: {current_hunt}."
            print(msg_done)
            if on_message:
                await on_message(f"✅ {msg_done}")
            
            await change_hunt(tab, current_hunt)
            return True
            
        if now - last_report_time >= 600:
            last_report_time = now
            report_msg = f"🧘‍♂️ *Treinando...*\n⚡ Stamina atual: {current_stam_str}\n⏳ Tempo para 100%: {stam_time}"
            print(report_msg)
            if on_message:
                await on_message(report_msg)
                
    return True


# ================================================================
# LOOP DA HUNT
# ================================================================

async def run_sell(
    tab,
    stop_event,
    pause_event,
    stats: HuntStats,
    on_message=None, 
):

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

            success = await execute_sale(
                tab,
                stats,
                stop_event=stop_event,
                on_message=on_message,
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

                continue 

            # ====================================================
            # VERIFICAR STAMINA APÓS A VENDA
            # ====================================================
            if not stop_event.is_set() and pause_event.is_set():
                hud_data = await get_hud_data(tab)
                stamina_str = hud_data.get("stamina_pct", "0%")
                stamina_val = parse_clean_int(stamina_str)
                
                if 0 < stamina_val <= IR_PARA_TREINO_ONLINE:
                    current_hunt = await get_current_hunt(tab)
                    if not current_hunt:
                        current_hunt = "Hunt Desconhecida"
                        
                    msg = f"🔋 *Stamina Crítica* ({stamina_val}%).\n\n⏸️ Pausando a hunt atual ({current_hunt}) e indo para o Treino Online."
                    print(msg.replace('*', ''))
                    if on_message:
                        await on_message(f"⚠️ {msg}")
                        
                    await manage_training(tab, stop_event, pause_event, on_message, current_hunt)

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