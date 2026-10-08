import asyncio
from datetime import datetime, timedelta, time, timezone
import json
from pathlib import Path

from baiaidle.config import PROJECT_ROOT
from baiaidle.autoboss import AutoBoss, get_boss_list

PRESET_FILE = PROJECT_ROOT / "autoboss_preset.json"

_autoboss_scheduler_task: asyncio.Task | None = None


def load_autoboss_preset() -> dict:
    """Carrega as configurações salvas da lista predefinida e do agendador noturno."""
    default_config = {
        "enabled": False,
        "boss_indices": [],
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
                return {
                    "enabled": bool(data.get("enabled", False)),
                    "boss_indices": indices,
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

    controller.auto_boss_instance = AutoBoss(controller.bot.tab)

    async def send_msg(text):
        await controller.send_hunt_msg(text)

    controller.auto_boss_instance.on_message = send_msg
    controller.auto_boss_instance.on_finished = controller.autoboss_finished

    try:
        charges, bosses = await get_boss_list(controller.bot.tab)
        boss_by_index = {b.index: b for b in bosses}

        # Filtra apenas bosses que estão vivos / disponíveis
        valid_indices = [idx for idx in indices if idx in boss_by_index]
        skipped = [idx for idx in indices if idx not in boss_by_index]

        if not valid_indices:
            msg = f"⚠️ *AutoBoss Noturno:* Nenhum dos bosses da lista predefinida (`{indices}`) está disponível no momento (Cargas: {charges})."
            controller.bot.resume_hunt()
            controller.auto_boss_instance = None
            await controller.send_hunt_msg(msg)
            return

        if skipped:
            await controller.send_hunt_msg(
                f"ℹ️ *Aviso:* Bosses `{skipped}` não estão disponíveis no momento. Executando os disponíveis: `{valid_indices}` (Cargas: {charges})."
            )

        success, message = await controller.auto_boss_instance.start(valid_indices)
        if not success:
            controller.bot.resume_hunt()
            controller.auto_boss_instance = None
            await controller.send_hunt_msg(f"❌ Falha ao iniciar AutoBoss automático: {message}")
        else:
            preset = load_autoboss_preset()
            preset["last_run_date"] = str(datetime.now().date())
            save_autoboss_preset(preset)

    except Exception as e:
        controller.bot.resume_hunt()
        controller.auto_boss_instance = None
        await controller.send_hunt_msg(f"❌ Erro durante AutoBoss noturno: {e}")
