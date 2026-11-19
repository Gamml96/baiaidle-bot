# Relatório de Análise do Repositório baiaidle-bot

**Data:** 2025-11-19  
**Diretório analisado:** `C:\Users\Usuario\Documents\baiaidle-bot\src\baiaidle\`  
**Arquivos:** 23 módulos Python (.py)

---

## 🔴 CRÍTICO (Erros de Runtime / Imports Quebrados)

### 1. `DEFAULT_HUNT` não importado em `telegram_bot.py`
**Arquivo:** `telegram_bot.py`  
**Linhas:** 440, 1941, 3359  
**Problema:** A constante `DEFAULT_HUNT` é definida em `sell.py:64` mas **não é importada** em `telegram_bot.py`. O código referencia `DEFAULT_HUNT` em três locais:
- Linha 440: `else DEFAULT_HUNT` (fallback no `run_auto_missions`)
- Linha 1941: `"Infernal Demon"` hardcoded em vez de usar a constante
- Linha 3359: fallback em `get_system_overview`

**Impacto:** `NameError` em runtime quando essas funções são chamadas.

---

## 🟠 WARNING (Funções Mortas / Código Morto)

### actions.py
| Função | Linha | Status |
|--------|-------|--------|
| `wait_for_sale_processed` | 1016 | **NUNCA CHAMADA** em nenhum arquivo |
| `wait_for_cloudflare` | 362 | Importado em `sell.py:12` mas **comentado** em `sell.py:670` |
| `print_sell_button_state` | 743 | Usada apenas internamente em `actions.py:924` |
| `sell_button_in_cooldown` | 795 | Usada apenas internamente em `actions.py:896` |
| `sell_button_available` | 833 | Usada apenas internamente em `actions.py:970` |

### autoboss.py
| Função | Linha | Status |
|--------|-------|--------|
| `find_boss_card` | 761 | **NUNCA CHAMADA** |
| `debug_fight_button` | 912 | Chamada apenas em contexto de debug (linha 2548), não em produção |
| `parse_boss_indices` | 750 | Wrapper interno, usado apenas em `autoboss.py:753` |

### battlepass.py
| Função | Linha | Status |
|--------|-------|--------|
| `get_battlepass_missions` | 82 | Usada internamente ✓ |
| `deliver_battlepass_mission` | 146 | Usada internamente ✓ |

### codex.py
| Função | Linha | Status |
|--------|-------|--------|
| `safe_print` | 33 | Usada internamente ✓ |
| `extract_hunt_from_codex_name` | 561 | Usada internamente ✓ |

### daily.py
| Função | Linha | Status |
|--------|-------|--------|
| `schedule_daily` | 402 | **Wrapper sem uso** - apenas chama `start_daily_schedule` |

### halloween.py
| Função | Linha | Status |
|--------|-------|--------|
| `exit_halloween_invasion_if_done` | 206 | Usada em `halloween.py:406` ✓ |
| `open_halloween_modal` | 226 | Usada em `halloween.py:324` ✓ |
| `close_halloween_modal` | 248 | Usada em `halloween.py:353,376` ✓ |

### hunts.py
| Função | Linha | Status |
|--------|-------|--------|
| `is_hunt_level_safe` | 109 | **NUNCA CHAMADA** em nenhum arquivo |

### overlays.py
| Função | Linha | Status |
|--------|-------|--------|
| `is_training_overlay` | 77 | **NUNCA CHAMADA** |
| `is_halloween_overlay` | 81 | **NUNCA CHAMADA** |
| `is_guild_task_overlay` | 85 | **NUNCA CHAMADA** |
| `wait_for_connection_restore` | 111 | Usada em `recovery.py` e `sell.py` ✓ |
| `wait_for_queue_exit` | 125 | Usada em `recovery.py` e `sell.py` ✓ |

### twitch.py
| Função | Linha | Status |
|--------|-------|--------|
| `status_is_counting` | 403 | **NUNCA CHAMADA** |
| `format_twitch_status` | 407 | Usada em `bot.py` e `telegram_bot.py` ✓ |
| `get_last_error` | 597 | Usada em `bot.py` e `telegram_bot.py` ✓ |
| `extract_login_from_preview` | 65 | Usada internamente em `get_twitch_lives` ✓ |
| `pick_live` | 79 | Usada em `choose_twitch_live` ✓ |

### config.py
| Função | Linha | Status |
|--------|-------|--------|
| `validate_config` | 138 | **NUNCA CHAMADA** |

### guild.py
Todas as funções são usadas internamente ✓

### expedition.py
| Função | Linha | Status |
|--------|-------|--------|
| `select_expedition_character` | 244 | Usada em `expedition.py:461` ✓, **importada mas não usada em `telegram_bot.py:83`** |

### tree.py
Todas as funções são usadas internamente ✓

### login.py
Todas as funções são usadas internamente ✓

### recovery.py
Todas as funções são usadas ✓

### sell.py
Todas as funções importadas são usadas ✓ (exceto `wait_for_cloudflare` comentado)

### bot.py
Todos os imports são usados ✓

---

## 🟡 INFO (Inconsistências / Importações Desnecessárias)

### telegram_bot.py - Imports não usados
| Import | Linha | Motivo |
|--------|-------|--------|
| `BotCommandScopeAllPrivateChats` | 11 | Nunca usado (apenas `BotCommandScopeDefault`) |
| `KeyboardButton` | 15 | Nunca usado (apenas `InlineKeyboardButton`) |
| `parse_boss_indices` | 36 | Importado mas **nunca usado** (usa `parse_boss_indices_and_difficulties`) |
| `select_expedition_character` | 83 | Importado mas **nunca usado em telegram_bot.py** |

### telegram_bot.py - Inconsistência de constante
| Problema | Linha | Detalhes |
|----------|-------|----------|
| `DEFAULT_HUNT` não importado | 440, 1941, 3359 | Causa `NameError` em runtime |
| Fallback hardcoded | 1941 | `"Infernal Demon"` em vez de `DEFAULT_HUNT` |

### sell.py - Import comentado
| Import | Linha | Detalhes |
|--------|-------|----------|
| `wait_for_cloudflare` | 12 | Importado de `actions` mas uso comentado em linha 670 |

---

## 📊 Resumo por Severidade

| Severidade | Quantidade | Detalhes |
|------------|------------|----------|
| **Crítico** | 1 | `DEFAULT_HUNT` não importado → `NameError` em runtime |
| **Warning** | 15 | Funções definidas mas nunca chamadas externamente |
| **Info** | 8 | Imports desnecessários, inconsistências de nomenclatura |

---

## ✅ Recomendações Prioritárias

1. **URGENTE:** Adicionar `from baiaidle.sell import DEFAULT_HUNT` em `telegram_bot.py` (linha ~98) e substituir o hardcoded `"Infernal Demon"` na linha 1941.

2. **LIMPAR:** Remover imports não usados em `telegram_bot.py`:
   - `BotCommandScopeAllPrivateChats` (linha 11)
   - `KeyboardButton` (linha 15)  
   - `parse_boss_indices` (linha 36)
   - `select_expedition_character` (linha 83)

3. **LIMPAR:** Remover `wait_for_cloudflare` do import em `sell.py:12` já que está comentado o uso.

4. **REVISAR:** Funções `is_hunt_level_safe` (hunts.py), `is_training_overlay`, `is_halloween_overlay`, `is_guild_task_overlay` (overlays.py), `status_is_counting` (twitch.py), `validate_config` (config.py) - avaliar se devem ser removidas ou se há planos de uso futuro.

5. **REVISAR:** `wait_for_sale_processed` (actions.py:1016) - função completa sem nenhum chamador.

---

## 📝 Notas Adicionais

- O código usa **pyrefly** para suprimir erros de import (`# pyrefly: ignore [missing-import]`) - isso mascara problemas reais de imports.
- Muitos módulos definem sua própria função `extract_execute_result` e `parse_json_result` - considerar centralizar em `actions.py` ou utilitário comum.
- O padrão de `async def` + JS inline é consistente em todo o projeto.