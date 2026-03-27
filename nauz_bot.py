#!/usr/bin/env python3
import os
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    context.user_data.clear()
    context.user_data["history"] = []
    context.user_data["q_count"] = 0
    context.user_data["report_offered"] = False

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

    history = context.user_data.get("history", [])
    q_count = context.user_data.get("q_count", 0)
    user = update.effective_user

    history.append({"role": "user", "content": user_text})
    await update.message.chat.send_action("typing")

    if q_count >= 10 and not context.user_data.get("report_offered", False):
        history.append({"role": "user", "content": "[ИНСТРУКЦИЯ: Задано 10+ вопросов. Поблагодари и предложи сформировать итоговый отчёт.]"})
        context.user_data["report_offered"] = True

    response = ai_response(history)
    history.append({"role": "assistant", "content": response})
    context.user_data["history"] = history
    context.user_data["q_count"] = q_count + 1

    if context.user_data["q_count"] % 5 == 0:
        save_dialog(user.id, user.username or "unknown", history)

    await update.message.reply_text(response)
    return CHATTING


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    history = context.user_data.get("history", [])
    user = update.effective_user

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

    await update.message.reply_text(f"ИТОГОВЫЙ ОТЧЁТ\n\n{report_text}")
    await update.message.reply_text("Отчёт готов! Спасибо за участие в опросе НАУЗ!\nhttps://auz.clinic")
    return CHATTING


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Начинаем сначала...")
    return await start(update, context)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Ошибка: {context.error}", exc_info=context.error)


def main() -> None:
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
    app.add_error_handler(error_handler)
    logger.info("Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
