import json
from pathlib import Path
from baiaidle.config import PROJECT_ROOT

SETTINGS_FILE = PROJECT_ROOT / "config_user.json"

DEFAULT_SETTINGS = {
    "stamina_treino": 20,       # Ir para o treino quando stamina <= 20%
    "stamina_retorno": 100,     # Voltar para hunt quando stamina >= 100%
    "min_tier_stash": 4,        # Tier mínimo para guardar item no baú
    "watchdog_minutes": 10,     # Tempo sem atividade para o watchdog reiniciar (min)
    "notify_sales": True,       # Notificar cada venda no Telegram
    "notify_tasks": True,       # Notificar progresso de tasks a cada 120s
    "auto_missions_after_boss": True,  # Executar Passe e Tasks da Guilda automaticamente após AutoBoss
    "auto_tree_enabled": True,         # Distribuir pontos da árvore automaticamente ao subir de nível
    "auto_halloween_invasion": True,   # Participar automaticamente da Invasão de Halloween nos horários marcados
    "codex_focus_enabled": False,      # Focar automaticamente nas hunts do atributo selecionado no Codex
    "codex_focus_attribute": "critDmg",# Atributo alvo do Codex (ex: critDmg, atkPct, spellDmgPct)
    "codex_focus_hunt": None,          # Hunt atual sendo focada pelo Codex
    "default_hunt": "Infernal Demon",  # Hunt padrão de segurança pós-treino e término do Codex
}

_cached_settings = None


def load_settings() -> dict:
    """Carrega as configurações do arquivo JSON ou retorna os valores padrão."""
    global _cached_settings
    settings = dict(DEFAULT_SETTINGS)

    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    settings.update(data)
        except Exception as e:
            print(f"[Settings] Aviso ao carregar {SETTINGS_FILE}: {e}")

    _cached_settings = settings
    return settings


def save_settings(settings: dict) -> bool:
    """Salva as configurações no arquivo JSON."""
    global _cached_settings
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        _cached_settings = settings
        return True
    except Exception as e:
        print(f"[Settings] Erro ao salvar {SETTINGS_FILE}: {e}")
        return False


def get_setting(key: str, default=None):
    """Obtém um valor de configuração."""
    global _cached_settings
    if _cached_settings is None:
        load_settings()
    return _cached_settings.get(key, default if default is not None else DEFAULT_SETTINGS.get(key))


def set_setting(key: str, value) -> dict:
    """Altera uma configuração e salva em disco."""
    settings = load_settings()
    settings[key] = value
    save_settings(settings)
    return settings
