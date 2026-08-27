import asyncio

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
from baiaidle.actions import validate_sale, get_party_info
from baiaidle.sell import run_sell, HuntStats


class GameBot:

    def __init__(self):

        self.browser = None
        self.tab = None
        self.stop_event = asyncio.Event()
        self.hunt_pause_event = asyncio.Event()
        self.hunt_task = None
        
        self.party_monitor_task = None
        self.cloudflare_monitor_task = None # NOVO: Variável do Vigia

        self.running = False
        self.starting = False
        self.on_message = None 
        
        self.hunt_stats = HuntStats()

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
            if self.tab:
                try:
                    party_data = await get_party_info(self.tab)
                    
                    if party_data:
                        for member in party_data:
                            hp_str = member.get("hp", "")
                            
                            if hp_str and "/" in hp_str:
                                current_hp_str = hp_str.split('/')[0].replace('.', '').strip()
                                
                                try:
                                    current_hp = int(current_hp_str)
                                    name = member.get("name", "Desconhecido")
                                    role = member.get("role", "Membro")
                                    
                                    if current_hp == 0:
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
                                        if name in last_alerted:
                                            last_alerted.remove(name)
                                except ValueError:
                                    pass
                except Exception as e:
                    pass
            
            for _ in range(10):
                if self.stop_event.is_set():
                    break
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
            if not BAIAKIDLE_LOGIN or not BAIAKIDLE_PASSWORD:
                raise RuntimeError("Credenciais não configuradas no .env.")

            print("\n========================================\nINICIANDO BOT\n========================================")

            start_virtual_display()
            self.browser = create_browser()
            await self.browser.start()
            print("Navegador iniciado.")

            self.tab = await self.browser.new_tab()
            url = BAIAKIDLE_URL.rstrip("/") + "/jogar"
            
            print("Abrindo:", url)
            await self.tab.go_to(url)
            
            print("Ativando bypass automático do Cloudflare em segundo plano...")
            await self.tab.enable_auto_solve_cloudflare_captcha()
            await asyncio.sleep(3)

            print("Iniciando login...")
            success = await login(self.tab, BAIAKIDLE_LOGIN, BAIAKIDLE_PASSWORD)
            
            if not success:
                raise RuntimeError("Login falhou.")
            print("Login realizado.")

            print("Validando sessão...")
            validated = await validate_sale(self.tab)
            if not validated:
                raise RuntimeError("Validação da sessão falhou.")
            print("Sessão validada.")

            self.stop_event.clear()
            self.hunt_pause_event.set()
            self.running = True
            self.hunt_stats.reset()

            self.hunt_task = asyncio.create_task(
                run_sell(self.tab, self.stop_event, self.hunt_pause_event, self.hunt_stats, self.on_message)
            )
            
            self.party_monitor_task = asyncio.create_task(self.monitor_party_health())
            self.cloudflare_monitor_task = asyncio.create_task(self.monitor_cloudflare()) # NOVO: Iniciando Vigia

            print("Hunt iniciada.\nBOT ONLINE.")
            return True, "Bot iniciado com sucesso."

        except Exception:
            await self.stop()
            raise
        finally:
            self.starting = False

    # ============================================================
    # STOP
    # ============================================================

    async def stop(self):

        print("\nSolicitando parada do bot...")
        self.stop_event.set()
        self.hunt_pause_event.set()

        if self.hunt_task and not self.hunt_task.done():
            self.hunt_task.cancel()
            try:
                await self.hunt_task
            except asyncio.CancelledError:
                pass
        self.hunt_task = None
            
        if self.party_monitor_task and not self.party_monitor_task.done():
            self.party_monitor_task.cancel()
            try:
                await self.party_monitor_task
            except asyncio.CancelledError:
                pass
        self.party_monitor_task = None

        # NOVO: Parando Vigia
        if self.cloudflare_monitor_task and not self.cloudflare_monitor_task.done():
            self.cloudflare_monitor_task.cancel()
            try:
                await self.cloudflare_monitor_task
            except asyncio.CancelledError:
                pass
        self.cloudflare_monitor_task = None

        if self.tab:
            try:
                print("Desativando bypass automático do Cloudflare...")
                await self.tab.disable_auto_solve_cloudflare_captcha()
                await self.tab.close()
            except Exception:
                pass
            self.tab = None

        if self.browser:
            try:
                await self.browser.stop()
            except Exception:
                pass
            self.browser = None

        stop_virtual_display()
        self.running = False
        print("BOT OFFLINE.")

    def pause_hunt(self):
        self.hunt_pause_event.clear()

    def resume_hunt(self):
        self.hunt_pause_event.set()

    def is_running(self) -> bool:
        return self.running

    def is_hunt_running(self) -> bool:
        return self.running and self.hunt_pause_event.is_set()