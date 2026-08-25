import flet as ft
import time
import json
import random
import threading
from datetime import datetime, timezone

STORAGE_KEY = "save_v3"

UPGRADES = [
    {"id": "u1", "name": "Крепкая рука", "emoji": "💪", "base_cost": 25, "power": 1},
    {"id": "u2", "name": "Стальной палец", "emoji": "🦾", "base_cost": 150, "power": 3},
    {"id": "u3", "name": "Робо-тап", "emoji": "🤖", "base_cost": 800, "power": 8},
    {"id": "u4", "name": "Ферма кликов", "emoji": "🏭", "base_cost": 4000, "power": 25},
]

PASSIVE = [
    {"id": "p1", "name": "Мини-ферма", "emoji": "🌾", "base_cost": 100, "income": 5},
    {"id": "p2", "name": "Завод", "emoji": "🏗️", "base_cost": 600, "income": 30},
    {"id": "p3", "name": "Космодобыча", "emoji": "🚀", "base_cost": 3000, "income": 150},
]

QUESTS = [
    {"id": "q1", "desc": "Сделай 50 кликов", "type": "clicks", "target": 50, "reward": 100},
    {"id": "q2", "desc": "Сделай 300 кликов", "type": "clicks", "target": 300, "reward": 500},
    {"id": "q3", "desc": "Заработай 1000 очков (всего)", "type": "lifetime_points", "target": 1000, "reward": 300},
    {"id": "q4", "desc": "Заработай 10000 очков (всего)", "type": "lifetime_points", "target": 10000, "reward": 2000},
    {"id": "q5", "desc": "Купи 5 улучшений", "type": "upgrades_bought", "target": 5, "reward": 400},
]

ACHIEVEMENTS = [
    {"id": "a1", "desc": "🏆 1000 кликов за всю игру", "type": "clicks", "target": 1000, "reward": 1000},
    {"id": "a2", "desc": "🏆 50000 очков за всю игру", "type": "lifetime_points", "target": 50000, "reward": 5000},
    {"id": "a3", "desc": "🏆 Купить 15 улучшений", "type": "upgrades_bought", "target": 15, "reward": 3000},
]

SKINS = [
    {"id": "coin_classic", "emoji": "💰", "name": "Классика", "min_lifetime": 0},
    {"id": "coin_diamond", "emoji": "💎", "name": "Алмаз", "min_lifetime": 15000},
    {"id": "coin_fire", "emoji": "🔥", "name": "Огонь", "min_lifetime": 75000},
    {"id": "coin_star", "emoji": "🌟", "name": "Звезда", "min_lifetime": 300000},
]

LEAGUES = [
    {"name": "Бронза", "min": 0},
    {"name": "Серебро", "min": 2000},
    {"name": "Золото", "min": 15000},
    {"name": "Платина", "min": 75000},
    {"name": "Алмаз", "min": 300000},
]

CRIT_CHANCE = 0.1
CRIT_MULT = 5
PRESTIGE_THRESHOLD = 20000
PRESTIGE_BONUS_PER_POINT = 0.02  # +2% к доходу за каждое очко перерождения
BOOSTER_DURATION = 300  # 5 минут
BOOSTER_MULT = 2


def default_state():
    return {
        "points": 0,
        "lifetime_points": 0,
        "since_prestige_points": 0,
        "prestige_points": 0,
        "total_clicks": 0,
        "upgrades_bought_count": 0,
        "energy": 100,
        "energy_max": 100,
        "last_tick": time.time(),
        "last_login": None,
        "streak": 0,
        "owned_upgrades": {},
        "owned_passive": {},
        "claimed_quests": [],
        "claimed_achievements": [],
        "selected_skin": "coin_classic",
        "booster_until": 0,
    }


def main(page: ft.Page):
    page.title = "Кликер"
    page.bgcolor = "#12121a"
    page.padding = 0
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    try:
        build_game(page)
    except Exception as ex:
        import traceback
        page.controls.clear()
        page.scroll = ft.ScrollMode.AUTO
        page.add(
            ft.Text("Ошибка запуска игры:", size=18, weight=ft.FontWeight.BOLD, color="#ff5252"),
            ft.Text(str(ex), size=14, color="white", selectable=True),
            ft.Text(traceback.format_exc(), size=11, color="#9e9e9e", selectable=True),
        )
        page.update()


def build_game(page: ft.Page):
    state = {}

    def load_state():
        raw = page.client_storage.get(STORAGE_KEY)
        if raw:
            try:
                loaded = json.loads(raw)
                d = default_state()
                d.update(loaded)
                return d
            except Exception:
                pass
        return default_state()

    def save_state():
        page.client_storage.set(STORAGE_KEY, json.dumps(state))

    state.update(load_state())

    def upgrade_cost(base_cost, level):
        return int(base_cost * (1.15 ** level))

    def active_multiplier():
        mult = 1 + state["prestige_points"] * PRESTIGE_BONUS_PER_POINT
        if time.time() < state.get("booster_until", 0):
            mult *= BOOSTER_MULT
        return mult

    def base_click_power():
        power = 1
        for u in UPGRADES:
            lvl = state["owned_upgrades"].get(u["id"], 0)
            power += lvl * u["power"]
        return power

    def total_click_power():
        return base_click_power() * active_multiplier()

    def total_passive_income():
        income = 0
        for p in PASSIVE:
            lvl = state["owned_passive"].get(p["id"], 0)
            income += lvl * p["income"]
        return income * active_multiplier()

    def league_index():
        idx = 0
        for i, l in enumerate(LEAGUES):
            if state["lifetime_points"] >= l["min"]:
                idx = i
        return idx

    def current_league():
        return LEAGUES[league_index()]

    def add_points(amount):
        state["points"] += amount
        state["lifetime_points"] += amount
        state["since_prestige_points"] += amount

    # ---------- офлайн-прогресс ----------
    offline_gain = 0

    def apply_offline_progress():
        nonlocal offline_gain
        now = time.time()
        elapsed = max(0, now - state.get("last_tick", now))
        elapsed_capped = min(elapsed, 8 * 3600)
        income_per_sec = total_passive_income() / 3600
        gained = income_per_sec * elapsed_capped
        if gained > 1:
            add_points(gained)
            offline_gain = gained
        regen = elapsed / 3
        state["energy"] = min(state["energy_max"], state["energy"] + regen)
        state["last_tick"] = now

    def check_daily_bonus():
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        last = state.get("last_login")
        if last == today:
            return None
        if last:
            last_date = datetime.strptime(last, "%Y-%m-%d")
            diff_days = (datetime.now(timezone.utc).date() - last_date.date()).days
            state["streak"] = state.get("streak", 0) + 1 if diff_days == 1 else 1
        else:
            state["streak"] = 1
        state["last_login"] = today
        bonus = 50 * state["streak"]
        add_points(bonus)
        gave_booster = False
        if state["streak"] % 3 == 0:
            state["booster_until"] = time.time() + BOOSTER_DURATION
            gave_booster = True
        save_state()
        return bonus, state["streak"], gave_booster

    apply_offline_progress()
    daily_result = check_daily_bonus()
    save_state()

    # ---------- Верхняя панель ----------
    points_text = ft.Text(f"{int(state['points'])}", size=42, weight=ft.FontWeight.BOLD, color="#ffd54f")
    power_text = ft.Text(f"+{int(total_click_power())} за тап", size=14, color="#9e9e9e")
    passive_text = ft.Text(f"Пассивно: {int(total_passive_income())}/час", size=14, color="#9e9e9e")
    league_text = ft.Text(f"Лига: {current_league()['name']}", size=13, color="#ce93d8")
    league_progress = ft.ProgressBar(value=0, color="#ce93d8", bgcolor="#2a2a35", width=280)
    league_sub_text = ft.Text("", size=11, color="#9e9e9e")
    booster_text = ft.Text("", size=12, color="#4fc3f7")
    energy_text = ft.Text(f"{int(state['energy'])}/{state['energy_max']}", size=14, color="#80cbc4")
    energy_bar = ft.ProgressBar(value=state["energy"] / state["energy_max"], color="#80cbc4", bgcolor="#2a2a35", width=280)
    floating_text = ft.Text("", size=20, weight=ft.FontWeight.BOLD, color="#ffd54f", opacity=0)

    def current_skin_emoji():
        skin = next((s for s in SKINS if s["id"] == state["selected_skin"]), SKINS[0])
        return skin["emoji"]

    coin_text = ft.Text(current_skin_emoji(), size=90)

    def refresh_top():
        points_text.value = f"{int(state['points'])}"
        power_text.value = f"+{int(total_click_power())} за тап"
        passive_text.value = f"Пассивно: {int(total_passive_income())}/час"
        league_text.value = f"Лига: {current_league()['name']}"
        idx = league_index()
        if idx + 1 < len(LEAGUES):
            cur_min = LEAGUES[idx]["min"]
            next_min = LEAGUES[idx + 1]["min"]
            frac = (state["lifetime_points"] - cur_min) / max(1, (next_min - cur_min))
            league_progress.value = max(0, min(1, frac))
            league_sub_text.value = f"До {LEAGUES[idx + 1]['name']}: {int(max(0, next_min - state['lifetime_points']))}"
        else:
            league_progress.value = 1
            league_sub_text.value = "Максимальная лига!"
        if time.time() < state.get("booster_until", 0):
            remain = int(state["booster_until"] - time.time())
            booster_text.value = f"⚡ Бустер x{BOOSTER_MULT}: {remain // 60}:{remain % 60:02d}"
        else:
            booster_text.value = ""
        energy_text.value = f"{int(state['energy'])}/{state['energy_max']}"
        energy_bar.value = state["energy"] / state["energy_max"]
        update_quest_badge()
        page.update()

    # ---------- Клик ----------
    def flash_floating(text_value):
        floating_text.value = text_value
        floating_text.opacity = 1
        page.update()

        def hide():
            time.sleep(0.6)
            try:
                floating_text.opacity = 0
                page.update()
            except Exception:
                pass

        threading.Thread(target=hide, daemon=True).start()

    def on_click_coin(e):
        if state["energy"] < 1:
            return
        state["energy"] -= 1
        state["total_clicks"] += 1

        power = total_click_power()
        is_crit = random.random() < CRIT_CHANCE
        gained = power * CRIT_MULT if is_crit else power
        add_points(gained)

        coin_button.bgcolor = "#33261e" if is_crit else "#262633"
        page.update()

        def restore_color():
            time.sleep(0.08)
            try:
                coin_button.bgcolor = "#1e1e2a"
                page.update()
            except Exception:
                pass

        threading.Thread(target=restore_color, daemon=True).start()

        flash_floating(f"+{int(gained)}" + (" КРИТ!" if is_crit else ""))
        refresh_top()
        save_state()

    coin_button = ft.Container(
        content=coin_text,
        width=200,
        height=200,
        border_radius=100,
        bgcolor="#1e1e2a",
        alignment=ft.alignment.center,
        on_click=on_click_coin,
        ink=True,
    )

    # ---------- Магазин ----------
    def buy_upgrade(u):
        def handler(e):
            lvl = state["owned_upgrades"].get(u["id"], 0)
            cost = upgrade_cost(u["base_cost"], lvl)
            if state["points"] >= cost:
                state["points"] -= cost
                state["owned_upgrades"][u["id"]] = lvl + 1
                state["upgrades_bought_count"] += 1
                save_state()
                render_shop()
                refresh_top()
        return handler

    def buy_passive(p):
        def handler(e):
            lvl = state["owned_passive"].get(p["id"], 0)
            cost = upgrade_cost(p["base_cost"], lvl)
            if state["points"] >= cost:
                state["points"] -= cost
                state["owned_passive"][p["id"]] = lvl + 1
                state["upgrades_bought_count"] += 1
                save_state()
                render_shop()
                refresh_top()
        return handler

    def do_prestige(e):
        if state["since_prestige_points"] < PRESTIGE_THRESHOLD:
            return
        gained_pp = int(state["since_prestige_points"] // PRESTIGE_THRESHOLD)
        state["prestige_points"] += gained_pp
        state["since_prestige_points"] = 0
        state["points"] = 0
        state["owned_upgrades"] = {}
        state["owned_passive"] = {}
        state["energy"] = state["energy_max"]
        save_state()
        render_shop()
        refresh_top()
        show_info_dialog("Перерождение!", f"Получено очков перерождения: +{gained_pp}\nТекущий бонус: +{int(state['prestige_points'] * PRESTIGE_BONUS_PER_POINT * 100)}% к доходу")

    shop_column = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO)

    def shop_row(name, emoji, level, cost, on_buy, subtitle):
        return ft.Container(
            padding=10,
            border_radius=10,
            bgcolor="#1e1e2a",
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Column(spacing=2, controls=[
                        ft.Text(f"{emoji} {name}  Ур.{level}", size=14, weight=ft.FontWeight.BOLD, color="white"),
                        ft.Text(subtitle, size=11, color="#9e9e9e"),
                    ]),
                    ft.ElevatedButton(f"{cost} 💰", on_click=on_buy, bgcolor="#ffd54f", color="#12121a"),
                ],
            ),
        )

    def render_shop():
        shop_column.controls.clear()

        prestige_ready = state["since_prestige_points"] >= PRESTIGE_THRESHOLD
        shop_column.controls.append(
            ft.Container(
                padding=10, border_radius=10, bgcolor="#241e33",
                content=ft.Column(spacing=4, controls=[
                    ft.Text(f"✨ Очки перерождения: {state['prestige_points']} (бонус +{int(state['prestige_points'] * PRESTIGE_BONUS_PER_POINT * 100)}%)", size=12, color="#ce93d8"),
                    ft.Text(f"Прогресс к перерождению: {int(state['since_prestige_points'])}/{PRESTIGE_THRESHOLD}", size=11, color="#9e9e9e"),
                    ft.ElevatedButton(
                        "🔁 Переродиться" if prestige_ready else f"Нужно ещё {int(PRESTIGE_THRESHOLD - state['since_prestige_points'])}",
                        on_click=do_prestige if prestige_ready else None,
                        disabled=not prestige_ready,
                        bgcolor="#ce93d8" if prestige_ready else "#3a3a45",
                        color="#12121a" if prestige_ready else "#777",
                    ),
                ]),
            )
        )
        shop_column.controls.append(ft.Divider(color="#2a2a35"))

        shop_column.controls.append(ft.Text("Сила клика", size=16, weight=ft.FontWeight.BOLD, color="white"))
        for u in UPGRADES:
            lvl = state["owned_upgrades"].get(u["id"], 0)
            cost = upgrade_cost(u["base_cost"], lvl)
            shop_column.controls.append(shop_row(u["name"], u["emoji"], lvl, cost, buy_upgrade(u), f"+{u['power']} к клику"))
        shop_column.controls.append(ft.Divider(color="#2a2a35"))
        shop_column.controls.append(ft.Text("Пассивный доход", size=16, weight=ft.FontWeight.BOLD, color="white"))
        for p in PASSIVE:
            lvl = state["owned_passive"].get(p["id"], 0)
            cost = upgrade_cost(p["base_cost"], lvl)
            shop_column.controls.append(shop_row(p["name"], p["emoji"], lvl, cost, buy_passive(p), f"+{p['income']}/час"))
        page.update()

    # ---------- Квесты + достижения ----------
    quests_column = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO)

    def progress_value(entry):
        if entry["type"] == "clicks":
            return state["total_clicks"]
        if entry["type"] == "lifetime_points":
            return state["lifetime_points"]
        if entry["type"] == "upgrades_bought":
            return state["upgrades_bought_count"]
        return 0

    def claim_entry(entry, claimed_list_key, on_done):
        def handler(e):
            if entry["id"] in state[claimed_list_key]:
                return
            if progress_value(entry) >= entry["target"]:
                add_points(entry["reward"])
                state[claimed_list_key].append(entry["id"])
                save_state()
                on_done()
                refresh_top()
        return handler

    def entry_row(entry, claimed_list_key, on_done):
        done = entry["id"] in state[claimed_list_key]
        progress = min(progress_value(entry), entry["target"])
        ready = progress >= entry["target"] and not done
        if done:
            status = ft.Text("✅ Забрано", size=12, color="#66bb6a")
        elif ready:
            status = ft.ElevatedButton("Забрать", on_click=claim_entry(entry, claimed_list_key, on_done), bgcolor="#66bb6a", color="white")
        else:
            status = ft.Text(f"{int(progress)}/{entry['target']}", size=12, color="#9e9e9e")
        return ft.Container(
            padding=10, border_radius=10, bgcolor="#1e1e2a",
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Column(spacing=2, controls=[
                        ft.Text(entry["desc"], size=13, color="white"),
                        ft.Text(f"Награда: {entry['reward']} 💰", size=11, color="#ffd54f"),
                    ]),
                    status,
                ],
            ),
        )

    def render_quests():
        quests_column.controls.clear()
        quests_column.controls.append(ft.Text("Задания", size=16, weight=ft.FontWeight.BOLD, color="white"))
        for q in QUESTS:
            quests_column.controls.append(entry_row(q, "claimed_quests", render_quests))
        quests_column.controls.append(ft.Divider(color="#2a2a35"))
        quests_column.controls.append(ft.Text("Достижения", size=16, weight=ft.FontWeight.BOLD, color="white"))
        for a in ACHIEVEMENTS:
            quests_column.controls.append(entry_row(a, "claimed_achievements", render_quests))
        page.update()

    def unclaimed_ready_count():
        count = 0
        for q in QUESTS:
            if q["id"] not in state["claimed_quests"] and progress_value(q) >= q["target"]:
                count += 1
        for a in ACHIEVEMENTS:
            if a["id"] not in state["claimed_achievements"] and progress_value(a) >= a["target"]:
                count += 1
        return count

    def update_quest_badge():
        n = unclaimed_ready_count()
        quests_tab_btn.text = f"📋 Задания ({n})" if n > 0 else "📋 Задания"

    # ---------- Скины ----------
    skins_column = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO)

    def select_skin(s):
        def handler(e):
            if state["lifetime_points"] >= s["min_lifetime"]:
                state["selected_skin"] = s["id"]
                coin_text.value = s["emoji"]
                save_state()
                render_skins()
                page.update()
        return handler

    def render_skins():
        skins_column.controls.clear()
        skins_column.controls.append(ft.Text("Скины монеты", size=16, weight=ft.FontWeight.BOLD, color="white"))
        for s in SKINS:
            unlocked = state["lifetime_points"] >= s["min_lifetime"]
            selected = state["selected_skin"] == s["id"]
            if selected:
                btn = ft.Text("✅ Выбран", size=12, color="#66bb6a")
            elif unlocked:
                btn = ft.ElevatedButton("Выбрать", on_click=select_skin(s), bgcolor="#ffd54f", color="#12121a")
            else:
                btn = ft.Text(f"🔒 {s['min_lifetime']}", size=12, color="#666")
            skins_column.controls.append(
                ft.Container(
                    padding=10, border_radius=10, bgcolor="#1e1e2a",
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Row(controls=[ft.Text(s["emoji"], size=28), ft.Text(s["name"], size=14, color="white")]),
                            btn,
                        ],
                    ),
                )
            )
        page.update()

    render_shop()
    render_quests()
    render_skins()

    # ---------- Вкладки ----------
    tabs_content = ft.Container(content=shop_column, height=260, width=320, padding=10)

    def sho
