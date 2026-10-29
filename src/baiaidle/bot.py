import asyncio
import uuid

from baiaidle.config import (
    BAIAKIDLE_LOGIN,
    BAIAKIDLE_PASSWORD,
    BAIAKIDLE_URL,
)

from baiaidle.browser import (
    create_browser,
    start_virtual_display,
    stop_virtual_display,
)
from baiaidle.login import login
from baiaidle.actions import validate_sale, get_party_info, extract_member_level
from baiaidle.hunts import get_current_hunt
from baiaidle.sell import run_sell, HuntStats, is_training_location
from baiaidle.recovery import (
    init_session_tracker,
    dismiss_welcome_and_popups,
    monitor_page_recovery,
    ensure_page_session,
)



class GameBot:

    def __init__(self):

        self.browser = None
        self.tab = None
        self.stop_event = asyncio.Event()
        self.hunt_pause_event = asyncio.Event()
        self.hunt_task = None
        
        # Tarefa em segundo plano para vigiar o HP
        self.party_monitor_task = None
        
        # Tarefa em segundo plano para vigiar o Cloudflare
        self.cloudflare_monitor_task = None

        # Tarefa em segundo plano para vigiar refresh da página e telas de boas-vindas
        self.page_monitor_task = None
        self.session_token = str(uuid.uuid4())[:8]
        self.is_recovering = False
        self.recovery_lock = asyncio.Lock()
        self.last_activity_time = 0.0

        self.running = False
        self.starting = False
        self.on_message = None 
        
        # Instanciamos o objeto de estatísticas para ser acessado por qualquer comando
        self.hunt_stats = HuntStats()

        # Níveis iniciais da party (registrados na inicialização do bot)
        self.initial_party_levels = {}

        self.auto_boss_instance = None
        self.telegram_controller = None

    # ============================================================
    # VIGIA DE CLOUDFLARE SURPRESA (BACKGROUND)
    # ============================================================
    
    async def monitor_cloudflare(self):
        print("Shield Anti-Cloudflare iniciado em segundo plano.")
        
        js_check = """
        (() => {
            const el = document.querySelector('.mk-captcha');
            if (!el) return false;
            const rect = el.getBoundingClientRect();
            return (rect.width > 0 && rect.height > 0);
        })()
        """
        
        while not self.stop_event.is_set():
            if self.tab:
                try:
                    res = await self.tab.execute_script(js_check)
                    
                    is_ready = False
                    if isinstance(res, dict) and "result" in res:
                        is_ready = res["result"]["result"].get("value", False)
                        
                    if is_ready:
                        print("\n⚠️ [SHIELD] Cloudflare surpresa detectado! Interceptando...")
                        element = await self.tab.find(xpath='//*[contains(@class, "mk-captcha")]', timeout=3)
                        if element:
                            await element.click(humanize=True)
                            print("✅ [SHIELD] Cloudflare resolvido. O script vai refazer a ação anulada automaticamente.")
                            await asyncio.sleep(3) # Tempo para a caixinha sumir da tela
                except Exception:
                    pass
            
            # Checa a cada 1 segundo (picotado em 0.5s para parar rápido no /stop)
            for _ in range(2):
                if self.stop_event.is_set():
                    break
                await asyncio.sleep(0.5)

    # ============================================================
    # VIGIA DE HP DA PARTY (BACKGROUND)
    # ============================================================
    
    async def monitor_party_health(self):
        
        print("Monitor de Party iniciado.")
        last_alerted = set()
        
        while not self.stop_event.is_set():
            
            # Executa a checagem independente do bot estar pausado (útil para Autoboss)
            if self.tab:
                try:
                    party_data = await get_party_info(self.tab)
                    
                    if party_data:
                        for member in party_data:
                            hp_str = member.get("hp", "")
                            
                            # Formato esperado: "10.347/10.391" ou "0/10.391"
                            if hp_str and "/" in hp_str:
                                current_hp_str = hp_str.split('/')[0].replace('.', '').strip()
                                
                                try:
                                    current_hp = int(current_hp_str)
                                    name = member.get("name", "Desconhecido")
                                    role = member.get("role", "Membro")
                                    
                                    if current_hp == 0:
                                        
                                        # Evita mandar spam caso ele permaneça morto
                                        if name not in last_alerted:
                                            msg = f"💀 *ALERTA DE MORTE!*\nO personagem *{name}* ({role}) morreu!"
                                            print(f"ALERTA: {name} morreu!")
                                            
                                            if self.on_message:
                                                try:
                                                    result = self.on_message(msg)
                                                    if asyncio.iscoroutine(result):
                                                        await result
                                                except Exception as e:
                                                    print(f"Erro ao enviar alerta: {e}")
                                                    
                                            last_alerted.add(name)
                                            
                                    else:
                                        
                                        # Se a vida subiu de 0 (ressuscitou), libera para futuros alertas
                                        if name in last_alerted:
                                            last_alerted.remove(name)
                                            
                                except ValueError:
                                    pass
                                    
                except Exception as e:
                    pass
            
            # Dorme por 10 segundos (picotados de 1 em 1 para parar rápido no /stop)
            for _ in range(10):
                if self.stop_event.is_set():
                    break
                await asyncio.sleep(1)

    # ============================================================
    # REGISTRO DE NÍVEL INICIAL DA PARTY
    # ============================================================

    async def record_initial_party(self):
        """
        Registra os níveis iniciais de cada membro da party assim que o bot inicia.
        """
        self.initial_party_levels = {}
        for attempt in range(5):
            if not self.tab:
                break
            try:
                party_data = await get_party_info(self.tab)
                if party_data:
                    for member in party_data:
                        name = member.get("name")
                        role = member.get("role")
                        lvl = extract_member_level(member)
                        if lvl is not None:
                            if name:
                                self.initial_party_levels[name] = lvl
                            if role:
                                self.initial_party_levels[f"role_{role}"] = lvl
                    if self.initial_party_levels:
                        print(f"✅ Níveis iniciais da party registrados: {self.initial_party_levels}")
                        break
            except Exception as e:
                print(f"Aviso ao registrar níveis iniciais da party (tentativa {attempt + 1}): {e}")
            await asyncio.sleep(1)

    # ============================================================
    # START
    # ============================================================

    async def start(self):

        if self.running:

            return True, "Bot já está rodando."

        if self.starting:

            return False, "Bot já está iniciando."

        self.starting = True

        try:

            if not BAIAKIDLE_LOGIN:

                raise RuntimeError(
                    "BAIAKIDLE_LOGIN não configurado."
                )

            if not BAIAKIDLE_PASSWORD:

                raise RuntimeError(
                    "BAIAKIDLE_PASSWORD não configurado."
                )

            print()
            print(
                "========================================"
            )

            print(
                "INICIANDO BOT"
            )

            print(
                "========================================"
            )

            # ====================================================
            # DISPLAY VIRTUAL (Xvfb, apenas Linux)
            # ====================================================

            start_virtual_display()

            # ====================================================
            # BROWSER
            # ====================================================

            self.browser = create_browser()

            await self.browser.start()

            print(
                "Navegador iniciado."
            )

            # ====================================================
            # TAB
            # ====================================================

            self.tab = await self.browser.new_tab()

            url = (
                BAIAKIDLE_URL.rstrip("/")
                + "/jogar"
            )

            print(
                "Abrindo:",
                url,
            )

            await self.tab.go_to(
                url
            )

            print("Ativando bypass automático do Cloudflare em segundo plano...")
            await self.tab.enable_auto_solve_cloudflare_captcha()

            await asyncio.sleep(3)

            # ====================================================
            # LOGIN
            # ====================================================

            print(
                "Iniciando login..."
            )

            success = await login(
                self.tab,
                BAIAKIDLE_LOGIN,
                BAIAKIDLE_PASSWORD,
            )

            if not success:

                raise RuntimeError(
                    "Login falhou."
                )

            print(
                "Login realizado."
            )

            # ====================================================
            # LIGA O SHIELD ANTES DA VALIDAÇÃO
            # ====================================================
            self.cloudflare_monitor_task = asyncio.create_task(
                self.monitor_cloudflare()
            )

            # ====================================================
            # DETECÇÃO INICIAL DE LOCALIZAÇÃO (TREINO / HUNT)
            # ====================================================
            current_loc = await get_current_hunt(self.tab, timeout=3.0)
            is_training, train_type = is_training_location(current_loc)

            if is_training:
                mode_desc = "Casa (Dummies)" if train_type == "casa" else "Treino Online"
                print(f"🧘‍♂️ Personagem detectado já em Treino: {current_loc} ({mode_desc}). Pulando validação de venda...")
            else:
                # ====================================================
                # VALIDAÇÃO DE SESSÃO COM VENDA DE ITENS
                # ====================================================
                print("Validando sessão...")
                validated = await validate_sale(self.tab)
                if not validated:
                    raise RuntimeError("Validação da sessão falhou.")
                print("Sessão validada.")

            # ====================================================
            # ESTADO
            # ====================================================
            self.stop_event.clear()
            self.hunt_pause_event.set()
            self.running = True

            # Zera as estatísticas ao iniciar
            self.hunt_stats.reset()
            if is_training:
                self.hunt_stats.is_in_training = True
                self.hunt_stats.training_type = train_type

            # ====================================================
            # TASKS DE BACKGROUND (HUNT & MONITORES)
            # ====================================================
            self.hunt_task = asyncio.create_task(
                run_sell(
                    self.tab,
                    self.stop_event,
                    self.hunt_pause_event,
                    self.hunt_stats, # Passa as estatísticas
                    self.on_message,
                    bot=self,
                )
            )
            
            # ====================================================
            # RASTREADOR DE SESSÃO & LIMPEZA DE BOAS-VINDAS
            # ====================================================
            self.touch_activity()
            await init_session_tracker(self.tab, self.session_token)
            await dismiss_welcome_and_popups(self.tab)

            # Inicia o vigia de HP paralelamente
            self.party_monitor_task = asyncio.create_task(
                self.monitor_party_health()
            )

            # Inicia o vigia de refresh da página e popups em segundo plano
            self.page_monitor_task = asyncio.create_task(
                monitor_page_recovery(self)
            )

            # ====================================================
            # REGISTRO DE NÍVEIS INICIAIS DA PARTY
            # ====================================================
            await self.record_initial_party()

            if is_training:
                mode_desc = "Casa (Dummies)" if train_type == "casa" else "Treino Online"
                msg_start = f"Modo Treino detectado! Personagem já está em: *{current_loc}* ({mode_desc})."
                print(f"🧘‍♂️ {msg_start.replace('*', '')}")
                print("BOT ONLINE.")
                return True, msg_start

            print("Hunt iniciada.")
            print("BOT ONLINE.")
            return True, "Hunt iniciada com sucesso."

        except Exception:

            await self.stop()

            raise

        finally:

            self.starting = False

    # ============================================================
    # STOP
    # ============================================================

    async def stop(self):

        print()
        print(
            "Solicitando parada do bot..."
        )

        self.stop_event.set()

        self.hunt_pause_event.set()

        # ========================================================
        # ENCERRAR HUNT
        # ========================================================

        if self.hunt_task:

            if not self.hunt_task.done():

                self.hunt_task.cancel()

                try:

                    await self.hunt_task

                except asyncio.CancelledError:

                    pass

                except Exception as e:

                    print(
                        "Erro ao encerrar Hunt:",
                        e,
                    )

            self.hunt_task = None
            
        # ========================================================
        # ENCERRAR VIGIA DE HP
        # ========================================================

        if self.party_monitor_task:
            
            if not self.party_monitor_task.done():
                
                self.party_monitor_task.cancel()
                
                try:
                    await self.party_monitor_task
                except asyncio.CancelledError:
                    pass
                    
            self.party_monitor_task = None

        # ========================================================
        # ENCERRAR VIGIA DE CLOUDFLARE
        # ========================================================

        if self.cloudflare_monitor_task:
            
            if not self.cloudflare_monitor_task.done():
                
                self.cloudflare_monitor_task.cancel()
                
                try:
                    await self.cloudflare_monitor_task
                except asyncio.CancelledError:
                    pass
                    
            self.cloudflare_monitor_task = None

        # ========================================================
        # ENCERRAR VIGIA DE REFRESH / BOAS-VINDAS
        # ========================================================

        if self.page_monitor_task:
            if not self.page_monitor_task.done():
                self.page_monitor_task.cancel()
                try:
                    await self.page_monitor_task
                except asyncio.CancelledError:
                    pass
            self.page_monitor_task = None

        # ========================================================
        # ENCERRAR AGENDAMENTO DA DAILY REWARD
        # ========================================================
        try:
            from baiaidle.daily import cancel_daily_schedule
            cancel_daily_schedule()
        except Exception:
            pass

        # ========================================================
        # TAB
        # ========================================================

        if self.tab:

            try:
                print("Desativando bypass automático do Cloudflare...")
                await self.tab.disable_auto_solve_cloudflare_captcha()
                await self.tab.close()

            except Exception:
                pass

            self.tab = None

        # ========================================================
        # BROWSER
        # ========================================================

        if self.browser:

            try:

                await self.browser.stop()

            except Exception:
                pass

            self.browser = None

        # ========================================================
        # DISPLAY VIRTUAL (Xvfb)
        # ========================================================

        stop_virtual_display()

        self.running = False
        self.initial_party_levels = {}

        print(
            "BOT OFFLINE."
        )

    # ============================================================
    # PAUSAR HUNT
    # ============================================================

    def pause_hunt(self):
        self.touch_activity()
        self.hunt_pause_event.clear()

    # ============================================================
    def resume_hunt(self):
        self.touch_activity()
        self.hunt_pause_event.set()
        self.ensure_hunt_running()

    def ensure_hunt_running(self, force_restart: bool = False):
        if not self.running or not self.tab:
            return
        if force_restart and self.hunt_task and not self.hunt_task.done():
            print("[Bot] Cancelando task de vendas anterior travada...")
            self.hunt_task.cancel()
            self.hunt_task = None

        if self.hunt_task is None or self.hunt_task.done():
            if self.hunt_task and self.hunt_task.done() and not self.hunt_task.cancelled():
                try:
                    exc = self.hunt_task.exception()
                    if exc:
                        print(f"[Bot] Exceção anterior na hunt_task: {exc}")
                except Exception:
                    pass
            print("[Bot] Reiniciando task de vendas/hunt (hunt_task estava inativa)...")
            self.hunt_pause_event.set()
            self.hunt_task = asyncio.create_task(
                run_sell(
                    self.tab,
                    self.stop_event,
                    self.hunt_pause_event,
                    self.hunt_stats,
                    self.on_message,
                    bot=self,
                )
            )

    # ============================================================
    # ESTADO
    # ============================================================

    def is_running(self) -> bool:

        return self.running

    def is_hunt_running(self) -> bool:

        return (
            self.running
            and self.hunt_pause_event.is_set()
            and self.hunt_task is not None
            and not self.hunt_task.done()
        )

    # ============================================================
    # RECUPERAÇÃO MANUAL DE SESSÃO / FECHAR POPUPS
    # ============================================================

    async def trigger_recovery(self) -> tuple[bool, str]:
        """
        Dispara manualmente a verificação de refresh, reconexão de sessão
        e fechamento de telas de boas-vindas / comunicados.
        """
        return await ensure_page_session(self, on_message=self.on_message)

    def touch_activity(self):
        """Atualiza o timestamp de atividade para o Watchdog Antitravamento."""
        import time
        self.last_activity_time = time.time()