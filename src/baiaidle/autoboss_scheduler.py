import asyncio
from datetime import datetime, timedelta, time, timezone
import json
from pathlib import Path

from baiaidle.config import PROJECT_ROOT
from baiaidle.autoboss import AutoBoss, get_boss_list

PRESET_FILE = PROJECT_ROOT / "autoboss_preset.json"

_autoboss_scheduler_task: asyncio.Task | None = None


def normalize_difficulty(val) -> int | str | None:
    """Normaliza o valor de dificuldade (número, 'max', 'min' ou None para padrão)."""
    if val is None:
        return None
    val_str = str(val).strip().lower()
    if val_str in ("", "none", "padrao", "padrão", "default", "null", "reset"):
        return None
    if val_str in ("max", "maior"):
        return "max"
    if val_str in ("min", "menor"):
        return "min"
    try:
        num = int(val_str)
        return num if num > 0 else None
    except ValueError:
        return None


def load_autoboss_preset() -> dict:
    """Carrega as configurações salvas da lista predefinida, dificuldades e do agendador noturno."""
    default_config = {
        "enabled": False,
        "boss_indices": [],
        "boss_difficulties": {},
        "default_difficulty": None,
        "last_run_date": None,
    }
    if not PRESET_FILE.exists():
        return default_config

    try:
        with open(PRESET_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                indices = []
                for x in data.get("boss_indices", []):
                    try:
                        indices.append(int(x))
                    except (ValueError, TypeError):
                        pass

                raw_diffs = data.get("boss_difficulties", {})
                diffs = {}
                if isinstance(raw_diffs, dict):
                    for k, v in raw_diffs.items():
                        norm_v = normalize_difficulty(v)
                        if norm_v is not None:
                            diffs[str(k).strip()] = norm_v

                return {
                    "enabled": bool(data.get("enabled", False)),
                    "boss_indices": indices,
                    "boss_difficulties": diffs,
                    "default_difficulty": normalize_difficulty(data.get("default_difficulty")),
                    "last_run_date": data.get("last_run_date"),
                }
    except Exception as e:
        print(f"[AutoBoss Scheduler] Erro ao carregar {PRESET_FILE}: {e}")

    return default_config


def save_autoboss_preset(data: dict) -> bool:
    """Salva as configurações da lista predefinida e agendador em arquivo JSON."""
    try:
        with open(PRESET_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[AutoBoss Scheduler] Erro ao salvar {PRESET_FILE}: {e}")
        return False


def set_preset_indices(indices: list[int]) -> dict:
    """Atualiza a lista predefinida de bosses no arquivo de configuração."""
    preset = load_autoboss_preset()
    preset["boss_indices"] = indices
    save_autoboss_preset(preset)
    return preset


def set_preset_enabled(enabled: bool) -> dict:
    """Liga ou desliga o agendamento automático das 00h."""
    preset = load_autoboss_preset()
    preset["enabled"] = bool(enabled)
    save_autoboss_preset(preset)
    return preset


def get_boss_difficulty(boss_name: str | None = None, boss_index: int | None = None) -> int | str | None:
    """
    Retorna a dificuldade configurada para o boss (ou None para usar a que vier por padrão).
    Prioridade:
    1. Nome exato do boss (ex: 'Mimar Haffar')
    2. Nome case-insensitive
    3. Índice do boss (ex: '98' ou 98)
    4. Dificuldade padrão global (default_difficulty)
    5. None (mantém o valor original que vier na interface)
    """
    preset = load_autoboss_preset()
    diffs = preset.get("boss_difficulties", {})

    if boss_name:
        if boss_name in diffs:
            return diffs[boss_name]
        b_lower = boss_name.strip().lower()
        for k, v in diffs.items():
            if k.strip().lower() == b_lower:
                return v

    if boss_index is not None:
        idx_str = str(boss_index)
        if idx_str in diffs:
            return diffs[idx_str]

    return preset.get("default_difficulty")


def set_boss_difficulty(boss_key: str | int, difficulty: int | str | None) -> dict:
    """
    Define a dificuldade desejada para um boss (por nome ou índice).
    Se difficulty for None/'padrao'/'reset', remove a configuração específica para usar a que vier.
    """
    preset = load_autoboss_preset()
    diffs = preset.get("boss_difficulties", {})
    norm = normalize_difficulty(difficulty)
    key_str = str(boss_key).strip()

    if norm is None:
        diffs.pop(key_str, None)
        to_del = [k for k in diffs if k.strip().lower() == key_str.lower()]
        for k in to_del:
            diffs.pop(k, None)
    else:
        diffs[key_str] = norm

    preset["boss_difficulties"] = diffs
    save_autoboss_preset(preset)
    return preset


def set_default_boss_difficulty(difficulty: int | str | None) -> dict:
    """Define a dificuldade padrão para todos os bosses que não possuírem regra específica."""
    preset = load_autoboss_preset()
    preset["default_difficulty"] = normalize_difficulty(difficulty)
    save_autoboss_preset(preset)
    return preset


def clear_boss_difficulties() -> dict:
    """Limpa todas as configurações de dificuldade de bosses."""
    preset = load_autoboss_preset()
    preset["boss_difficulties"] = {}
    preset["default_difficulty"] = None
    save_autoboss_preset(preset)
    return preset


BRT = timezone(timedelta(hours=-3))


def get_now_brasilia() -> datetime:
    """Retorna o horário atual oficial de Brasília (UTC-3)."""
    return datetime.now(BRT)


def seconds_until_midnight(margin_seconds: int = 60) -> int:
    """
    Retorna o número de segundos até a próxima meia-noite (00:00)
    no Horário Oficial de Brasília (UTC-3).
    Adiciona margem de segurança (padrão 60s) para o servidor do jogo virar a data.
    """
    now = get_now_brasilia()
    tomorrow = now.date() + timedelta(days=1)
    midnight = datetime.combine(tomorrow, time(0, 0), tzinfo=BRT) + timedelta(seconds=margin_seconds)
    delta = (midnight - now).total_seconds()
    return max(5, int(delta))


def format_time_until_midnight(margin_seconds: int = 60) -> str:
    """Formata o tempo restante até a próxima meia-noite (ex: '4h e 12m')."""
    secs = seconds_until_midnight(margin_seconds)
    hours = secs // 3600
    minutes = (secs % 3600) // 60
    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if not parts:
        return "menos de 1 minuto"
    return " e ".join(parts)


def start_autoboss_scheduler(controller):
    """Inicia a tarefa em segundo plano que monitora a virada das 00h."""
    global _autoboss_scheduler_task
    stop_autoboss_scheduler()
    _autoboss_scheduler_task = asyncio.create_task(_scheduler_loop(controller))
    print("[AutoBoss Scheduler] Agendador de virada das 00h iniciado em segundo plano.")
    return _autoboss_scheduler_task


def stop_autoboss_scheduler():
    """Para o agendador em segundo plano."""
    global _autoboss_scheduler_task
    if _autoboss_scheduler_task and not _autoboss_scheduler_task.done():
        _autoboss_scheduler_task.cancel()
        print("[AutoBoss Scheduler] Agendador cancelado.")
    _autoboss_scheduler_task = None


async def _scheduler_loop(controller):
    """Loop principal que espera a meia-noite e dispara o AutoBoss."""
    try:
        while True:
            delay = seconds_until_midnight(margin_seconds=60)
            print(f"⏰ [AutoBoss Scheduler] Proximo reset de cargas (00h) em {delay}s ({format_time_until_midnight(margin_seconds=60)}).")

            elapsed = 0
            while elapsed < delay:
                step = min(5, delay - elapsed)
                await asyncio.sleep(step)
                elapsed += step

            # Meia-noite atingida!
            preset = load_autoboss_preset()

            if not preset.get("enabled", False):
                print("⏰ [AutoBoss Scheduler] 00h atingida, mas agendamento automatico esta DESLIGADO.")
                await asyncio.sleep(60)
                continue

            indices = preset.get("boss_indices", [])
            if not indices:
                print("⏰ [AutoBoss Scheduler] 00h atingida, mas nenhuma lista predefinida foi configurada.")
                if controller and hasattr(controller, "send_hunt_msg"):
                    await controller.send_hunt_msg(
                        "⚠️ *Cargas de Boss renovadas (00h)!*\n"
                        "Porém nenhuma lista predefinida de bosses está configurada.\n"
                        "Use `/setautoboss 1,2,3` para configurar sua lista favorita."
                    )
                await asyncio.sleep(60)
                continue

            if not controller.bot or not controller.bot.is_running():
                print("⏰ [AutoBoss Scheduler] 00h atingida, mas o GameBot nao esta rodando.")
                await asyncio.sleep(60)
                continue

            # Executa com segurança
            await _run_midnight_autoboss(controller, indices)
            await asyncio.sleep(60)  # Garante que não dispare duas vezes no mesmo minuto

    except asyncio.CancelledError:
        print("[AutoBoss Scheduler] Loop do agendador finalizado.")
    except Exception as e:
        print(f"[AutoBoss Scheduler] Erro inesperado no loop: {e}")


async def _run_midnight_autoboss(controller, indices: list[int]):
    """Executa a rotina do AutoBoss à meia-noite com lock e mensagens."""
    indices_str = ", ".join(map(str, indices))

    if controller.auto_boss_instance and controller.auto_boss_instance.state.running:
        print("[AutoBoss Scheduler] Ja existe um AutoBoss em execucao.")
        return

    await controller.send_hunt_msg(
        f"🌙 *Meia-noite detectada! Cargas de Boss renovadas.*\n"
        f"Iniciando AutoBoss na lista predefinida: `[{indices_str}]`..."
    )

    lock = getattr(controller, "action_lock", None)
    if lock:
        async with lock:
            await _start_boss_battle(controller, indices)
    else:
        await _start_boss_battle(controller, indices)


async def _start_boss_battle(controller, indices: list[int]):
    controller.bot.pause_hunt()
    await asyncio.sleep(1.5)

    preset_data = load_autoboss_preset()
    diffs = preset_data.get("boss_difficulties", {})
    controller.auto_boss_instance = AutoBoss(controller.bot.tab, bot=controller.bot, difficulties=diffs)
    if controller.bot:
        controller.bot.auto_boss_instance = controller.auto_boss_instance

    async def send_msg(text):
        await controller.send_hunt_msg(text)

    controller.auto_boss_instance.on_message = send_msg
    controller.auto_boss_instance.on_finished = controller.autoboss_finished

    try:
        success, message = await controller.auto_boss_instance.start(indices)
        if not success:
            if controller.bot:
                controller.bot.auto_boss_instance = None
            controller.bot.resume_hunt()
            controller.auto_boss_instance = None
            await controller.send_hunt_msg(f"⚠️ *AutoBoss Noturno:* {message}")
        else:
            preset = load_autoboss_preset()
            preset["last_run_date"] = str(datetime.now().date())
            save_autoboss_preset(preset)
            await controller.send_hunt_msg(f"{message}\n\n🏹 Hunt pausada.")

    except Exception as e:
        if controller.bot:
            controller.bot.auto_boss_instance = None
        controller.bot.resume_hunt()
        controller.auto_boss_instance = None
        await controller.send_hunt_msg(f"❌ Erro durante AutoBoss noturno: {e}")
