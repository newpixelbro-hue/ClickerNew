import flet as ft
import time
import json
import threading
from datetime import datetime, timezone

STORAGE_KEY = "save_v2"

UPGRADES = [
    {"id": "u1", "name": "Крепкая рука", "base_cost": 25, "power": 1},
    {"id": "u2", "name": "Стальной палец", "base_cost": 150, "power": 3},
    {"id": "u3", "name": "Робо-тап", "base_cost": 800, "power": 8},
    {"id": "u4", "name": "Ферма кликов", "base_cost": 4000, "power": 25},
]

PASSIVE = [
    {"id": "p1", "name": "Мини-ферма", "base_cost": 100, "income": 5},
    {"id": "p2", "name": "Завод", "base_cost": 600, "income": 30},
    {"id": "p3", "name": "Космодобыча", "base_cost": 3000, "income": 150},
]

# Квесты: id, описание, тип цели (clicks / lifetime_points / upgrades_bought), значение, награда
QUESTS = [
    {"id": "q1", "desc": "Сделай 50 кликов", "type": "clicks", "target": 50, "reward": 100},
    {"id": "q2", "desc": "Сделай 300 кликов", "type": "clicks", "target": 300, "reward": 500},
    {"id": "q3", "desc": "Заработай 1000 очков (всего)", "type": "lifetime_points", "target": 1000, "reward": 300},
    {"id": "q4", "desc": "Заработай 10000 очков (всего)", "type": "lifetime_points", "target": 10000, "reward": 2000},
    {"id": "q5", "desc": "Купи 5 улучшений", "type": "upgrades_bought", "target": 5, "reward": 400},
]

# Лиги по общему заработку за всю игру (lifetime_points)
LEAGUES = [
    {"name": "Бронза", "min": 0},
    {"name": "Серебро", "min": 2000},
    {"name": "Золото", "min": 15000},
    {"name": "Платина", "min": 75000},
    {"name": "Алмаз", "min": 300000},
]

CRIT_CHANCE = 0.1
CRIT_MULT = 5


def default_state():
    return {
        "points": 0,
        "lifetime_points": 0,      # всего заработано за игру (не тратится)
        "total_clicks": 0,
        "upgrades_bought_count": 0,
        "click_power": 1,
        "energy": 100,
        "energy_max": 100,
        "last_tick": time.time(),
        "last_login": None,
        "streak": 0,
        "owned_upgrades": {},
        "owned_passive": {},
        "claimed_quests": [],
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

    def total_click_power():
        power = 1
        for u in UPGRADES:
            lvl = state["owned_upgrades"].get(u["id"], 0)
            power += lvl * u["power"]
        return power

    def total_passive_income():
        income = 0
        for p in PASSIVE:
            lvl = state["owned_passive"].get(p["id"], 0)
            income += lvl * p["income"]
        return income

    def current_league():
        lp = state["lifetime_points"]
        league = LEAGUES[0]
        for l in LEAGUES:
            if lp >= l["min"]:
                league = l
        return league

    def add_points(amount):
        state["points"] += amount
        state["lifetime_points"] += amount

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
        save_state()
        return bonus, state["streak"]

    apply_offline_progress()
    daily_result = check_daily_bonus()
    save_state()

    # ---------- Верхняя панель ----------
    points_text = ft.Text(f"{int(state['points'])}", size=42, weight=ft.FontWeight.BOLD, color="#ffd54f")
    power_text = ft.Text(f"+{total_click_power()} за тап", size=14, color="#9e9e9e")
    passive_text = ft.Text(f"Пассивно: {total_passive_income()}/час", size=14, color="#9e9e9e")
    league_text = ft.Text(f"Лига: {current_league()['name']}", size=13, color="#ce93d8")
    energy_text = ft.Text(f"{int(state['energy'])}/{state['energy_max']}", size=14, color="#80cbc4")
    energy_bar = ft.ProgressBar(value=state["energy"] / state["energy_max"], color="#80cbc4", bgcolor="#2a2a35", width=280)
    floating_text = ft.Text("", size=20, weight=ft.FontWeight.BOLD, color="#ffd54f", opacity=0)

    def refresh_top():
        points_text.value = f"{int(state['points'])}"
        power_text.value = f"+{total_click_power()} за тап"
        passive_text.value = f"Пассивно: {total_passive_income()}/час"
        league_text.value = f"Лига: {current_league()['name']}"
        energy_text.value = f"{int(state['energy'])}/{state['energy_max']}"
        energy_bar.value = state["energy"] / state["energy_max"]
        page.update()

    # ---------- Клик + крит + анимация ----------
    import random

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
        check_quests_silently()
        refresh_top()
        save_state()

    coin_button = ft.Container(
        content=ft.Text("💰", size=90),
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
                check_quests_silently()
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
                check_quests_silently()
                refresh_top()
        return handler

    shop_column = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO)

    def shop_row(name, level, cost, on_buy, subtitle):
        return ft.Container(
            padding=10,
            border_radius=10,
            bgcolor="#1e1e2a",
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Column(spacing=2, controls=[
                        ft.Text(f"{name}  Ур.{level}", size=14, weight=ft.FontWeight.BOLD, color="white"),
                        ft.Text(subtitle, size=11, color="#9e9e9e"),
                    ]),
                    ft.ElevatedButton(f"{cost} 💰", on_click=on_buy, bgcolor="#ffd54f", color="#12121a"),
                ],
            ),
        )

    def render_shop():
        shop_column.controls.clear()
        shop_column.controls.append(ft.Text("Сила клика", size=16, weight=ft.FontWeight.BOLD, color="white"))
        for u in UPGRADES:
            lvl = state["owned_upgrades"].get(u["id"], 0)
            cost = upgrade_cost(u["base_cost"], lvl)
            shop_column.controls.append(shop_row(u["name"], lvl, cost, buy_upgrade(u), f"+{u['power']} к клику"))
        shop_column.controls.append(ft.Divider(color="#2a2a35"))
        shop_column.controls.append(ft.Text("Пассивный доход", size=16, weight=ft.FontWeight.BOLD, color="white"))
        for p in PASSIVE:
            lvl = state["owned_passive"].get(p["id"], 0)
            cost = upgrade_cost(p["base_cost"], lvl)
            shop_column.controls.append(shop_row(p["name"], lvl, cost, buy_passive(p), f"+{p['income']}/час"))
        page.update()

    # ---------- Квесты ----------
    quests_column = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO)

    def quest_progress_value(q):
        if q["type"] == "clicks":
            return state["total_clicks"]
        if q["type"] == "lifetime_points":
            return state["lifetime_points"]
        if q["type"] == "upgrades_bought":
            return state["upgrades_bought_count"]
        return 0

    def claim_quest(q):
        def handler(e):
            if q["id"] in state["claimed_quests"]:
                return
            if quest_progress_value(q) >= q["target"]:
                add_points(q["reward"])
                state["claimed_quests"].append(q["id"])
                save_state()
                render_quests()
                refresh_top()
        return handler

    def render_quests():
        quests_column.controls.clear()
        for q in QUESTS:
            done = q["id"] in state["claimed_quests"]
            progress = min(quest_progress_value(q), q["target"])
            ready = progress >= q["target"] and not done
            if done:
                status_btn = ft.Text("✅ Забрано", size=12, color="#66bb6a")
            elif ready:
                status_btn = ft.ElevatedButton("Забрать", on_click=claim_quest(q), bgcolor="#66bb6a", color="white")
            else:
                status_btn = ft.Text(f"{progress}/{q['target']}", size=12, color="#9e9e9e")

            quests_column.controls.append(
                ft.Container(
                    padding=10,
                    border_radius=10,
                    bgcolor="#1e1e2a",
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Column(spacing=2, controls=[
                                ft.Text(q["desc"], size=13, color="white"),
                                ft.Text(f"Награда: {q['reward']} 💰", size=11, color="#ffd54f"),
                            ]),
                            status_btn,
                        ],
                    ),
                )
            )
        page.update()

    def check_quests_silently():
        # просто пересчитываем прогресс, кнопка "забрать" сама появится при рендере
        pass

    render_shop()
    render_quests()

    # ---------- Вкладки: магазин / квесты ----------
    tabs_content = ft.Container(content=shop_column, height=260, width=320, padding=10)

    def show_shop(e=None):
        tabs_content.content = shop_column
        render_shop()
        page.update()

    def show_quests(e=None):
        tabs_content.content = quests_column
        render_quests()
        page.update()

    tab_buttons = ft.Row(
        alignment=ft.MainAxisAlignment.CENTER,
        controls=[
            ft.TextButton("🛒 Магазин", on_click=show_shop),
            ft.TextButton("📋 Задания", on_click=show_quests),
        ],
    )

    # ---------- Автотик: энергия, пассивный доход, обновление квестов ----------
    def tick_loop():
        while True:
            time.sleep(1)
            now = time.time()
            elapsed = now - state.get("last_tick", now)
            state["energy"] = min(state["energy_max"], state["energy"] + elapsed / 3)
            add_points((total_passive_income() / 3600) * elapsed)
            state["last_tick"] = now
            try:
                refresh_top()
            except Exception:
                break

    threading.Thread(target=tick_loop, daemon=True).start()

    # ---------- Диалоги ----------
    dialogs_queue = []

    def close_dialog(e):
        page.dialog.open = False
        page.update()
        show_next_dialog()

    if offline_gain > 1:
        dialogs_queue.append(
            ft.AlertDialog(
                title=ft.Text("Пока тебя не было"),
                content=ft.Text(f"Ферма накопила: +{int(offline_gain)} 💰"),
                actions=[ft.TextButton("Ок", on_click=close_dialog)],
            )
        )

    if daily_result:
        bonus, streak = daily_result
        dialogs_queue.append(
            ft.AlertDialog(
                title=ft.Text("Ежедневный бонус!"),
                content=ft.Text(f"День подряд: {streak}\nПолучено: +{bonus} 💰"),
                actions=[ft.TextButton("Забрать", on_click=close_dialog)],
            )
        )

    def show_next_dialog():
        if dialogs_queue:
            dlg = dialogs_queue.pop(0)
            page.dialog = dlg
            dlg.open = True
            page.update()

    # ---------- Сборка экрана ----------
    page.add(
        ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=8,
            controls=[
                ft.Container(height=15),
                league_text,
                points_text,
                power_text,
                passive_text,
                ft.Stack(
                    controls=[
                        ft.Container(height=10),
                        ft.Container(content=floating_text, alignment=ft.alignment.center),
                    ]
                ),
                coin_button,
                energy_text,
                energy_bar,
                ft.Container(height=6),
                tab_buttons,
                tabs_content,
            ],
        )
    )

    show_next_dialog()


ft.app(target=main)
    
