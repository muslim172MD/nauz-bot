#!/usr/bin/env python3
"""Telegram-бот НАУЗ.

Бот проводит структурированное интервью с управленцами здравоохранения
и формирует итоговый профиль. Конфигурация передаётся только через
переменные окружения.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import anthropic
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

CHATTING = 0

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-5")

SAVE_DIALOGS = os.getenv("SAVE_DIALOGS", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DIALOGS_DIR = Path(os.getenv("DIALOGS_DIR", "data/dialogs"))

MAX_TELEGRAM_MESSAGE = 3900

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
)
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — интеллектуальный ассистент Национальной Ассоциации
Управленцев Сферы Здравоохранения (НАУЗ, сайт: auz.clinic).

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
Проводи глубокое интервью с управленцами здравоохранения.
Задавай по ОДНОМУ вопросу за раз. После 10 вопросов предложи сформировать отчёт.

Темы:
должность, тип организации, стратегические приоритеты, проблемы управления,
цифровизация, кадры, финансы, регуляторы, обучение, ожидания от НАУЗ.

Правила безопасности и приватности:
- Никогда не проси ФИО пациентов, номера историй болезни, полисы ОМС,
  СНИЛС, паспортные данные, телефоны, адреса, даты рождения или иные
  идентифицирующие данные пациентов.
- Если пользователь прислал данные пациента, не анализируй и не повторяй их.
  Попроси удалить идентификаторы и прислать обезличенную формулировку.
- Не утверждай, что данные сохранены, если сохранение отключено.
- Не выдавай медицинские рекомендации конкретному пациенту.

Стиль: профессиональный, экспертный, доброжелательный.
Язык: отвечай на том языке, на котором пишет пользователь.
"""

_PATIENT_DATA_PATTERNS = [
    # Явные медицинские/идентификационные маркеры.
    re.compile(r"\bснилс\b", re.IGNORECASE),
    re.compile(r"\bполис(?:а|ом)?\s+омс\b", re.IGNORECASE),
    re.compile(r"\bномер\s+истории\s+болезни\b", re.IGNORECASE),
    re.compile(r"\bпаспорт(?:ные|а)?\s+данн", re.IGNORECASE),
    re.compile(r"\bфио\s+пациент", re.IGNORECASE),
    re.compile(r"\bтелефон\s+пациент", re.IGNORECASE),
    re.compile(r"\bадрес\s+пациент", re.IGNORECASE),
    re.compile(r"\bдата\s+рождения\s+пациент", re.IGNORECASE),
    # Консервативные локальные шаблоны PII. Лучше остановить сообщение,
    # чем случайно отправить идентификатор во внешний API.
    re.compile(r"(?<!\d)\d{3}[- ]?\d{3}[- ]?\d{3}[- ]?\d{2}(?!\d)"),  # СНИЛС
    re.compile(r"(?<!\d)\d{16}(?!\d)"),  # типичный номер полиса ОМС
    re.compile(r"(?<!\d)\d{4}\s?\d{6}(?!\d)"),  # серия + номер паспорта
    re.compile(
        r"(?<!\d)(?:\+7|8)[ -]?(?:\(?\d{3}\)?)[ -]?\d{3}[ -]?\d{2}[ -]?\d{2}(?!\d)"
    ),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
]


def validate_config() -> None:
    """Проверить обязательные переменные окружения до запуска бота."""
    missing = []
    if not TELEGRAM_TOKEN:
        missing.append("TELEGRAM_TOKEN")
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if missing:
        raise RuntimeError(
            "Не заданы обязательные переменные окружения: " + ", ".join(missing)
        )


def contains_patient_identifiers(text: str) -> bool:
    """Консервативная проверка явных маркеров идентифицирующих данных пациента."""
    return any(pattern.search(text) for pattern in _PATIENT_DATA_PATTERNS)


def _client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)


async def ai_response(history: list[dict[str, str]], instruction: str | None = None) -> str:
    """Асинхронный запрос к Anthropic API без блокировки event loop."""
    system = SYSTEM_PROMPT
    if instruction:
        system = f"{system}\n\nДополнительная внутренняя инструкция:\n{instruction}"

    try:
        response = await _client().messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1200,
            system=system,
            messages=history,
        )
        if not response.content:
            return "Техническая ошибка: ИИ вернул пустой ответ."
        return response.content[0].text
    except anthropic.AuthenticationError:
        logger.exception("Ошибка авторизации Anthropic API")
        return "Техническая ошибка конфигурации ИИ. Сообщите администратору."
    except anthropic.APIConnectionError:
        logger.exception("Ошибка соединения с Anthropic API")
        return "Сервис ИИ временно недоступен. Попробуйте ещё раз позже."
    except Exception:
        logger.exception("Непредвиденная ошибка Anthropic API")
        return "Техническая ошибка. Попробуйте ещё раз или введите /start."


def save_dialog(user_id: int, username: str, history: list[dict[str, str]]) -> None:
    """Локально сохранить диалог только при явном SAVE_DIALOGS=true."""
    if not SAVE_DIALOGS:
        return

    try:
        DIALOGS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = DIALOGS_DIR / f"dialog_{user_id}_{timestamp}.json"
        data: dict[str, Any] = {
            "user_id": user_id,
            "username": username,
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "history": history,
        }
        filename.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            filename.chmod(0o600)
        except OSError:
            logger.warning("Не удалось установить права 0600 для %s", filename)
    except Exception:
        logger.exception("Ошибка локального сохранения диалога")


async def send_long_message(update: Update, text: str) -> None:
    """Отправить длинный текст несколькими сообщениями Telegram."""
    message = update.effective_message
    if message is None:
        return

    remaining = text.strip()
    while remaining:
        if len(remaining) <= MAX_TELEGRAM_MESSAGE:
            await message.reply_text(remaining)
            break

        split_at = remaining.rfind("\n", 0, MAX_TELEGRAM_MESSAGE)
        if split_at < MAX_TELEGRAM_MESSAGE // 2:
            split_at = remaining.rfind(" ", 0, MAX_TELEGRAM_MESSAGE)
        if split_at <= 0:
            split_at = MAX_TELEGRAM_MESSAGE

        chunk = remaining[:split_at].strip()
        remaining = remaining[split_at:].strip()
        await message.reply_text(chunk)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return CHATTING

    context.user_data.clear()
    context.user_data["history"] = []
    context.user_data["q_count"] = 0
    context.user_data["report_offered"] = False

    welcome = (
        f"Здравствуйте, {user.first_name}!\n\n"
        "Добро пожаловать в чат-бот Национальной Ассоциации Управленцев "
        "Сферы Здравоохранения (НАУЗ).\n\n"
        "Я помогу определить управленческие цели, выявить проблемы и "
        "подготовить итоговый профиль.\n\n"
        "Важно: не присылайте идентифицирующие данные пациентов "
        "(ФИО, СНИЛС, ОМС, паспорт, телефон, адрес, дату рождения).\n\n"
        "/report — итоговый отчёт\n"
        "/privacy — правила приватности\n"
        "/restart — начать заново\n"
        "/help — помощь\n\n"
        "Начнём?"
    )
    await message.reply_text(welcome)

    init = [
        {
            "role": "user",
            "content": (
                "Начни интервью. Кратко представься от имени НАУЗ и задай "
                "первый вопрос о должности и роли собеседника."
            ),
        }
    ]
    first_question = await ai_response(init)

    context.user_data["history"] = [
        init[0],
        {"role": "assistant", "content": first_question},
    ]
    context.user_data["q_count"] = 1

    await send_long_message(update, first_question)
    return CHATTING


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or not message.text:
        return CHATTING

    user_text = message.text.strip()
    if not user_text:
        return CHATTING

    if contains_patient_identifiers(user_text):
        await message.reply_text(
            "Я не буду передавать это сообщение во внешний ИИ: в нём похожи "
            "на идентифицирующие данные пациента. Удалите ФИО, номера документов, "
            "контакты, адрес, дату рождения и другие идентификаторы, затем "
            "пришлите обезличенную формулировку."
        )
        return CHATTING

    history = context.user_data.get("history", [])
    q_count = context.user_data.get("q_count", 0)

    history.append({"role": "user", "content": user_text})
    await message.chat.send_action("typing")

    instruction = None
    if q_count >= 10 and not context.user_data.get("report_offered", False):
        instruction = (
            "Задано 10 или более вопросов. Поблагодари за ответы и предложи "
            "либо продолжить интервью, либо сформировать итоговый отчёт командой /report."
        )
        context.user_data["report_offered"] = True

    response = await ai_response(history, instruction=instruction)
    history.append({"role": "assistant", "content": response})

    context.user_data["history"] = history
    context.user_data["q_count"] = q_count + 1

    if context.user_data["q_count"] % 5 == 0:
        save_dialog(user.id, user.username or "unknown", history)

    await send_long_message(update, response)
    return CHATTING


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return CHATTING

    history = context.user_data.get("history", [])
    if len(history) < 4:
        await message.reply_text(
            "Для содержательного отчёта нужно ответить хотя бы на несколько вопросов."
        )
        return CHATTING

    await message.reply_text("Формирую ваш персональный отчёт...")
    await message.chat.send_action("typing")

    report_text = await ai_response(
        history,
        instruction=(
            "Сформируй подробный итоговый отчёт на основе диалога. "
            "Структура: профиль управленца; проблемы и потребности; цели и "
            "приоритеты; рекомендации по взаимодействию с НАУЗ; конкретные "
            "следующие шаги. Не включай идентифицирующие данные пациентов."
        ),
    )
    history.append({"role": "assistant", "content": report_text})
    context.user_data["history"] = history

    save_dialog(user.id, user.username or "unknown", history)

    await send_long_message(update, f"ИТОГОВЫЙ ОТЧЁТ\n\n{report_text}")
    if SAVE_DIALOGS:
        await message.reply_text(
            "Отчёт готов. Локальное сохранение диалогов включено администратором."
        )
    else:
        await message.reply_text(
            "Отчёт готов. Локальное сохранение диалогов в приложении отключено."
        )
    return CHATTING


async def privacy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    del context
    message = update.effective_message
    if message is None:
        return CHATTING

    text = (
        "ПРИВАТНОСТЬ\n\n"
        "• Не присылайте идентифицирующие данные пациентов.\n"
        "• Сообщения с явными маркерами таких данных не отправляются в ИИ.\n"
        "• Локальное сохранение диалогов по умолчанию отключено.\n"
        "• Для аналитики используйте обезличенные сведения.\n"
        "• Если требуется работа с чувствительными данными, нужен отдельно "
        "утверждённый защищённый контур."
    )
    await message.reply_text(text)
    return CHATTING


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    del context
    message = update.effective_message
    if message is None:
        return CHATTING

    await message.reply_text(
        "КОМАНДЫ\n\n"
        "/start — начать интервью\n"
        "/report — сформировать итоговый отчёт\n"
        "/privacy — правила приватности\n"
        "/restart — начать заново\n"
        "/help — помощь"
    )
    return CHATTING


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if message is not None:
        await message.reply_text("Начинаем сначала...")
    return await start(update, context)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    del update
    logger.error("Ошибка Telegram-бота", exc_info=context.error)


def main() -> None:
    validate_config()
    logger.info("Запуск бота НАУЗ; SAVE_DIALOGS=%s", SAVE_DIALOGS)

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conversation = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHATTING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
                CommandHandler("report", report),
                CommandHandler("privacy", privacy),
                CommandHandler("restart", restart),
                CommandHandler("help", help_cmd),
            ],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("restart", restart),
            CommandHandler("help", help_cmd),
        ],
        allow_reentry=True,
    )

    app.add_handler(conversation)
    app.add_error_handler(error_handler)

    logger.info("Бот запущен")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
