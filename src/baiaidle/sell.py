import asyncio
import random
import re
from dataclasses import dataclass

from baiaidle.actions import (
    get_sale_value,
    get_sell_button_state,
    open_sale_confirmation,
    confirm_sale,
    wait_for_cloudflare,
    wait_for_sell_cooldown,
    get_hud_data,
    stash_valuable_items,
    get_loot_analyzer_coins,
)

# === IMPORTANDO FUNÇÕES DE HUNT E TREINO ===
from baiaidle.hunts import get_current_hunt, change_hunt, go_to_training, go_to_house
from baiaidle.guild import get_tracked_task_progress, process_guild_tasks
from baiaidle.codex import process_codex_routine
from baiaidle.battlepass import get_tracked_battlepass_progress, process_battlepass
from baiaidle.recovery import dismiss_welcome_and_popups
from baiaidle.settings import get_setting

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
VOLTAR_PARA_HUNT = 100

MAX_STAMINA_HOURS = 42
MAX_STAMINA_MINUTES = MAX_STAMINA_HOURS * 60  # 2520 minutos (42 horas)
STAMINA_RECOVERY_RATE = 8.0                   # 1 minuto real recupera 8 minutos de stamina

DEFAULT_HUNT = "Infernal Demon"

# ================================================================
# ESTATÍSTICAS
# ================================================================

@dataclass
class HuntStats:

    started_at: float = 0.0
    total_gold: int = 0
    sales: int = 0
    current_xp: int = 0
    min_tier_to_stash: int = 4
    force_action: str | None = None
    codex_progress: str = "0%"
    last_task_report: float = 0.0
    default_hunt: str = DEFAULT_HUNT
    last_crystal_coins: int = 0
    last_platinum_coins: int = 0
    last_gold_coins: int = 0
    coins_initialized: bool = False
    session_crystal_coins: int = 0
    session_platinum_coins: int = 0
    session_gold_coins: int = 0
    total_coin_gold: int = 0

    def reset(self):
        """Zera todos os dados da sessão."""
        try:
            self.started_at = asyncio.get_running_loop().time()
        except RuntimeError:
            import time
            self.started_at = time.time()
        self.total_gold = 0
        self.sales = 0
        self.current_xp = 0
        self.force_action = None
        self.codex_progress = "0%"
        self.last_task_report = 0.0
        self.last_crystal_coins = 0
        self.last_platinum_coins = 0
        self.last_gold_coins = 0
        self.coins_initialized = False
        self.session_crystal_coins = 0
        self.session_platinum_coins = 0
        self.session_gold_coins = 0
        self.total_coin_gold = 0
        if not getattr(self, "default_hunt", None):
            self.default_hunt = DEFAULT_HUNT

    def init_coins(self, coins: dict[str, int]):
        """Inicializa a contagem base de moedas do Loot Analyser."""
        self.last_crystal_coins = coins.get("crystal", 0)
        self.last_platinum_coins = coins.get("platinum", 0)
        self.last_gold_coins = coins.get("gold", 0)
        self.coins_initialized = True

    def calculate_coin_deltas(self, current_coins: dict[str, int]) -> tuple[dict[str, int], int]:
        """
        Calcula os deltas de moedas e valor total em gold sem atualizar o estado interno.
        Valores:
          1 crystal coin = 10.000 gold
          1 platinum coin = 100 gold
          1 gold coin = 1 gold
        """
        curr_crystal = current_coins.get("crystal", 0)
        curr_platinum = current_coins.get("platinum", 0)
        curr_gold = current_coins.get("gold", 0)

        if not self.coins_initialized:
            return {"crystal": 0, "platinum": 0, "gold": 0}, 0

        delta_crystal = (curr_crystal - self.last_crystal_coins) if curr_crystal >= self.last_crystal_coins else curr_crystal
        delta_platinum = (curr_platinum - self.last_platinum_coins) if curr_platinum >= self.last_platinum_coins else curr_platinum
        delta_gold = (curr_gold - self.last_gold_coins) if curr_gold >= self.last_gold_coins else curr_gold

        coin_gold = (delta_crystal * 10000) + (delta_platinum * 100) + (delta_gold * 1)
        return {
            "crystal": delta_crystal,
            "platinum": delta_platinum,
            "gold": delta_gold,
        }, coin_gold

    def commit_coins(self, current_coins: dict[str, int], deltas: dict[str, int], coin_gold: int):
        """
        Confirma a atualização do estado das moedas após uma venda bem-sucedida.
        """
        self.last_crystal_coins = current_coins.get("crystal", 0)
        self.last_platinum_coins = current_coins.get("platinum", 0)
        self.last_gold_coins = current_coins.get("gold", 0)
        self.coins_initialized = True

        self.session_crystal_coins += deltas.get("crystal", 0)
        self.session_platinum_coins += deltas.get("platinum", 0)
        self.session_gold_coins += deltas.get("gold", 0)
        self.total_coin_gold += coin_gold

    def add_sale(self, value: int):
        self.total_gold += value
        self.sales += 1

    def update_xp(self, gained_xp: int):
        self.current_xp = gained_xp

    def get_session_xp(self) -> int:
        return self.current_xp

    def elapsed(self) -> float:
        if self.started_at == 0.0:
            return 0
        try:
            now = asyncio.get_running_loop().time()
        except RuntimeError:
            import time
            now = time.time()
        return now - self.started_at

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


def format_coin_breakdown(deltas: dict[str, int]) -> str:
    """Formata o detalhamento das moedas coletadas."""
    parts = []
    if deltas.get("crystal", 0) > 0:
        parts.append(f"{format_number(deltas['crystal'])} crystal coin")
    if deltas.get("platinum", 0) > 0:
        parts.append(f"{format_number(deltas['platinum'])} platinum coin")
    if deltas.get("gold", 0) > 0:
        parts.append(f"{format_number(deltas['gold'])} gold coin")
    return ", ".join(parts) if parts else "0 moedas"



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
    cleaned = re.sub(r"[^0-9]", "", text)
    if not cleaned:
        return 0
    try:
        return int(cleaned)
    except ValueError:
        return 0


def parse_stamina_time_to_minutes(stam_time: str) -> int | None:
    """
    Converte strings de tempo de stamina como '35:20', '35:20:00', '35h 20m', '35h'
    em minutos totais de stamina. Retorna None se não for possível converter.
    """
    if not stam_time:
        return None
    s = stam_time.strip()

    # Formato HH:MM ou HH:MM:SS (ex: "35:20" ou "35:20:00")
    m = re.match(r"^(\d{1,3}):(\d{2})(?::\d{2})?$", s)
    if m:
        hours = int(m.group(1))
        mins = int(m.group(2))
        return hours * 60 + mins

    # Formato com 'h' e 'm' (ex: "35h 20m", "35h", "20m")
    m = re.match(r"^(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?$", s, re.IGNORECASE)
    if m and (m.group(1) or m.group(2)):
        hours = int(m.group(1)) if m.group(1) else 0
        mins = int(m.group(2)) if m.group(2) else 0
        return hours * 60 + mins

    return None


def calculate_remaining_recovery_time(stam_time_str: str, stam_pct_val: int) -> tuple[int, str]:
    """
    Calcula o tempo real estimado restante até atingir 100% de stamina (42 horas).
    Considera a taxa de que a cada 1 minuto de treino real recupera-se 8 minutos de stamina.
    Retorna (minutos_reais_restantes, string_formatada).
    """
    current_minutes = parse_stamina_time_to_minutes(stam_time_str)

    # Se parseou com sucesso e stamina já está no máximo ou acima
    if current_minutes is not None and current_minutes >= MAX_STAMINA_MINUTES:
        return 0, "0m (100%)"

    # Se parseou com sucesso e deu > 0, calcula a partir do tempo exato
    if current_minutes is not None and current_minutes > 0:
        needed_stamina_min = max(0, MAX_STAMINA_MINUTES - current_minutes)
    elif stam_pct_val is not None and stam_pct_val > 0:
        pct = max(0, min(100, stam_pct_val))
        if pct >= 100:
            return 0, "0m (100%)"
        needed_stamina_min = MAX_STAMINA_MINUTES * (1.0 - (pct / 100.0))
    else:
        if current_minutes == 0 and stam_pct_val == 0:
            needed_stamina_min = MAX_STAMINA_MINUTES
        else:
            return 0, "desconhecido"

    if needed_stamina_min <= 0:
        return 0, "0m (100%)"

    real_minutes_needed = round(needed_stamina_min / STAMINA_RECOVERY_RATE)
    if real_minutes_needed <= 0:
        return 0, "< 1m"

    hours = real_minutes_needed // 60
    mins = real_minutes_needed % 60

    if hours > 0 and mins > 0:
        formatted = f"{hours}h {mins}m"
    elif hours > 0:
        formatted = f"{hours}h"
    else:
        formatted = f"{mins}m"

    return real_minutes_needed, formatted


def is_training_location(location: str | None) -> tuple[bool, str]:
    """
    Identifica se a localização atual (#wave-title) é Treino Online ou Casa.
    Retorna (is_training, tipo) onde tipo é 'treino', 'casa' ou ''.
    """
    if not location or not isinstance(location, str):
        return False, ""
    loc = location.strip().lower()

    # Treino Online
    if any(k in loc for k in ["treino", "exercise", "treinamento", "training"]):
        return True, "treino"

    # Casa
    if any(k in loc for k in ["casa", "house", "dummy", "dummies"]):
        return True, "casa"

    return False, ""


async def resolve_target_hunt(tab, stats: HuntStats | None = None) -> str:
    """
    Identifica a hunt atual. Se for desconhecida ou se o personagem estiver no treino/casa,
    retorna a hunt padrão configurada (Infernal Demon por padrão).
    """
    fallback = (stats.default_hunt if stats and stats.default_hunt else DEFAULT_HUNT)
    current = await get_current_hunt(tab)
    if not current or not isinstance(current, str):
        return fallback
    current = current.strip()
    is_training, _ = is_training_location(current)
    if is_training or current.lower() == "hunt desconhecida":
        return fallback
    return current


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
    bot=None,
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
    min_tier = get_setting("min_tier_stash", stats.min_tier_to_stash)
    print(f"Verificando itens raros no inventário (Tier {min_tier}+)...")
    stash_result = await stash_valuable_items(tab, min_tier=min_tier)
    
    if stash_result and stash_result.get("stashed", 0) > 0:
        stashed_items = stash_result.get("items", [])
        stashed_msg = ", ".join(stashed_items)
        print(f"💎 {stash_result['stashed']} item(ns) guardado(s): {stashed_msg}")
        
        if on_message:
            await on_message(f"💎 *Item Raro Protegido!*\nEnviado para o Backpack: {stashed_msg}")
            
        # Aguarda 1 segundo para a animação do jogo retirar os itens da grid
        await asyncio.sleep(1)
    # ==========================================

    # === CAPTURA DE MOEDAS NO LOOT ANALYSER ===
    # Moedas (crystal, platinum, gold) vão direto ao banco e não entram no pouch de venda,
    # mas são registradas no Loot Analyser.
    current_coins = await get_loot_analyzer_coins(tab)
    if not stats.coins_initialized:
        stats.init_coins(current_coins)
        coin_deltas, coin_gold = {"crystal": 0, "platinum": 0, "gold": 0}, 0
    else:
        coin_deltas, coin_gold = stats.calculate_coin_deltas(current_coins)

    if coin_gold > 0:
        print(f"🪙 Moedas detectadas na hunt: +{format_number(coin_gold)} gold ({format_coin_breakdown(coin_deltas)})")
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
            "Valor da venda de itens:",
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

    # if not await wait_for_cloudflare(
    #     tab,
    #     timeout=60,
    # ):

    #     print(
    #         "ERRO: Cloudflare."
    #     )

    #     return False

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

    if bot and hasattr(bot, "touch_activity"):
        bot.touch_activity()

    # Confirma o avanço das moedas registradas após a venda bem-sucedida
    stats.commit_coins(current_coins, coin_deltas, coin_gold)

    hud_data = await get_hud_data(tab)
    
    current_balance_str = hud_data.get("gold", "0")
    stamina_pct = hud_data.get("stamina_pct", "0%")
    stamina_time = hud_data.get("stamina_time", "00:00")

    # ==========================================================
    # LER XP DIRETAMENTE DO HUNT ANALYZER (#an-raw)
    # ==========================================================
    js_analyzer = "(() => { const el = document.getElementById('an-raw'); return el ? el.innerText.trim() : '0'; })()"
    res_analyzer = await tab.execute_script(js_analyzer)
    
    analyzer_xp_str = "0"
    if isinstance(res_analyzer, dict):
        try:
            analyzer_xp_str = res_analyzer["result"]["result"].get("value", "0")
        except:
            pass
    else:
        if res_analyzer:
            analyzer_xp_str = str(res_analyzer)

    current_xp = parse_clean_int(analyzer_xp_str)
    stats.update_xp(current_xp)
    # ==========================================================

    total_sale_value = sale_value + coin_gold

    if total_sale_value > 0:

        stats.add_sale(
            total_sale_value
        )
        
        session_gained_xp = stats.get_session_xp()

        print()
        print("========================================")
        print(f"VENDA #{stats.sales}")
        if coin_gold > 0:
            print(f"Itens Vendidos: {format_number(sale_value)} gold")
            print(f"Moedas Coletadas: +{format_number(coin_gold)} gold ({format_coin_breakdown(coin_deltas)})")
            print(f"Valor Total desta Venda: {format_number(total_sale_value)} gold")
        else:
            print(f"Valor: {format_number(total_sale_value)} gold")
        print(f"Acumulado da Hunt: {format_number(stats.total_gold)} gold")
        print(f"Saldo Total (HUD): {current_balance_str}")
        print(f"XP Obtida na Sessão: {format_number(session_gained_xp)}")
        print(f"XP/h: {format_number(int(stats.xp_per_hour()))}")
        print(f"Stamina: {stamina_pct} (Regenera em: {stamina_time})")
        print(f"Tempo: {format_duration(stats.elapsed())}")
        print(f"Gold/h: {format_number(int(stats.gold_per_hour()))}")
        print(f"Codex da Hunt: {stats.codex_progress}")
        print("========================================")

        notify_enabled = get_setting("notify_sales", True)
        if on_message and notify_enabled:
            if coin_gold > 0:
                coin_str = format_coin_breakdown(coin_deltas)
                msg_telegram = (
                    f"💰 *VENDA #{stats.sales}*\n\n"
                    f"⏱️ Duração: {format_duration(stats.elapsed())}\n"
                    f"⚡ Stamina: {stamina_pct} (Tempo: {stamina_time})\n"
                    f"📖 Codex Atual: {stats.codex_progress}\n\n"
                    f"📦 Itens Vendidos: {format_number(sale_value)} gold\n"
                    f"🪙 Moedas Coletadas: +{format_number(coin_gold)} gold ({coin_str})\n"
                    f"💵 *Valor Total:* {format_number(total_sale_value)} gold\n"
                    f"📈 Acumulado da Hunt: {format_number(stats.total_gold)} gold\n"
                    f"⚖️ Gold/h: {format_number(int(stats.gold_per_hour()))}\n"
                    f"🏦 Saldo Total: {current_balance_str}\n\n"
                    f"✨ XP Obtida na Sessão: {format_number(session_gained_xp)}\n"
                    f"📊 XP/h: {format_number(int(stats.xp_per_hour()))}\n"
                )
            else:
                msg_telegram = (
                    f"💰 *VENDA #{stats.sales}*\n\n"
                    f"⏱️ Duração: {format_duration(stats.elapsed())}\n"
                    f"⚡ Stamina: {stamina_pct} (Tempo: {stamina_time})\n"
                    f"📖 Codex Atual: {stats.codex_progress}\n\n"
                    f"🪙 Valor: {format_number(total_sale_value)} gold\n"
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

async def manage_training(tab, stop_event, pause_event, on_message, current_hunt, already_there=False, bot=None):
    """
    Controla o ciclo do bot enquanto a stamina regenera.
    Acorda a cada 60s, mas avisa o Telegram apenas a cada 10 minutos.
    """
    if not already_there:
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

        if bot and hasattr(bot, "touch_activity"):
            bot.touch_activity()
            
        hud_data = await get_hud_data(tab)
        current_stam_str = hud_data.get("stamina_pct", "0%")
        current_stam_val = parse_clean_int(current_stam_str)
        stam_time = hud_data.get("stamina_time", "00:00")
        current_minutes = parse_stamina_time_to_minutes(stam_time)
        
        now = asyncio.get_running_loop().time()
        
        target_retorno = get_setting("stamina_retorno", VOLTAR_PARA_HUNT)
        if current_stam_val >= target_retorno or (current_minutes is not None and current_minutes >= MAX_STAMINA_MINUTES):
            msg_done = f"🔋 Stamina recuperada ({current_stam_val}%). Retornando para a hunt: {current_hunt}."
            print(msg_done)
            if on_message:
                await on_message(f"✅ {msg_done}")
            
            # Tenta voltar para a hunt repetidamente até conseguir
            viagem_sucesso = False
            while not viagem_sucesso and not stop_event.is_set():
                viagem_sucesso, msg_viagem = await change_hunt(tab, current_hunt)
                if not viagem_sucesso:
                    print(f"⚠️ Falha ao voltar para a Hunt. Tentando novamente em 5s... Erro: {msg_viagem}")
                    await asyncio.sleep(5)
                    
            return True
            
        if now - last_report_time >= 600:
            last_report_time = now
            _, time_remaining_str = calculate_remaining_recovery_time(stam_time, current_stam_val)
            report_msg = (
                f"🧘‍♂️ *Treinando...*\n"
                f"⚡ Stamina atual: {current_stam_str} ({stam_time})\n"
                f"⏳ Restante até 100%: ~{time_remaining_str}"
            )
            print(report_msg)
            if on_message:
                await on_message(report_msg)
                
    return True

async def manage_house_training(tab, stop_event, pause_event, on_message, current_hunt, silent_fail=False, already_there=False, bot=None):
    """
    Controla o ciclo do bot na Casa enquanto a stamina regenera.
    Acorda a cada 60s, mas avisa o Telegram apenas a cada 10 minutos.
    """
    if not already_there:
        success = await go_to_house(tab)
        if not success:
            if on_message and not silent_fail:
                await on_message("❌ Nenhuma Casa com dummy ativo encontrada no momento.")
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

        if bot and hasattr(bot, "touch_activity"):
            bot.touch_activity()
            
        hud_data = await get_hud_data(tab)
        current_stam_str = hud_data.get("stamina_pct", "0%")
        current_stam_val = parse_clean_int(current_stam_str)
        stam_time = hud_data.get("stamina_time", "00:00")
        current_minutes = parse_stamina_time_to_minutes(stam_time)
        
        now = asyncio.get_running_loop().time()
        
        target_retorno = get_setting("stamina_retorno", VOLTAR_PARA_HUNT)
        if current_stam_val >= target_retorno or (current_minutes is not None and current_minutes >= MAX_STAMINA_MINUTES):
            msg_done = f"🔋 Stamina recuperada ({current_stam_val}%). Saindo da Casa e retornando para: {current_hunt}."
            print(msg_done)
            if on_message:
                await on_message(f"✅ {msg_done}")
            
            # Tenta voltar para a hunt repetidamente até conseguir
            viagem_sucesso = False
            while not viagem_sucesso and not stop_event.is_set():
                viagem_sucesso, msg_viagem = await change_hunt(tab, current_hunt)
                if not viagem_sucesso:
                    print(f"⚠️ Falha ao voltar para a Hunt. Tentando novamente em 5s... Erro: {msg_viagem}")
                    await asyncio.sleep(5)

            return True
            
        if now - last_report_time >= 600:
            last_report_time = now
            _, time_remaining_str = calculate_remaining_recovery_time(stam_time, current_stam_val)
            report_msg = (
                f"🏠 *Treinando na Casa...*\n"
                f"⚡ Stamina atual: {current_stam_str} ({stam_time})\n"
                f"⏳ Restante até 100%: ~{time_remaining_str}"
            )
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
    bot=None,
):

    print("\n========================================")
    print("HUNT INICIADA")
    print("========================================")

    # Inicializa a contagem base de moedas do Loot Analyser
    if not stats.coins_initialized:
        try:
            initial_coins = await get_loot_analyzer_coins(tab)
            stats.init_coins(initial_coins)
            print(
                f"Loot Analyser inicializado: {stats.last_crystal_coins} crystal, "
                f"{stats.last_platinum_coins} plat, {stats.last_gold_coins} gold"
            )
        except Exception as e:
            print(f"Aviso ao inicializar moedas do Loot Analyser: {e}")


    try:

        while not stop_event.is_set():

            # ====================================================
            # INTERRUPÇÃO MANUAL (VIA TELEGRAM)
            # ====================================================
            if stats.force_action:
                action = stats.force_action
                stats.force_action = None
                
                current_hunt = await resolve_target_hunt(tab, stats)
                    
                if action == "casa":
                    if on_message:
                        await on_message("🏠 Iniciando ida manual para a Casa...")
                    
                    house_success = await manage_house_training(tab, stop_event, pause_event, on_message, current_hunt, silent_fail=True, bot=bot)
                    if not house_success:
                        if on_message:
                            await on_message("❌ Casa indisponível. Redirecionando para o Treino Online padrão...")
                        await manage_training(tab, stop_event, pause_event, on_message, current_hunt, bot=bot)
                        
                elif action == "treino":
                    if on_message:
                        await on_message("🧘‍♂️ Iniciando ida manual para o Treino Online...")
                    await manage_training(tab, stop_event, pause_event, on_message, current_hunt, bot=bot)
                
                continue 
            # ====================================================

            # ====================================================
            # LIMPEZA PREVENTIVA DE TELAS RESIDUAIS / BOAS-VINDAS
            # ====================================================
            try:
                await dismiss_welcome_and_popups(tab, max_passes=1)
            except Exception:
                pass

            # ====================================================
            # DETECÇÃO AUTOMÁTICA DE LOCALIZAÇÃO (TREINO / CASA)
            # ====================================================
            current_loc = await get_current_hunt(tab)
            is_training, train_type = is_training_location(current_loc)
            if is_training:
                hud_data = await get_hud_data(tab)
                stam_pct = parse_clean_int(hud_data.get("stamina_pct", "0%"))
                stam_time = hud_data.get("stamina_time", "00:00")
                current_minutes = parse_stamina_time_to_minutes(stam_time)
                
                is_full = (stam_pct >= VOLTAR_PARA_HUNT) or (current_minutes is not None and current_minutes >= MAX_STAMINA_MINUTES)
                target_hunt = stats.default_hunt or DEFAULT_HUNT

                if is_full:
                    msg = f"🔋 Personagem detectado no {current_loc} com Stamina cheia ({stam_pct}%). Retornando para a hunt padrão: {target_hunt}."
                    print(msg)
                    if on_message:
                        await on_message(f"✅ {msg}")
                    await change_hunt(tab, target_hunt)
                else:
                    _, time_remaining_str = calculate_remaining_recovery_time(stam_time, stam_pct)
                    mode_name = "Casa (Dummies)" if train_type == "casa" else "Treino Online"
                    msg = (
                        f"🧘‍♂️ *Modo Treino Ativado!*\n"
                        f"Detectado que o personagem já está em: *{current_loc}* ({mode_name})\n\n"
                        f"⚡ Stamina atual: {hud_data.get('stamina_pct', f'{stam_pct}%')} ({stam_time})\n"
                        f"⏳ Restante até 100%: ~{time_remaining_str}\n"
                        f"🎯 Hunt de retorno configurada: *{target_hunt}*"
                    )
                    print(msg.replace('*', ''))
                    if on_message:
                        await on_message(msg)

                    if train_type == "casa":
                        await manage_house_training(tab, stop_event, pause_event, on_message, target_hunt, silent_fail=True, already_there=True, bot=bot)
                    else:
                        await manage_training(tab, stop_event, pause_event, on_message, target_hunt, already_there=True, bot=bot)

                continue
            # ====================================================

            if not pause_event.is_set():
                print("\nHunt pausada.")
                await pause_event.wait()
                if stop_event.is_set():
                    break
                print("\nHunt retomada.")
                continue

            delay = random_main_delay()
            print(f"\nPróxima venda em {delay:.1f}s.")
            remaining = delay

            while remaining > 0:
                if stop_event.is_set() or not pause_event.is_set():
                    break
                if stats.force_action:
                    break
                    
                # ====================================================
                # AVISO DE PROGRESSO DE TASK (A CADA 120s)
                # ====================================================
                now = asyncio.get_running_loop().time()
                if now - stats.last_task_report >= 120:
                    stats.last_task_report = now
                    
                    # Checa o progresso na tela silenciosamente
                    task_data = await get_tracked_task_progress(tab)
                    if task_data and not task_data.get("finished"):
                        max_kills = task_data['max']
                        current_kills = task_data['current']
                        pct = (current_kills / max_kills * 100) if max_kills > 0 else 0
                        
                        prog_msg = f"🎯 *Task em Andamento:* {task_data['name']}\nProgresso: {pct:.1f}% ({current_kills}/{max_kills})"
                        print(f"\n{prog_msg.replace('*', '')}")
                        
                        if on_message and get_setting("notify_tasks", True):
                            try:
                                await on_message(prog_msg)
                            except Exception as e:
                                print(f"Erro ao enviar aviso de Task: {e}")

                    # Checa o progresso do Passe de Batalha silenciosamente
                    bp_data = await get_tracked_battlepass_progress(tab)
                    if bp_data and not bp_data.get("finished"):
                        max_kills = bp_data['max']
                        current_kills = bp_data['current']
                        pct = (current_kills / max_kills * 100) if max_kills > 0 else 0

                        bp_msg = f"🎟️ *Passe de Batalha:* {bp_data['hunt_name']}\nProgresso: {pct:.1f}% ({current_kills}/{max_kills})"
                        print(f"\n{bp_msg.replace('*', '')}")

                        if on_message and get_setting("notify_tasks", True):
                            try:
                                await on_message(bp_msg)
                            except Exception as e:
                                print(f"Erro ao enviar aviso de Passe: {e}")
                # ====================================================

                sleep_time = min(1, remaining)
                await asyncio.sleep(sleep_time)
                remaining -= sleep_time

            if stop_event.is_set() or stats.force_action:
                continue

            if not pause_event.is_set():
                continue

            # ====================================================
            # VERIFICAR CODEX ANTES DA VENDA
            # ====================================================
            if not stop_event.is_set() and pause_event.is_set() and not stats.force_action:
                current_hunt = await get_current_hunt(tab)
                if current_hunt and current_hunt != "Hunt Desconhecida":
                    delivered, progress = await process_codex_routine(tab, current_hunt, on_message)
                    stats.codex_progress = progress

            success = await execute_sale(
                tab,
                stats,
                stop_event=stop_event,
                on_message=on_message,
                bot=bot,
            )

            if not success and not stop_event.is_set() and pause_event.is_set() and not stats.force_action:
                print("\nA venda não foi concluída.")
                retry_delay = random_retry_delay()
                print(f"Nova tentativa em {retry_delay:.1f}s.")
                remaining = retry_delay

                while remaining > 0:
                    if stop_event.is_set() or not pause_event.is_set():
                        break
                    if stats.force_action:
                        break
                    await asyncio.sleep(min(1, remaining))
                    remaining -= min(1, remaining)

                continue 

            # ====================================================
            # VERIFICAR STAMINA APÓS A VENDA
            # ====================================================
            if not stop_event.is_set() and pause_event.is_set():
                hud_data = await get_hud_data(tab)
                stamina_str = hud_data.get("stamina_pct", "0%")
                stamina_val = parse_clean_int(stamina_str)
                
                stamina_limit = get_setting("stamina_treino", IR_PARA_TREINO_ONLINE)
                if 0 < stamina_val <= stamina_limit:
                    current_hunt = await resolve_target_hunt(tab, stats)
                        
                    msg = f"🔋 *Stamina Crítica* ({stamina_val}%).\n\n⏸️ Pausando a hunt atual ({current_hunt}) e tentando ir para a Casa..."
                    print(msg.replace('*', ''))
                    if on_message:
                        await on_message(f"⚠️ {msg}")
                        
                    house_success = await manage_house_training(tab, stop_event, pause_event, on_message, current_hunt, silent_fail=True, bot=bot)
                    
                    if not house_success:
                        if on_message:
                            await on_message("❌ Casa indisponível. Redirecionando para o Treino Online padrão...")
                        await manage_training(tab, stop_event, pause_event, on_message, current_hunt, bot=bot)

            # ====================================================
            # VERIFICAR SE A TASK DA GUILDA FOI FINALIZADA
            # ====================================================
            if not stop_event.is_set() and pause_event.is_set():
                task_data = await get_tracked_task_progress(tab)
                
                if task_data and task_data.get("finished"):
                    msg = f"✅ *Task Finalizada!* ({task_data['name']})\nIndo até a Guilda entregar e buscar uma nova..."
                    print(msg.replace('*', ''))
                    
                    if on_message:
                        await on_message(msg)
                        
                    await process_guild_tasks(tab, on_message)

            # ====================================================
            # VERIFICAR SE O PASSE DE BATALHA FOI FINALIZADO
            # ====================================================
            if not stop_event.is_set() and pause_event.is_set():
                bp_data = await get_tracked_battlepass_progress(tab)

                if bp_data and bp_data.get("finished"):
                    msg = f"✅ *Missão do Passe Finalizada!* ({bp_data['hunt_name']})\nIndo até o Passe entregar e verificar as próximas..."
                    print(msg.replace('*', ''))

                    if on_message:
                        await on_message(msg)

                    try:
                        success, bp_msg = await process_battlepass(tab, on_message)
                        if bp_msg in ["finalizado", "nenhuma_nova"]:
                            target_hunt = stats.default_hunt or DEFAULT_HUNT
                            await change_hunt(tab, target_hunt)
                            if on_message:
                                await on_message(f"✅ Missões do Passe de hoje concluídas!\nRetornando para a hunt padrão: *{target_hunt}*")
                    except Exception as e:
                        print(f"Erro ao processar passe no loop de vendas: {e}")

    except asyncio.CancelledError:
        print("Task da Hunt cancelada.")
        raise
    finally:
        print("\nHunt encerrada.")