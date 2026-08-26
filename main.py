import flet as ft
import time
import json
import random
import threading
import urllib.request
import urllib.error
from datetime import datetime, timezone

SESSION_KEY = "session_v1"    # кто сейчас залогинен / запомнить ли (только локально, для предзаполнения формы)

ADMIN_USERNAME = "admin"
ADMIN_SECRET_CODE = "ROYAL2026"  # поменяй перед сборкой на свой личный код, никому не говори его

# ---------- Firebase ----------
FIREBASE_API_KEY = "AIzaSyB2-ujCytjq_v1gzm9sU-0Fcoc5oM0B0Hk"
FIREBASE_PROJECT_ID = "clickernew-eb5c9"
FIRESTORE_BASE = f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}/databases/(default)/documents"
FIREBASE_AUTH_BASE = "https://identitytoolkit.googleapis.com/v1/accounts"

AUTH_ERROR_MESSAGES = {
    "EMAIL_EXISTS": "Такой ник уже занят",
    "EMAIL_NOT_FOUND": "Такого игрока нет — сначала зарегистрируйся",
    "INVALID_PASSWORD": "Неверный пароль",
    "INVALID_LOGIN_CREDENTIALS": "Неверный ник или пароль",
    "USER_DISABLED": "Этот аккаунт заблокирован",
}


def friendly_auth_error(raw_message):
    if raw_message == "NETWORK_ERROR":
        return "Нет подключения к интернету. Проверь связь и попробуй снова."
    for key, text in AUTH_ERROR_MESSAGES.items():
        if key in raw_message:
            return text
    if "WEAK_PASSWORD" in raw_message:
        return "Пароль слишком короткий (минимум 6 символов)"
    return "Ошибка: " + raw_message


def http_json(url, method="GET", payload=None, headers=None, timeout=12):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return (json.loads(body) if body else {}), None
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
            msg = body.get("error", {}).get("message", str(e))
        except Exception:
            msg = str(e)
        return None, msg
    except Exception:
        return None, "NETWORK_ERROR"


def nickname_to_email(nickname):
    return f"{nickname.strip().lower()}@clickernew.local"


def firebase_sign_up(nickname, password):
    url = f"{FIREBASE_AUTH_BASE}:signUp?key={FIREBASE_API_KEY}"
    return http_json(url, "POST", {"email": nickname_to_email(nickname), "password": password, "returnSecureToken": True})


def firebase_sign_in(nickname, password):
    url = f"{FIREBASE_AUTH_BASE}:signInWithPassword?key={FIREBASE_API_KEY}"
    return http_json(url, "POST", {"email": nickname_to_email(nickname), "password": password, "returnSecureToken": True})


def league_name_for_points(points):
    name = LEAGUES[0]["name"]
    for l in LEAGUES:
        if points >= l["min"]:
            name = l["name"]
    return name


def fs_encode_state(nickname, state):
    fields = {
        "nickname": {"stringValue": nickname},
        "lifetime_points": {"integerValue": str(int(state.get("lifetime_points", 0)))},
        "league": {"stringValue": league_name_for_points(state.get("lifetime_points", 0))},
        "prestige_count": {"integerValue": str(int(state.get("prestige_count", 0)))},
        "updated_at": {"stringValue": datetime.now(timezone.utc).isoformat()},
        "data": {"stringValue": json.dumps(state, ensure_ascii=False)},
    }
    return fields


def fs_decode_doc(doc):
    fields = doc.get("fields", {})
    raw = fields.get("data", {}).get("stringValue")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            return None
    return None


def firestore_save_state(id_token, uid, nickname, state):
    fields = fs_encode_state(nickname, state)
    mask = "&".join(f"updateMask.fieldPaths={k}" for k in fields.keys())
    url = f"{FIRESTORE_BASE}/players/{uid}?{mask}"
    headers = {"Authorization": f"Bearer {id_token}"}
    _, err = http_json(url, "PATCH", {"fields": fields}, headers=headers)
    return err is None


def firestore_load_state(id_token, uid):
    url = f"{FIRESTORE_BASE}/players/{uid}"
    headers = {"Authorization": f"Bearer {id_token}"}
    result, err = http_json(url, "GET", None, headers=headers)
    if err or not result:
        return None
    return fs_decode_doc(result)


def firestore_leaderboard(limit=20):
    url = f"{FIRESTORE_BASE}:runQuery"
    payload = {
        "structuredQuery": {
            "from": [{"collectionId": "players"}],
            "orderBy": [{"field": {"fieldPath": "lifetime_points"}, "direction": "DESCENDING"}],
            "limit": limit,
        }
    }
    result, err = http_json(url, "POST", payload)
    if err or not result:
        return []
    players = []
    for item in result:
        doc = item.get("document")
        if not doc:
            continue
        f = doc.get("fields", {})
        players.append({
            "nickname": f.get("nickname", {}).get("stringValue", "???"),
            "lifetime_points": int(f.get("lifetime_points", {}).get("integerValue", "0")),
            "league": f.get("league", {}).get("stringValue", ""),
            "prestige_count": int(f.get("prestige_count", {}).get("integerValue", "0")),
        })
    return players


UPGRADES = [
    {"id": "u1", "name": "Крепкая рука", "emoji": "💪", "base_cost": 25, "power": 1},
    {"id": "u2", "name": "Стальной палец", "emoji": "🦾", "base_cost": 150, "power": 3},
    {"id": "u3", "name": "Робо-тап", "emoji": "🤖", "base_cost": 800, "power": 8},
    {"id": "u4", "name": "Ферма кликов", "emoji": "🏭", "base_cost": 4000, "power": 25},
]

PASSIVE = [
    {"id": "p1", "name": "Мини-ферма", "emoji": "🌾", "base_cost": 100, "income": 30},
    {"id": "p2", "name": "Завод", "emoji": "🏗️", "base_cost": 600, "income": 180},
    {"id": "p3", "name": "Космодобыча", "emoji": "🚀", "base_cost": 3000, "income": 900},
]

# Квесты сбрасываются и растут по сложности после каждого перерождения (используют "since_prestige_*" счётчики)
QUESTS_BASE = [
    {"id": "q1", "desc": "Сделай {t} кликов", "type": "clicks_run", "target": 50, "reward": 100, "reward_type": "points"},
    {"id": "q2", "desc": "Сделай {t} кликов", "type": "clicks_run", "target": 300, "reward": 500, "reward_type": "points"},
    {"id": "q3", "desc": "Сделай {t} кликов", "type": "clicks_run", "target": 800, "reward": 1200, "reward_type": "points"},
    {"id": "q4", "desc": "Заработай {t} очков за этот забег", "type": "points_run", "target": 1000, "reward": 300, "reward_type": "points"},
    {"id": "q5", "desc": "Заработай {t} очков за этот забег", "type": "points_run", "target": 5000, "reward": 1200, "reward_type": "points"},
    {"id": "q6", "desc": "Заработай {t} очков за этот забег", "type": "points_run", "target": 15000, "reward": 3000, "reward_type": "points"},
    {"id": "q7", "desc": "Купи {t} улучшений за этот забег", "type": "upgrades_run", "target": 5, "reward": 400, "reward_type": "points"},
    {"id": "q8", "desc": "Купи {t} улучшений за этот забег", "type": "upgrades_run", "target": 12, "reward": 1500, "reward_type": "points"},
    {"id": "q9", "desc": "Сделай {t} кликов", "type": "clicks_run", "target": 150, "reward": 100, "reward_type": "energy"},
    {"id": "q10", "desc": "Заработай {t} очков за этот забег", "type": "points_run", "target": 3000, "reward": 100, "reward_type": "energy"},
]


def build_quests(prestige_count):
    diff_mult = 1 + prestige_count * 0.6
    reward_mult = 1 + prestige_count * 0.5
    quests = []
    for q in QUESTS_BASE:
        target = max(1, int(round(q["target"] * diff_mult)))
        if q["reward_type"] == "energy":
            reward = q["reward"]  # энергия не растёт с престижем, всегда полный бак
        else:
            reward = max(1, int(round(q["reward"] * reward_mult)))
        quests.append({
            "id": q["id"],
            "desc": q["desc"].format(t=target),
            "type": q["type"],
            "target": target,
            "reward": reward,
            "reward_type": q["reward_type"],
        })
    return quests

PROMOCODES = {
    "ADMIN": {"points": 3000, "energy_full": True},
}

ACHIEVEMENTS = [
    {"id": "a1", "desc": "🏆 1000 кликов за всю игру", "type": "clicks", "target": 1000, "reward": 1000},
    {"id": "a2", "desc": "🏆 50000 очков за всю игру", "type": "lifetime_points", "target": 50000, "reward": 5000},
    {"id": "a3", "desc": "🏆 Купить 15 улучшений", "type": "upgrades_bought", "target": 15, "reward": 3000},
]

SKINS = [
    {"id": "coin_classic", "emoji": "💰", "name": "Классика", "min_lifetime": 0, "bonus_type": None, "bonus_value": 0, "bonus_desc": "Без бонуса"},
    {"id": "coin_diamond", "emoji": "💎", "name": "Алмаз", "min_lifetime": 15000, "bonus_type": "passive", "bonus_value": 0.05, "bonus_desc": "+5% к пассивному доходу"},
    {"id": "coin_fire", "emoji": "🔥", "name": "Огонь", "min_lifetime": 75000, "bonus_type": "crit_chance", "bonus_value": 0.05, "bonus_desc": "+5% к шансу крита"},
    {"id": "coin_star", "emoji": "🌟", "name": "Звезда", "min_lifetime": 300000, "bonus_type": "click_power", "bonus_value": 0.10, "bonus_desc": "+10% к силе клика"},
]

LEAGUES = [
    {"name": "Бронза", "min": 0, "offline_mult": 0.5},
    {"name": "Серебро", "min": 2000, "offline_mult": 0.65},
    {"name": "Золото", "min": 15000, "offline_mult": 0.85},
    {"name": "Платина", "min": 75000, "offline_mult": 1.1},
    {"name": "Алмаз", "min": 300000, "offline_mult": 1.5},
]

# Кейсы: у каждого свой список наград с весами (шанс = вес / сумма весов)
CASES = [
    # Дешёвые кейсы — только очки, никакой энергии/бустеров (иначе энергия перестаёт быть ограничителем)
    {"id": "case_starter", "name": "Стартовый кейс", "emoji": "🧰", "cost": 150, "daily_limit": 8, "rewards": [
        {"type": "points", "amount": 60, "weight": 55, "label": "+60 💰"},
        {"type": "points", "amount": 150, "weight": 30, "label": "+150 💰"},
        {"type": "points", "amount": 400, "weight": 15, "label": "+400 💰"},
    ]},
    {"id": "case_common", "name": "Обычный кейс", "emoji": "📦", "cost": 500, "daily_limit": 5, "rewards": [
        {"type": "points", "amount": 350, "weight": 45, "label": "+350 💰"},
        {"type": "points", "amount": 900, "weight": 25, "label": "+900 💰"},
        {"type": "points", "amount": 2000, "weight": 10, "label": "+2000 💰"},
        {"type": "energy_add", "amount": 20, "weight": 20, "label": "+20 энергии ⚡"},
    ]},
    # Дорогие кейсы — сами по себе ограничены дневным лимитом, а не только ценой
    {"id": "case_rare", "name": "Редкий кейс", "emoji": "🎁", "cost": 2500, "daily_limit": 3, "rewards": [
        {"type": "points", "amount": 1800, "weight": 35, "label": "+1800 💰"},
        {"type": "points", "amount": 5000, "weight": 15, "label": "+5000 💰"},
        {"type": "energy_full", "weight": 15, "label": "Полная энергия ⚡"},
        {"type": "booster", "seconds": 300, "weight": 25, "label": "Бустер x2 на 5 мин ⚡"},
        {"type": "prestige_points", "amount": 1, "weight": 10, "label": "+1 очко перерождения ✨"},
    ]},
    {"id": "case_epic", "name": "Эпический кейс", "emoji": "💠", "cost": 10000, "daily_limit": 1, "rewards": [
        {"type": "points", "amount": 7000, "weight": 30, "label": "+7000 💰"},
        {"type": "points", "amount": 18000, "weight": 15, "label": "+18000 💰"},
        {"type": "booster", "seconds": 600, "weight": 25, "label": "Бустер x2 на 10 мин ⚡"},
        {"type": "prestige_points", "amount": 2, "weight": 20, "label": "+2 очка перерождения ✨"},
        {"type": "prestige_points", "amount": 5, "weight": 10, "label": "+5 очков перерождения ✨🌟"},
    ]},
]

CRIT_CHANCE = 0.1
CRIT_MULT = 5
PRESTIGE_THRESHOLD = 20000
PRESTIGE_BONUS_PER_POINT = 0.05  # +5% к доходу за каждое очко перерождения
ENERGY_PER_PRESTIGE = 20  # +20 к максимуму энергии за каждое перерождение
BOOSTER_DURATION = 300  # 5 минут
BOOSTER_MULT = 2


def default_state():
    return {
        "points": 0,
        "lifetime_points": 0,
        "since_prestige_points": 0,
        "since_prestige_clicks": 0,
        "since_prestige_upgrades": 0,
        "prestige_points": 0,
        "prestige_count": 0,
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
        "used_promocodes": [],
        "case_opens": {},
        "total_cases_opened": 0,
        "created_at": None,
        "admin_unlimited": False,
        "admin_god_mode": False,
    }


def main(page: ft.Page):
    page.title = "Кликер"
    page.bgcolor = "#12121a"
    page.padding = 0
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    try:
        show_auth_screen(page)
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


def safe_run(page, fn):
    """Обёртка: если внутри fn что-то упадёт — покажем текст ошибки вместо тишины/серого экрана."""
    try:
        fn()
    except Exception as ex:
        import traceback
        page.controls.clear()
        page.scroll = ft.ScrollMode.AUTO
        page.add(
            ft.Text("Ошибка:", size=18, weight=ft.FontWeight.BOLD, color="#ff5252"),
            ft.Text(str(ex), size=14, color="white", selectable=True),
            ft.Text(traceback.format_exc(), size=11, color="#9e9e9e", selectable=True),
        )
        page.update()


def show_auth_screen(page: ft.Page):
    # "запомнить меня" из прошлого раза — только подставляем данные в поля, форму всё равно показываем
    remembered_username = ""
    remembered_password = ""
    session_raw = page.client_storage.get(SESSION_KEY)
    if session_raw:
        try:
            session = json.loads(session_raw)
            if session.get("remember"):
                remembered_username = session.get("username", "")
                remembered_password = session.get("password", "")
        except Exception:
            pass

    mode = {"value": "login"}

    username_field = ft.TextField(label="Ник", width=260, value=remembered_username, color="white", border_color="#3a3a45")
    password_field = ft.TextField(label="Пароль", width=260, value=remembered_password, password=True, can_reveal_password=True, color="white", border_color="#3a3a45")
    admin_code_field = ft.TextField(label="Код администратора", width=260, password=True, can_reveal_password=True, visible=False, color="white", border_color="#3a3a45")
    remember_checkbox = ft.Checkbox(label="Запомнить меня", value=True)
    error_text = ft.Text("", color="#ff5252", size=12)
    title_text = ft.Text("Вход", size=22, weight=ft.FontWeight.BOLD, color="white")
    submit_btn = ft.ElevatedButton("Войти", bgcolor="#ffd54f", color="#12121a")
    loading_ring = ft.ProgressRing(width=20, height=20, stroke_width=3, color="#ffd54f", visible=False)
    switch_btn = ft.TextButton("Нет аккаунта? Зарегистрироваться")

    def update_admin_field(e=None):
        show_it = mode["value"] == "register" and (username_field.value or "").strip().lower() == ADMIN_USERNAME
        admin_code_field.visible = show_it
        page.update()

    username_field.on_change = update_admin_field

    def switch_mode(e):
        mode["value"] = "register" if mode["value"] == "login" else "login"
        title_text.value = "Регистрация" if mode["value"] == "register" else "Вход"
        submit_btn.text = "Зарегистрироваться" if mode["value"] == "register" else "Войти"
        switch_btn.text = "Уже есть аккаунт? Войти" if mode["value"] == "register" else "Нет аккаунта? Зарегистрироваться"
        error_text.value = ""
        update_admin_field()

    switch_btn.on_click = switch_mode

    def do_submit(e):
        uname_raw = (username_field.value or "").strip()
        pwd = password_field.value or ""

        if not uname_raw or not pwd:
            error_text.value = "Заполни ник и пароль"
            page.update()
            return
        if len(pwd) < 6:
            error_text.value = "Пароль должен быть не короче 6 символов"
            page.update()
            return

        if mode["value"] == "register" and uname_raw.lower() == ADMIN_USERNAME and (admin_code_field.value or "") != ADMIN_SECRET_CODE:
            error_text.value = "Неверный код администратора"
            page.update()
            return

        submit_btn.disabled = True
        submit_btn.text = "Подключаюсь..."
        loading_ring.visible = True
        error_text.value = ""
        page.update()

        if mode["value"] == "register":
            result, err = firebase_sign_up(uname_raw, pwd)
        else:
            result, err = firebase_sign_in(uname_raw, pwd)

        loading_ring.visible = False

        if err:
            error_text.value = friendly_auth_error(err)
            submit_btn.disabled = False
            submit_btn.text = "Зарегистрироваться" if mode["value"] == "register" else "Войти"
            page.update()
            return

        id_token = result["idToken"]
        uid = result["localId"]

        session_data = {"username": uname_raw, "remember": remember_checkbox.value}
        if remember_checkbox.value:
            session_data["password"] = pwd
        page.client_storage.set(SESSION_KEY, json.dumps(session_data))

        page.controls.clear()
        safe_run(page, lambda: build_game(page, uname_raw, uid, id_token))

    submit_btn.on_click = do_submit

    page.controls.clear()
    page.scroll = None
    page.add(
        ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=14,
            controls=[
                ft.Container(height=60),
                ft.Text("💰", size=60),
                title_text,
                username_field,
                password_field,
                admin_code_field,
                remember_checkbox,
                error_text,
                submit_btn,
                loading_ring,
                switch_btn,
                ft.Text("Аккаунт облачный — работает на любом устройстве", size=10, color="#555"),
            ],
        )
    )
    page.update()


def build_game(page: ft.Page, username="guest", uid=None, id_token=None):
    state = {}

    def load_state():
        remote = firestore_load_state(id_token, uid) if uid and id_token else None
        if remote:
            d = default_state()
            d.update(remote)
            return d
        return default_state()

    def save_state():
        if uid and id_token:
            firestore_save_state(id_token, uid, username, state)

    state.update(load_state())

    if not state.get("created_at"):
        state["created_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # подтягиваем лимит энергии под текущее число перерождений (и для старых сохранений тоже)
    expected_energy_max = 100 + state["prestige_count"] * ENERGY_PER_PRESTIGE
    if state["energy_max"] < expected_energy_max:
        state["energy_max"] = expected_energy_max

    def upgrade_cost(base_cost, level):
        return int(base_cost * (1.15 ** level))

    # Все бонусы (престиж, скин, бустер) складываются, а не перемножаются —
    # иначе они накручивают друг друга и экономика идёт вразнос.
    def booster_bonus_fraction():
        if time.time() < state.get("booster_until", 0):
            return BOOSTER_MULT - 1  # x2 -> +100%
        return 0

    def base_click_power():
        power = 1
        for u in UPGRADES:
            lvl = state["owned_upgrades"].get(u["id"], 0)
            power += lvl * u["power"]
        return power

    def selected_skin_obj():
        return next((s for s in SKINS if s["id"] == state["selected_skin"]), SKINS[0])

    def skin_bonus(bonus_type):
        skin = selected_skin_obj()
        if skin.get("bonus_type") == bonus_type:
            return skin.get("bonus_value", 0)
        return 0

    def click_bonus_fraction():
        return state["prestige_points"] * PRESTIGE_BONUS_PER_POINT + skin_bonus("click_power") + booster_bonus_fraction()

    def passive_bonus_fraction():
        return state["prestige_points"] * PRESTIGE_BONUS_PER_POINT + skin_bonus("passive") + booster_bonus_fraction()

    def total_click_power():
        return base_click_power() * (1 + click_bonus_fraction())

    def total_passive_income():
        income = 0
        for p in PASSIVE:
            lvl = state["owned_passive"].get(p["id"], 0)
            income += lvl * p["income"]
        return income * (1 + passive_bonus_fraction())

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

    def add_run_click():
        state["since_prestige_clicks"] += 1

    def add_run_upgrade():
        state["since_prestige_upgrades"] += 1

    # ---------- офлайн-прогресс ----------
    offline_gain = 0

    def apply_offline_progress():
        nonlocal offline_gain
        now = time.time()
        elapsed = max(0, now - state.get("last_tick", now))
        elapsed_capped = min(elapsed, 8 * 3600)
        offline_mult = current_league().get("offline_mult", 0.5)
        income_per_sec = (total_passive_income() / 3600) * offline_mult
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
    combo_text = ft.Text("", size=12, color="#ff8a65")

    COMBO_WINDOW = 1.2   # секунд между кликами, чтобы комбо не сбрасывалось
    COMBO_STEP = 0.015   # +1.5% за каждый клик в комбо
    COMBO_CAP = 20        # максимум +30%
    combo_state = {"count": 0, "last_time": 0}

    def combo_fraction():
        return min(combo_state["count"], COMBO_CAP) * COMBO_STEP

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
        if state["energy"] < 1 and not state.get("admin_unlimited"):
            return
        if not state.get("admin_unlimited"):
            state["energy"] -= 1
        state["total_clicks"] += 1
        add_run_click()

        now = time.time()
        if now - combo_state["last_time"] < COMBO_WINDOW:
            combo_state["count"] += 1
        else:
            combo_state["count"] = 1
        combo_state["last_time"] = now

        power = total_click_power() * (1 + combo_fraction())
        if state.get("admin_god_mode"):
            power *= 100
        is_crit = random.random() < (CRIT_CHANCE + skin_bonus("crit_chance"))
        gained = power * CRIT_MULT if is_crit else power
        add_points(gained)

        if combo_state["count"] > 1:
            combo_text.value = f"🔥 Комбо x{min(combo_state['count'], COMBO_CAP)} (+{int(combo_fraction() * 100)}%)"
        else:
            combo_text.value = ""

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
                add_run_upgrade()
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
                add_run_upgrade()
                save_state()
                render_shop()
                refresh_top()
        return handler

    def do_prestige(e):
        if state["since_prestige_points"] < PRESTIGE_THRESHOLD:
            return
        gained_pp = int(state["since_prestige_points"] // PRESTIGE_THRESHOLD)
        state["prestige_points"] += gained_pp
        state["prestige_count"] += 1
        state["energy_max"] = 100 + state["prestige_count"] * ENERGY_PER_PRESTIGE
        state["since_prestige_points"] = 0
        state["since_prestige_clicks"] = 0
        state["since_prestige_upgrades"] = 0
        state["points"] = 0
        state["owned_upgrades"] = {}
        state["owned_passive"] = {}
        state["energy"] = state["energy_max"]
        state["claimed_quests"] = []
        save_state()
        render_shop()
        render_quests()
        refresh_top()
        show_info_dialog("Перерождение!", f"Получено очков перерождения: +{gained_pp}\nТекущий бонус: +{int(state['prestige_points'] * PRESTIGE_BONUS_PER_POINT * 100)}% к доходу\nЛимит энергии: {state['energy_max']}\nЗадания снова открыты (стали сложнее)")

    shop_column = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO)

    promo_field = ft.TextField(label="Промокод", width=180, color="white", border_color="#3a3a45")

    def redeem_promo(e):
        code = (promo_field.value or "").strip().upper()
        if not code:
            return
        if code in state["used_promocodes"]:
            show_info_dialog("Промокод", "Этот промокод уже использован")
            return
        if code not in PROMOCODES:
            show_info_dialog("Промокод", "Неверный промокод")
            return
        reward = PROMOCODES[code]
        if "points" in reward:
            add_points(reward["points"])
        if reward.get("energy_full"):
            state["energy"] = state["energy_max"]
        state["used_promocodes"].append(code)
        promo_field.value = ""
        save_state()
        refresh_top()
        show_info_dialog("Промокод активирован!", f"Код {code} успешно применён")

    promo_button = ft.ElevatedButton("Активировать", on_click=redeem_promo, bgcolor="#4fc3f7", color="#12121a")

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

        shop_column.controls.append(
            ft.Container(
                padding=10, border_radius=10, bgcolor="#1e1e2a",
                content=ft.Row(controls=[promo_field, promo_button]),
            )
        )

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
        # достижения — считают за всю игру (никогда не сбрасываются)
        if entry["type"] == "clicks":
            return state["total_clicks"]
        if entry["type"] == "lifetime_points":
            return state["lifetime_points"]
        if entry["type"] == "upgrades_bought":
            return state["upgrades_bought_count"]
        # квесты — считают только с последнего перерождения (сбрасываются и растут)
        if entry["type"] == "clicks_run":
            return state["since_prestige_clicks"]
        if entry["type"] == "points_run":
            return state["since_prestige_points"]
        if entry["type"] == "upgrades_run":
            return state["since_prestige_upgrades"]
        return 0

    def claim_entry(entry, claimed_list_key, on_done):
        def handler(e):
            if entry["id"] in state[claimed_list_key]:
                return
            if progress_value(entry) >= entry["target"]:
                if entry.get("reward_type") == "energy":
                    state["energy"] = state["energy_max"]
                else:
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
                        ft.Text(
                            "Награда: полная энергия ⚡" if entry.get("reward_type") == "energy" else f"Награда: {entry['reward']} 💰",
                            size=11, color="#ffd54f"
                        ),
                    ]),
                    status,
                ],
            ),
        )

    def render_quests():
        quests_column.controls.clear()
        quests_column.controls.append(ft.Text(f"Задания (забег #{state['prestige_count'] + 1})", size=16, weight=ft.FontWeight.BOLD, color="white"))
        for q in build_quests(state["prestige_count"]):
            quests_column.controls.append(entry_row(q, "claimed_quests", render_quests))
        quests_column.controls.append(ft.Divider(color="#2a2a35"))
        quests_column.controls.append(ft.Text("Достижения (навсегда)", size=16, weight=ft.FontWeight.BOLD, color="white"))
        for a in ACHIEVEMENTS:
            quests_column.controls.append(entry_row(a, "claimed_achievements", render_quests))
        page.update()

    def unclaimed_ready_count():
        count = 0
        for q in build_quests(state["prestige_count"]):
            if q["id"] not in state["claimed_quests"] and progress_value(q) >= q["target"]:
                count += 1
        for a in ACHIEVEMENTS:
            if a["id"] not in state["claimed_achievements"] and progress_value(a) >= a["target"]:
                count += 1
        return count

    def update_quest_badge():
        n = unclaimed_ready_count()
        quests_badge_text.value = f"📋 Задания ({n})" if n > 0 else "📋 Задания"

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
                            ft.Column(spacing=2, controls=[
                                ft.Row(controls=[ft.Text(s["emoji"], size=28), ft.Text(s["name"], size=14, color="white")]),
                                ft.Text(s.get("bonus_desc", ""), size=11, color="#9e9e9e"),
                            ]),
                            btn,
                        ],
                    ),
                )
            )
        page.update()

    render_shop()
    render_quests()
    render_skins()

    # ---------- Кейсы ----------
    cases_column = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO)

    def weighted_choice(rewards):
        total_w = sum(r["weight"] for r in rewards)
        roll = random.uniform(0, total_w)
        upto = 0
        for reward in rewards:
            upto += reward["weight"]
            if roll <= upto:
                return reward
        return rewards[-1]

    def apply_case_reward(reward):
        if reward["type"] == "points":
            add_points(reward["amount"])
        elif reward["type"] == "energy_full":
            state["energy"] = state["energy_max"]
        elif reward["type"] == "energy_add":
            state["energy"] = min(state["energy_max"], state["energy"] + reward["amount"])
        elif reward["type"] == "booster":
            state["booster_until"] = max(state.get("booster_until", 0), time.time()) + reward["seconds"]
        elif reward["type"] == "prestige_points":
            state["prestige_points"] += reward["amount"]

    def case_opens_today(case_id):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rec = state["case_opens"].get(case_id)
        if not rec or rec.get("date") != today:
            return 0
        return rec.get("count", 0)

    def register_case_open(case_id):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rec = state["case_opens"].get(case_id)
        if not rec or rec.get("date") != today:
            state["case_opens"][case_id] = {"date": today, "count": 1}
        else:
            rec["count"] += 1
        state["total_cases_opened"] += 1

    def open_case(case):
        def handler(e):
            try:
                opened = case_opens_today(case["id"])
                if opened >= case["daily_limit"] and not state.get("admin_unlimited"):
                    show_info_dialog("Кейсы", f"Дневной лимит для «{case['name']}» исчерпан ({case['daily_limit']}/день). Заходи завтра!")
                    return
                if state["points"] < case["cost"] and not state.get("admin_unlimited"):
                    show_info_dialog("Кейсы", "Не хватает очков на этот кейс")
                    return
                if not state.get("admin_unlimited"):
                    state["points"] -= case["cost"]
                register_case_open(case["id"])
                reward = weighted_choice(case["rewards"])
                apply_case_reward(reward)
                save_state()
                render_cases()
                refresh_top()
                show_case_reward_dialog(case, reward)
            except Exception as ex:
                show_info_dialog("Ошибка открытия кейса", str(ex))
        return handler

    def render_cases():
        cases_column.controls.clear()
        cases_column.controls.append(ft.Text("Кейсы", size=16, weight=ft.FontWeight.BOLD, color="white"))
        for c in CASES:
            opened = case_opens_today(c["id"])
            left = c["daily_limit"] - opened
            btn_disabled = left <= 0
            total_w = sum(r["weight"] for r in c["rewards"])
            possible = ", ".join(f"{r['label']} ({round(r['weight'] / total_w * 100)}%)" for r in c["rewards"])
            cases_column.controls.append(
                ft.Container(
                    padding=10, border_radius=10, bgcolor="#1e1e2a",
                    content=ft.Column(spacing=6, controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Column(spacing=2, controls=[
                                    ft.Row(controls=[ft.Text(c["emoji"], size=26), ft.Text(c["name"], size=14, color="white")]),
                                    ft.Text(f"Осталось сегодня: {max(0, left)}/{c['daily_limit']}", size=11, color="#9e9e9e"),
                                ]),
                                ft.ElevatedButton(
                                    "Лимит" if btn_disabled else f"{c['cost']} 💰",
                                    on_click=None if btn_disabled else open_case(c),
                                    disabled=btn_disabled,
                                    bgcolor="#3a3a45" if btn_disabled else "#4fc3f7",
                                    color="#777" if btn_disabled else "#12121a",
                                ),
                            ],
                        ),
                        ft.Text(f"Возможно: {possible}", size=10, color="#7a7a85"),
                    ]),
                )
            )
        page.update()

    render_cases()

    # ---------- Вкладки ----------
    tabs_content = ft.Container(content=shop_column, height=260, width=320, padding=10)

    def show_shop(e=None):
        tabs_content.content = shop_column
        render_shop()
        page.update()

    def show_quests(e=None):
        tabs_content.content = quests_column
        render_quests()
        page.update()

    def show_skins(e=None):
        tabs_content.content = skins_column
        render_skins()
        page.update()

    def show_cases(e=None):
        tabs_content.content = cases_column
        render_cases()
        page.update()

    stats_column = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO)

    def stat_row(label, value):
        return ft.Container(
            padding=10, border_radius=10, bgcolor="#1e1e2a",
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[ft.Text(label, size=13, color="#9e9e9e"), ft.Text(str(value), size=14, weight=ft.FontWeight.BOLD, color="white")],
            ),
        )

    def render_stats():
        stats_column.controls.clear()
        stats_column.controls.append(ft.Text("Статистика", size=16, weight=ft.FontWeight.BOLD, color="white"))
        total_achievements = len(ACHIEVEMENTS)
        claimed_achievements = len(state["claimed_achievements"])
        stats_column.controls.append(stat_row("Игрок с", state.get("created_at", "—")))
        stats_column.controls.append(stat_row("Всего кликов", int(state["total_clicks"])))
        stats_column.controls.append(stat_row("Заработано очков (всего)", int(state["lifetime_points"])))
        stats_column.controls.append(stat_row("Текущая лига", current_league()["name"]))
        stats_column.controls.append(stat_row("Перерождений", state["prestige_count"]))
        stats_column.controls.append(stat_row("Очков перерождения", state["prestige_points"]))
        stats_column.controls.append(stat_row("Кейсов открыто", state["total_cases_opened"]))
        stats_column.controls.append(stat_row("Достижений получено", f"{claimed_achievements}/{total_achievements}"))
        stats_column.controls.append(stat_row("Улучшений куплено", state["upgrades_bought_count"]))
        stats_column.controls.append(stat_row("Дней подряд (стрик)", state["streak"]))
        page.update()

    def show_stats(e=None):
        tabs_content.content = stats_column
        render_stats()
        page.update()

    # ---------- Таблица лидеров (из облака, видна всем) ----------
    leaderboard_column = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO)

    def render_leaderboard():
        leaderboard_column.controls.clear()
        leaderboard_column.controls.append(
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                ft.Text("🏆 Топ игроков", size=16, weight=ft.FontWeight.BOLD, color="white"),
                ft.TextButton("Обновить", on_click=lambda e: render_leaderboard()),
            ])
        )
        players = firestore_leaderboard(limit=20)
        if not players:
            leaderboard_column.controls.append(ft.Text("Пока никого нет или нет сети", size=12, color="#9e9e9e"))
        else:
            medals = ["🥇", "🥈", "🥉"]
            for i, p in enumerate(players):
                place = medals[i] if i < 3 else f"{i + 1}."
                is_me = p["nickname"].lower() == username.lower()
                leaderboard_column.controls.append(
                    ft.Container(
                        padding=10, border_radius=10, bgcolor="#2a2140" if is_me else "#1e1e2a",
                        content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                            ft.Text(f"{place} {p['nickname']}", size=13, color="white"),
                            ft.Text(f"{p['league']} · {p['lifetime_points']} 💰", size=12, color="#ffd54f"),
                        ]),
                    )
                )
        page.update()

    def show_leaderboard(e=None):
        tabs_content.content = leaderboard_column
        render_leaderboard()
        page.update()

    # ---------- Админ-панель (видна только на аккаунте admin) ----------
    admin_column = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO)

    def toggle_unlimited(e):
        state["admin_unlimited"] = not state.get("admin_unlimited")
        save_state()
        render_admin()
        refresh_top()

    def toggle_god_mode(e):
        state["admin_god_mode"] = not state.get("admin_god_mode")
        save_state()
        render_admin()

    def admin_grant_points(amount):
        def handler(e):
            add_points(amount)
            save_state()
            refresh_top()
            render_admin()
        return handler

    def admin_grant_prestige(amount):
        def handler(e):
            state["prestige_points"] += amount
            save_state()
            refresh_top()
            render_admin()
        return handler

    def admin_unlock_all_skins(e):
        max_needed = max(s["min_lifetime"] for s in SKINS)
        state["lifetime_points"] = max(state["lifetime_points"], max_needed)
        save_state()
        refresh_top()
        render_skins()
        render_admin()

    def render_admin():
        admin_column.controls.clear()
        admin_column.controls.append(ft.Text("🛠 Админ-панель", size=16, weight=ft.FontWeight.BOLD, color="#ce93d8"))

        admin_column.controls.append(
            ft.Container(
                padding=10, border_radius=10, bgcolor="#1e1e2a",
                content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                    ft.Text("Безлимит (энергия + кейсы)", size=13, color="white"),
                    ft.Switch(value=state.get("admin_unlimited", False), on_change=toggle_unlimited),
                ]),
            )
        )
        admin_column.controls.append(
            ft.Container(
                padding=10, border_radius=10, bgcolor="#1e1e2a",
                content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                    ft.Text("Режим бога (x100 к клику)", size=13, color="white"),
                    ft.Switch(value=state.get("admin_god_mode", False), on_change=toggle_god_mode),
                ]),
            )
        )

        admin_column.controls.append(ft.Divider(color="#2a2a35"))
        admin_column.controls.append(ft.Text("Выдача", size=14, weight=ft.FontWeight.BOLD, color="white"))
        admin_column.controls.append(
            ft.Row(wrap=True, controls=[
                ft.ElevatedButton("+10000 💰", on_click=admin_grant_points(10000), bgcolor="#4fc3f7", color="#12121a"),
                ft.ElevatedButton("+100000 💰", on_click=admin_grant_points(100000), bgcolor="#4fc3f7", color="#12121a"),
                ft.ElevatedButton("+1 очко ✨", on_click=admin_grant_prestige(1), bgcolor="#ce93d8", color="#12121a"),
                ft.ElevatedButton("+10 очков ✨", on_click=admin_grant_prestige(10), bgcolor="#ce93d8", color="#12121a"),
                ft.ElevatedButton("Все скины 🎨", on_click=admin_unlock_all_skins, bgcolor="#ffd54f", color="#12121a"),
            ])
        )

        admin_column.controls.append(ft.Divider(color="#2a2a35"))
        admin_column.controls.append(ft.Text("Сырое сохранение (JSON)", size=14, weight=ft.FontWeight.BOLD, color="white"))
        admin_column.controls.append(
            ft.Container(
                padding=10, border_radius=10, bgcolor="#0d0d12",
                content=ft.Text(json.dumps(state, indent=2, ensure_ascii=False), size=9, color="#9e9e9e", selectable=True),
            )
        )

        admin_column.controls.append(ft.Divider(color="#2a2a35"))
        admin_column.controls.append(
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                ft.Text("Все игроки (из облака)", size=14, weight=ft.FontWeight.BOLD, color="white"),
                ft.TextButton("Обновить", on_click=lambda e: render_admin()),
            ])
        )
        players = firestore_leaderboard(limit=100)
        if not players:
            admin_column.controls.append(ft.Text("Пока никого нет или нет сети", size=12, color="#9e9e9e"))
        else:
            for i, p in enumerate(players, 1):
                admin_column.controls.append(
                    ft.Container(
                        padding=8, border_radius=8, bgcolor="#1e1e2a",
                        content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                            ft.Text(f"{i}. {p['nickname']}", size=12, color="white"),
                            ft.Text(f"{p['league']} · {p['lifetime_points']} 💰 · ✨{p['prestige_count']}", size=11, color="#9e9e9e"),
                        ]),
                    )
                )
        page.update()

    def show_admin(e=None):
        tabs_content.content = admin_column
        render_admin()
        page.update()

    # ---------- Стилизованные вкладки-чипы с подсветкой активной ----------
    active_tab_key = {"value": "shop"}
    tab_chips = {}
    quests_badge_text = ft.Text("📋 Задания", size=13, weight=ft.FontWeight.BOLD)

    TAB_DEFS = [
        ("shop", ft.Text("🛒 Магазин", size=13, weight=ft.FontWeight.BOLD), show_shop),
        ("quests", quests_badge_text, show_quests),
        ("skins", ft.Text("🎨 Скины", size=13, weight=ft.FontWeight.BOLD), show_skins),
        ("cases", ft.Text("🎁 Кейсы", size=13, weight=ft.FontWeight.BOLD), show_cases),
        ("stats", ft.Text("📊 Стата", size=13, weight=ft.FontWeight.BOLD), show_stats),
        ("leaderboard", ft.Text("🏆 Лидеры", size=13, weight=ft.FontWeight.BOLD), show_leaderboard),
    ]
    if username == ADMIN_USERNAME:
        TAB_DEFS.append(("admin", ft.Text("🛠 Админ", size=13, weight=ft.FontWeight.BOLD), show_admin))

    def refresh_tab_styles():
        for key, container in tab_chips.items():
            is_active = key == active_tab_key["value"]
            container.bgcolor = "#ffd54f" if is_active else "#1e1e2a"
            container.content.color = "#12121a" if is_active else "#9e9e9e"
        page.update()

    def make_tab_handler(key, original_handler):
        def handler(e=None):
            active_tab_key["value"] = key
            original_handler(e)
            refresh_tab_styles()
        return handler

    tab_chip_controls = []
    for key, label_control, handler in TAB_DEFS:
        wrapped_handler = make_tab_handler(key, handler)
        chip = ft.Container(
            content=label_control,
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            border_radius=20,
            bgcolor="#ffd54f" if key == "shop" else "#1e1e2a",
            on_click=wrapped_handler,
            ink=True,
        )
        label_control.color = "#12121a" if key == "shop" else "#9e9e9e"
        tab_chips[key] = chip
        tab_chip_controls.append(chip)

    tab_buttons = ft.Row(
        alignment=ft.MainAxisAlignment.CENTER,
        wrap=True,
        spacing=8,
        run_spacing=8,
        controls=tab_chip_controls,
    )

    # ---------- Сброс прогресса ----------
    def confirm_reset(e):
        def do_reset(e2):
            state.clear()
            state.update(default_state())
            save_state()
            coin_text.value = current_skin_emoji()
            render_shop()
            render_quests()
            render_skins()
            refresh_top()
            page.dialog.open = False
            page.update()

        def cancel(e2):
            page.dialog.open = False
            page.update()

        page.dialog = ft.AlertDialog(
            title=ft.Text("Сбросить прогресс?"),
            content=ft.Text("Весь прогресс будет удалён без возможности восстановить."),
            actions=[ft.TextButton("Отмена", on_click=cancel), ft.TextButton("Сбросить", on_click=do_reset)],
        )
        page.dialog.open = True
        page.update()

    settings_btn = ft.IconButton(icon=ft.Icons.SETTINGS, icon_color="#666", on_click=confirm_reset)

    def do_logout(e):
        page.client_storage.set(SESSION_KEY, json.dumps({"username": None, "remember": False}))
        page.controls.clear()
        page.scroll = None
        safe_run(page, lambda: show_auth_screen(page))

    logout_btn = ft.IconButton(icon=ft.Icons.LOGOUT, icon_color="#666", on_click=do_logout)

    # ---------- Автотик ----------
    def tick_loop():
        while True:
            time.sleep(1)
            now = time.time()
            elapsed = now - state.get("last_tick", now)
            state["energy"] = min(state["energy_max"], state["energy"] + elapsed / 3)
            add_points((total_passive_income() / 3600) * elapsed)
            state["last_tick"] = now
            if combo_state["count"] > 0 and now - combo_state["last_time"] > COMBO_WINDOW:
                combo_state["count"] = 0
                combo_text.value = ""
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

    def show_info_dialog(title, text):
        dlg = ft.AlertDialog(title=ft.Text(title), content=ft.Text(text), actions=[ft.TextButton("Ок", on_click=close_dialog)])
        page.dialog = dlg
        dlg.open = True
        page.update()

    def show_case_reward_dialog(case, reward):
        dlg = ft.AlertDialog(
            title=ft.Text(f"{case['emoji']} {case['name']} открыт!", size=16, weight=ft.FontWeight.BOLD),
            content=ft.Column(
                spacing=6,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Text("Вы получили:", size=13, color="#9e9e9e"),
                    ft.Text(reward["label"], size=24, weight=ft.FontWeight.BOLD, color="#ffd54f"),
                ],
            ),
            actions=[ft.ElevatedButton("Забрать", on_click=close_dialog, bgcolor="#ffd54f", color="#12121a")],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    if offline_gain > 1:
        dialogs_queue.append(
            ft.AlertDialog(
                title=ft.Text("Пока тебя не было"),
                content=ft.Text(f"Ферма накопила: +{int(offline_gain)} 💰\n(офлайн-множитель твоей лиги: x{current_league().get('offline_mult', 0.5)})"),
                actions=[ft.TextButton("Ок", on_click=close_dialog)],
            )
        )

    if daily_result:
        bonus, streak, gave_booster = daily_result
        text = f"День подряд: {streak}\nПолучено: +{bonus} 💰"
        if gave_booster:
            text += f"\n⚡ Бонус: бустер x{BOOSTER_MULT} на {BOOSTER_DURATION // 60} мин!"
        dialogs_queue.append(
            ft.AlertDialog(
                title=ft.Text("Ежедневный бонус!"),
                content=ft.Text(text),
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
    display_name = username.upper() if username == ADMIN_USERNAME else username
    user_label = ft.Text(f"👑 {display_name}" if username == ADMIN_USERNAME else display_name, size=12, color="#ce93d8" if username == ADMIN_USERNAME else "#9e9e9e")
    header_row = ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        controls=[logout_btn, ft.Column(spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[league_text, user_label]), settings_btn],
    )

    page.add(
        ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=6,
            controls=[
                ft.Container(height=10),
                header_row,
                league_progress,
                league_sub_text,
                points_text,
                power_text,
                passive_text,
                booster_text,
                combo_text,
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

    update_quest_badge()
    page.update()
    show_next_dialog()


ft.app(target=main)
