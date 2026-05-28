#!/usr/bin/env python3
import os
import sqlite3
import logging
import json
import datetime
import anthropic

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ADMIN_ID          = int(os.environ.get("ADMIN_ID", "0"))

DB_PATH = "nauz_stats.db"

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

CHATTING = 0

SYSTEM_PROMPT = """Ты — интеллектуальный ассистент Национальной Ассоциации Управленцев Сферы Здравоохранения (НАУЗ, сайт: auz.clinic).

О НАУЗ:
НАУЗ — объединение лидеров-управленцев системы здравоохранения России.
Председатель — Муслим Муслимов, врач-хирург, к.м.н., член Общественной палаты РФ.

Цели НАУЗ:
- Сформировать профессиональное сообщество специалистов здравоохранения
- Создать систему повышения управленческих навыков
- Наладить постоянный диалог всех участников отрасли
- Отобрать лучших в кадровый резерв
- Открыть аналитический центр
- Разработать рейтинговую систему эффективности медуправления
- Объединить управленческие кейсы российской и зарубежной медицины

Твоя роль:
Проводи глубокое интервью с управленцами здравоохранения. Задавай по ОДНОМУ вопросу за раз. После 10 вопросов предложи сформировать отчёт.

Темы: должность, тип организации, стратегические приоритеты, проблемы управления, цифровизация, кадры, финансы, регуляторы, обучение, ожидания от НАУЗ.

Стиль: профессиональный, экспертный, доброжелательный.
Язык: отвечай на том языке, на котором пишет пользователь."""

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ── База данных ──────────────────────────────────────────────────────────────

def db_init():
    with sqlite3.connect(DB_PATH) as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                first_name  TEXT,
                first_seen  TEXT NOT NULL,
                last_active TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER NOT NULL,
                started_at   TEXT NOT NULL,
                ended_at     TEXT,
                msg_count    INTEGER DEFAULT 0,
                got_report   INTEGER DEFAULT 0
            );
        """)


def db_upsert_user(user_id: int, username: str, first_name: str):
    now = datetime.datetime.now().isoformat()
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            INSERT INTO users (user_id, username, first_name, first_seen, last_active)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username    = excluded.username,
                first_name  = excluded.first_name,
                last_active = excluded.last_active
        """, (user_id, username, first_name, now, now))


def db_start_session(user_id: int) -> int:
    now = datetime.datetime.now().isoformat()
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute(
            "INSERT INTO sessions (user_id, started_at) VALUES (?, ?)", (user_id, now)
        )
        return cur.lastrowid


def db_update_session(session_id: int, msg_count: int, got_report: bool = False):
    now = datetime.datetime.now().isoformat()
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            UPDATE sessions
            SET msg_count = ?, got_report = ?, ended_at = ?
            WHERE id = ?
        """, (msg_count, int(got_report), now, session_id))


def db_touch_user(user_id: int):
    now = datetime.datetime.now().isoformat()
    with sqlite3.connect(DB_PATH) as con:
        con.execute("UPDATE users SET last_active = ? WHERE user_id = ?", (now, user_id))


def db_get_stats() -> dict:
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        total_users    = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_sessions = con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        total_reports  = con.execute("SELECT COUNT(*) FROM sessions WHERE got_report = 1").fetchone()[0]
        avg_msgs       = con.execute("SELECT AVG(msg_count) FROM sessions WHERE msg_count > 0").fetchone()[0]

        today = datetime.date.today().isoformat()
        new_today = con.execute(
            "SELECT COUNT(*) FROM users WHERE first_seen >= ?", (today,)
        ).fetchone()[0]
        sessions_today = con.execute(
            "SELECT COUNT(*) FROM sessions WHERE started_at >= ?", (today,)
        ).fetchone()[0]

        week_ago = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
        active_week = con.execute(
            "SELECT COUNT(DISTINCT user_id) FROM sessions WHERE started_at >= ?", (week_ago,)
        ).fetchone()[0]

        last_users = con.execute("""
            SELECT first_name, username, last_active
            FROM users ORDER BY last_active DESC LIMIT 5
        """).fetchall()

    return {
        "total_users":     total_users,
        "total_sessions":  total_sessions,
        "total_reports":   total_reports,
        "avg_msgs":        round(avg_msgs or 0, 1),
        "new_today":       new_today,
        "sessions_today":  sessions_today,
        "active_week":     active_week,
        "last_users":      [dict(r) for r in last_users],
    }


# ── AI ───────────────────────────────────────────────────────────────────────

def ai_response(history: list) -> str:
    try:
        resp = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=1200,
            system=SYSTEM_PROMPT,
            messages=history,
        )
        return resp.content[0].text
    except Exception as e:
        logger.error(f"Anthropic API error: {e}")
        return "Техническая ошибка. Попробуйте ещё раз или введите /start."


def save_dialog(user_id, username, history):
    try:
        filename = f"dialog_{user_id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        data = {"user_id": user_id, "username": username, "timestamp": datetime.datetime.now().isoformat(), "history": history}
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Save error: {e}")


# ── Хендлеры ─────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    context.user_data.clear()
    context.user_data["history"] = []
    context.user_data["q_count"] = 0
    context.user_data["report_offered"] = False

    db_upsert_user(user.id, user.username or "", user.first_name or "")
    session_id = db_start_session(user.id)
    context.user_data["session_id"] = session_id

    welcome = (
        f"Здравствуйте, {user.first_name}!\n\n"
        "Добро пожаловать в чат-бот\n"
        "Национальной Ассоциации Управленцев Сферы Здравоохранения (НАУЗ)\n\n"
        "Я помогу определить ваши управленческие цели, выявить проблемы и подготовить отчёт.\n\n"
        "/report — итоговый отчёт\n"
        "/restart — начать заново\n\n"
        "Начнём?"
    )
    await update.message.reply_text(welcome)

    init = [{"role": "user", "content": "Начни интервью. Кратко представься от имени НАУЗ и задай первый вопрос о должности собеседника."}]
    first_q = ai_response(init)

    context.user_data["history"] = [
        {"role": "user", "content": "Начни интервью. Кратко представься от имени НАУЗ и задай первый вопрос о должности собеседника."},
        {"role": "assistant", "content": first_q},
    ]
    context.user_data["q_count"] = 1
    await update.message.reply_text(first_q)
    return CHATTING


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_text = update.message.text.strip()
    if not user_text:
        return CHATTING

    history  = context.user_data.get("history", [])
    q_count  = context.user_data.get("q_count", 0)
    user     = update.effective_user

    history.append({"role": "user", "content": user_text})
    await update.message.chat.send_action("typing")

    if q_count >= 10 and not context.user_data.get("report_offered", False):
        history.append({"role": "user", "content": "[ИНСТРУКЦИЯ: Задано 10+ вопросов. Поблагодари и предложи сформировать итоговый отчёт.]"})
        context.user_data["report_offered"] = True

    response = ai_response(history)
    history.append({"role": "assistant", "content": response})
    context.user_data["history"] = history
    context.user_data["q_count"] = q_count + 1

    db_touch_user(user.id)
    db_update_session(context.user_data.get("session_id", 0), context.user_data["q_count"])

    if context.user_data["q_count"] % 5 == 0:
        save_dialog(user.id, user.username or "unknown", history)

    await update.message.reply_text(response)
    return CHATTING


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    history = context.user_data.get("history", [])
    user    = update.effective_user

    if len(history) < 4:
        await update.message.reply_text("Для отчёта нужно ответить хотя бы на несколько вопросов.")
        return CHATTING

    await update.message.reply_text("Формирую ваш персональный отчёт...")
    await update.message.chat.send_action("typing")

    history.append({"role": "user", "content": "Сформируй подробный итоговый отчёт на основе нашего диалога с заголовками и рекомендациями по взаимодействию с НАУЗ."})
    report_text = ai_response(history)
    history.append({"role": "assistant", "content": report_text})
    context.user_data["history"] = history
    save_dialog(user.id, user.username or "unknown", history)

    db_touch_user(user.id)
    db_update_session(
        context.user_data.get("session_id", 0),
        context.user_data.get("q_count", 0),
        got_report=True,
    )

    await update.message.reply_text(f"ИТОГОВЫЙ ОТЧЁТ\n\n{report_text}")
    await update.message.reply_text("Отчёт готов! Спасибо за участие в опросе НАУЗ!\nhttps://auz.clinic")
    return CHATTING


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Начинаем сначала...")
    return await start(update, context)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if ADMIN_ID and user.id != ADMIN_ID:
        await update.message.reply_text("Нет доступа.")
        return

    s = db_get_stats()

    last_lines = ""
    for u in s["last_users"]:
        name = u["first_name"] or "—"
        uname = f"@{u['username']}" if u["username"] else ""
        ts = u["last_active"][:16].replace("T", " ")
        last_lines += f"  • {name} {uname} ({ts})\n"

    text = (
        "📊 Статистика НАУЗ-бота\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Всего пользователей:  {s['total_users']}\n"
        f"🆕 Новых сегодня:        {s['new_today']}\n"
        f"🔥 Активных за неделю:   {s['active_week']}\n"
        "\n"
        f"💬 Всего сессий:         {s['total_sessions']}\n"
        f"📅 Сессий сегодня:       {s['sessions_today']}\n"
        f"📝 Отчётов сформировано: {s['total_reports']}\n"
        f"📨 Среднее сообщ/сессия: {s['avg_msgs']}\n"
        "\n"
        "🕐 Последние активные:\n"
        f"{last_lines}"
    )
    await update.message.reply_text(text)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Ошибка: {context.error}", exc_info=context.error)


def main() -> None:
    db_init()
    logger.info("Запуск бота НАУЗ...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHATTING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
                CommandHandler("report", report),
                CommandHandler("restart", restart),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("stats", stats))
    app.add_error_handler(error_handler)
    logger.info("Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
