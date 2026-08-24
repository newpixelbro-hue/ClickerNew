import flet as ft
import time
import json
import math
from datetime import datetime, timezone

STORAGE_KEY = "save_v1"

# --- Апгрейды: id, название, базовая цена, прирост дохода за клик, множитель роста цены
UPGRADES = [
    {"id": "u1", "name": "Крепкая рука", "base_cost": 25, "power": 1},
    {"id": "u2", "name": "Стальной палец", "base_cost": 150, "power": 3},
    {"id": "u3", "name": "Робо-тап", "base_cost": 800, "power": 8},
    {"id": "u4", "name": "Ферма кликов", "base_cost": 4000, "power": 25},
]

# --- Пассивный доход: отдельная ветка апгрейдов (очки в час)
PASSIVE = [
    {"id": "p1", "name": "Мини-ферма", "base_cost": 100, "income": 5},
    {"id": "p2", "name": "Завод", "base_cost": 600, "income": 30},
    {"id": "p3", "name": "Космодобыча", "base_cost": 3000, "income": 150},
]


def default_state():
    return {
        "points": 0,
        "click_power": 1,
        "energy": 100,
        "energy_max": 100,
        "last_tick": time.time(),          # для восстановления энергии
        "last_login": None,                 # для ежедневного бонуса
        "streak": 0,                        # серия дней подряд
        "owned_upgrades": {},               # {id: level}
        "owned_passive": {},                # {id: level}
    }


def main(page: ft.Page):
    page.title = "Кликер"
    page.bgcolor = "#12121a"
    page.padding = 0
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER

    state = {}

    # ---------- Сохранение / загрузка ----------
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

    # ---------- Расчёт цены следующего уровня апгрейда ----------
    def upgrade_cost(base_cost, level):
        return int(base_cost * (1.15 ** level))

    def total_click_power():
        power = 1
        for u in UPGRADES:
            lvl = state["owned_upgrades"].get(u["id"], 0)
            power += lvl * u["power"]
        return power

    def total_passive_income():
        # очков в час
        income = 0
        for p in PASSIVE:
            lvl = state["owned_passive"].get(p["id"], 0)
            income += lvl * p["income"]
        return income

    # ---------- Применяем офлайн-доход и восстановление энергии при заходе ----------
    def apply_offline_progress():
        now = time.time()
        elapsed = max(0, now - state.get("last_tick", now))

        # пассивный доход капаем за прошедшее время (максимум 8 часов офлайн, чтобы не абузили)
        elapsed_capped = min(elapsed, 8 * 3600)
        income_per_sec = total_passive_income() / 3600
        state["points"] += income_per_sec * elapsed_capped

        # энергия восстанавливается 1 очко в 3 секунды
        regen = elapsed / 3
        state["energy"] = min(state["energy_max"], state["energy"] + regen)

        state["last_tick"] = now

    def check_daily_bonus():
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        last = state.get("last_login")
        if last == today:
            return None  # уже забирал сегодня

        # проверяем серию: если заходил вчера — стрик растёт, иначе сбрасывается
        if last:
            last_date = datetime.strptime(last, "%Y-%m-%d")
            diff_days = (datetime.now(timezone.utc).date() - last_date.date()).days
            if diff_days == 1:
                state["streak"] = state.get("streak", 0) + 1
            else:
                state["streak"] = 1
        else:
            state["streak"] = 1

        state["last_login"] = today
        bonus = 50 * state["streak"]  # растёт с каждым днём подряд
        state["points"] += bonus
        save_state()
        return bonus, state["streak"]

    apply_offline_progress()
    daily_result = check_daily_bonus()
    save_state()

    # ---------- UI элементы ----------
    points_text = ft.Text(f"{int(state['points'])}", size=42, weight=ft.FontWeight.BOLD, color="#ffd54f")
    power_text = ft.Text(f"+{total_click_power()} за тап", size=14, color="#9e9e9e")
    passive_text = ft.Text(f"Пассивно: {total_passive_income()}/час", size=14, color="#9e9e9e")
    energy_text = ft.Text(f"{int(state['energy'])}/{state['energy_max']}", size=14, color="#80cbc4")
    energy_bar = ft.ProgressBar(value=state["energy"] / state["energy_max"], color="#80cbc4", bgcolor="#2a2a35", width=280)

    def refresh_top():
        points_text.value = f"{int(state['points'])}"
        power_text.value = f"+{total_click_power()} за тап"
        passive_text.value = f"Пассивно: {total_passive_income()}/час"
        energy_text.value = f"{int(state['energy'])}/{state['energy_max']}"
        energy_bar.value = state["energy"] / state["energy_max"]
        page.update()

    # ---------- Клик ----------
    def on_click_coin(e):
        if state["energy"] < 1:
            return
        state["energy"] -= 1
        state["points"] += total_click_power()
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

    # ---------- Магазин апгрейдов (клик-сила) ----------
    def buy_upgrade(u):
        def handler(e):
            lvl = state["owned_upgrades"].get(u["id"], 0)
            cost = upgrade_cost(u["base_cost"], lvl)
            if state["points"] >= cost:
                state["points"] -= cost
                state["owned_upgrades"][u["id"]] = lvl + 1
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
                save_state()
                render_shop()
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
            shop_column.controls.append(
                shop_row(u["name"], lvl, cost, buy_upgrade(u), f"+{u['power']} к клику")
            )
        shop_column.controls.append(ft.Divider(color="#2a2a35"))
        shop_column.controls.append(ft.Text("Пассивный доход", size=16, weight=ft.FontWeight.BOLD, color="white"))
        for p in PASSIVE:
            lvl = state["owned_passive"].get(p["id"], 0)
            cost = upgrade_cost(p["base_cost"], lvl)
            shop_column.controls.append(
                shop_row(p["name"], lvl, cost, buy_passive(p), f"+{p['income']}/час")
            )
        page.update()

    render_shop()

    # ---------- Автообновление энергии/пассивного дохода раз в секунду ----------
    import threading

    def tick_loop():
        while True:
            time.sleep(1)
            now = time.time()
            elapsed = now - state.get("last_tick", now)
            state["energy"] = min(state["energy_max"], state["energy"] + elapsed / 3)
            state["points"] += (total_passive_income() / 3600) * elapsed
            state["last_tick"] = now
            try:
                refresh_top()
            except Exception:
                break  # окно закрыто

    threading.Thread(target=tick_loop, daemon=True).start()

    # ---------- Диалог ежедневного бонуса ----------
    def close_dialog(e):
        page.dialog.open = False
        page.update()

    if daily_result:
        bonus, streak = daily_result
        page.dialog = ft.AlertDialog(
            title=ft.Text("Ежедневный бонус!"),
            content=ft.Text(f"День подряд: {streak}\nПолучено: +{bonus} 💰"),
            actions=[ft.TextButton("Забрать", on_click=close_dialog)],
        )
        page.dialog.open = True

    # ---------- Сборка экрана ----------
    page.add(
        ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
            controls=[
                ft.Container(height=20),
                points_text,
                power_text,
                passive_text,
                ft.Container(height=10),
                coin_button,
                ft.Container(height=10),
                energy_text,
                energy_bar,
                ft.Container(height=10),
                ft.Container(
                    content=shop_column,
                    height=280,
                    width=320,
                    padding=10,
                ),
            ],
        )
    )


ft.app(target=main)
