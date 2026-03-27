#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║   Telegram-бот НАУЗ — Национальная Ассоциация Управленцев   ║
║              Сферы Здравоохранения (auz.clinic)              ║
╚══════════════════════════════════════════════════════════════╝

Установка зависимостей:
    pip install python-telegram-bot anthropic

Настройка:
    1. @BotFather в Telegram → /newbot → скопируйте TELEGRAM_TOKEN
    2. https://console.anthropic.com → API Keys → скопируйте ANTHROPIC_API_KEY
    3. Вставьте токены в раздел НАСТРОЙКИ ниже
    4. Запустите: python nauz_bot.py
"""

import logging
import json
import datetime
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
import anthropic

# ══════════════════════════════════════════════
#  НАСТРОЙКИ — вставьте ваши токены здесь
# ══════════════════════════════════════════════
import os
TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
# ══════════════════════════════════════════════
#  Логирование
# ══════════════════════════════════════════════
logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════
#  Состояния диалога
# ══════════════════════════════════════════════
CHATTING = 0

# ══════════════════════════════════════════════
#  Системный промпт — знания о НАУЗ
# ══════════════════════════════════════════════
SYSTEM_PROMPT = """Ты — интеллектуальный ассистент Национальной Ассоциации Управленцев Сферы Здравоохранения (НАУЗ, сайт: auz.clinic).

=== О НАУЗ ===
НАУЗ — объединение лидеров-управленцев системы здравоохранения России.
Председатель — Муслим Муслимов, врач-хирург, к.м.н., член Общественной палаты РФ и Общественного совета при Минздраве России.

Ключевые цели НАУЗ:
• Сформировать действующее профессиональное сообщество специалистов здравоохранения
• Создать систему повышения управленческих навыков (Центр развития управленческих компетенций на базе РМАНПО)
• Наладить постоянный диалог всех участников отрасли
• Отобрать лучших в кадровый резерв — от выпускников вузов до топ-менеджеров
• Открыть аналитический центр
• Разработать рейтинговую систему эффективности медуправления в России
• Объединить управленческие кейсы российской и зарубежной медицины в общедоступную базу

Ключевые проблемы отрасли, которые решает НАУЗ:
• Критическая нехватка врачей-организаторов из-за отсутствия системы развития управленцев
• Несоответствие практик отдельных областей здравоохранения передовым стандартам управления
• Административные барьеры на пути развития частного сектора
• Слабая цифровизация медицинских организаций
• Разрозненность профессионального сообщества

Деятельность НАУЗ:
• Международные конгрессы и конференции
• Образовательные программы и мастер-классы
• Экспертные круглые столы с органами власти
• Международные бизнес-туры для изучения лучших практик
• Участие в разработке законодательных инициатив
• Сотрудничество с Государственной Думой РФ (Экспертный совет по цифровизации здравоохранения)
• Партнёрства с ведущими ИТ-компаниями (1С-Битрикс, F.Doc и др.)

=== ТВОЯ РОЛЬ ===
Ты проводишь глубокое структурированное интервью с управленцами в сфере здравоохранения.
Твоя задача — задавать умные уточняющие вопросы, чтобы понять:
- Кто этот человек и какова его роль
- С какими проблемами он сталкивается
- Каковы его цели и приоритеты
- Как НАУЗ может ему помочь
- Что он готов привнести в ассоциацию

=== ПРАВИЛА ДИАЛОГА ===
1. Задавай строго ОДИН вопрос за раз — никогда не задавай несколько вопросов подряд
2. Вопросы должны быть конкретными и вытекать из предыдущего ответа
3. Кратко комментируй ответ перед следующим вопросом — покажи, что слушаешь
4. Веди диалог последовательно: контекст → проблемы → цели → ожидания от НАУЗ
5. После 10-12 вопросов предложи сформировать итоговый отчёт
6. Говори на том языке, на котором пишет пользователь

=== ТЕМЫ ДЛЯ УТОЧНЕНИЯ (раскрывай постепенно) ===
□ Должность, специализация и опыт в здравоохранении
□ Тип организации (государственная / частная / смешанная) и её масштаб
□ Текущие стратегические приоритеты и KPI
□ Главные управленческие проблемы и барьеры
□ Цифровизация: что внедрено, что планируется
□ Кадровая стратегия и HR-вызовы
□ Финансовое управление и ресурсные ограничения
□ Взаимодействие с регуляторами и государством
□ Потребность в обучении и профессиональном развитии
□ Опыт участия в профессиональных объединениях
□ Ожидания от членства в НАУЗ
□ Готовность участвовать в проектах ассоциации

=== ФОРМАТ ИТОГОВОГО ОТЧЁТА ===
Когда пользователь просит отчёт — составь структурированный документ:

ИТОГОВЫЙ ПРОФИЛЬ УПРАВЛЕНЦА
- Краткая характеристика: должность, организация, опыт
- Ключевые проблемы и потребности
- Стратегические цели на 1-3 года
- Рекомендации по взаимодействию с НАУЗ
- Конкретные проекты ассоциации, которые могут быть полезны

=== СТИЛЬ ===
• Экспертный, профессиональный, но тёплый и человечный
• Используй профессиональную терминологию здравоохранения
• Проявляй искренний интерес и глубокое понимание отрасли
• Иногда делись релевантными фактами о работе НАУЗ
"""

# ══════════════════════════════════════════════
#  Клиент Anthropic
# ══════════════════════════════════════════════
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def ai_response(history: list) -> str:
    """Запрос к Claude API."""
    try:
        resp = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=1200,
            system=SYSTEM_PROMPT,
            messages=history,
        )
        return resp.content[0].text
    except anthropic.APIConnectionError:
        return "⚠️ Ошибка подключения к ИИ. Проверьте интернет и попробуйте снова."
    except anthropic.AuthenticationError:
        return "⚠️ Неверный API-ключ Anthropic. Проверьте настройки бота."
    except Exception as e:
        logger.error(f"Anthropic API error: {e}")
        return "⚠️ Техническая ошибка. Попробуйте ещё раз или введите /start."


def save_dialog(user_id: int, username: str, history: list) -> None:
    """Сохранить диалог в JSON-файл."""
    try:
        filename = f"dialog_{user_id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        data = {
            "user_id": user_id,
            "username": username,
            "timestamp": datetime.datetime.now().isoformat(),
            "messages_count": len(history),
            "history": history,
        }
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Диалог сохранён: {filename}")
    except Exception as e:
        logger.error(f"Ошибка сохранения диалога: {e}")


# ══════════════════════════════════════════════
#  /start
# ══════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    logger.info(f"Новый пользователь: {user.id} (@{user.username})")

    context.user_data.clear()
    context.user_data["history"] = []
    context.user_data["q_count"] = 0
    context.user_data["report_offered"] = False

    welcome = (
        f"👋 Здравствуйте, {user.first_name}!\n\n"
        "Добро пожаловать в чат-бот\n"
        "🏥 Национальной Ассоциации Управленцев Сферы Здравоохранения (НАУЗ)\n\n"
        "Я помогу:\n"
        "✅ Определить ваши управленческие цели и задачи\n"
        "✅ Выявить ключевые проблемы и потребности\n"
        "✅ Найти точки взаимодействия с НАУЗ\n"
        "✅ Подготовить персональный аналитический отчёт\n\n"
        "Команды:\n"
        "/report — получить итоговый отчёт\n"
        "/restart — начать заново\n"
        "/help — помощь\n\n"
        "Диалог займёт около 10-15 минут. Начнём?"
    )

    await update.message.reply_text(welcome)

    init_msg = [{"role": "user", "content": "Начни интервью. Кратко представься от имени НАУЗ и задай первый вопрос о должности и роли собеседника в здравоохранении."}]
    first_q = ai_response(init_msg)

    context.user_data["history"] = [
        {"role": "user", "content": "Начни интервью. Кратко представься от имени НАУЗ и задай первый вопрос о должности и роли собеседника в здравоохранении."},
        {"role": "assistant", "content": first_q},
    ]
    context.user_data["q_count"] = 1

    await update.message.reply_text(first_q)
    return CHATTING


# ══════════════════════════════════════════════
#  Основной обработчик сообщений
# ══════════════════════════════════════════════
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_text = update.message.text.strip()
    if not user_text:
        return CHATTING

    history = context.user_data.get("history", [])
    q_count = context.user_data.get("q_count", 0)
    user    = update.effective_user

    history.append({"role": "user", "content": user_text})
    await update.message.chat.send_action("typing")

    # После 10 вопросов — предложить отчёт (один раз)
    if q_count >= 10 and not context.user_data.get("report_offered", False):
        history.append({
            "role": "user",
            "content": (
                "[СИСТЕМНАЯ ИНСТРУКЦИЯ: Задано уже 10+ вопросов. "
                "Поблагодари за развёрнутые ответы и предложи сформировать итоговый отчёт. "
                "Спроси хочет ли пользователь продолжить диалог или получить отчёт сейчас.]"
            ),
        })
        context.user_data["report_offered"] = True

    response = ai_response(history)
    history.append({"role": "assistant", "content": response})

    context.user_data["history"] = history
    context.user_data["q_count"] = q_count + 1

    # Автосохранение каждые 5 сообщений
    if context.user_data["q_count"] % 5 == 0:
        save_dialog(user.id, user.username or "unknown", history)

    await update.message.reply_text(response)
    return CHATTING


# ══════════════════════════════════════════════
#  /report
# ══════════════════════════════════════════════
async def report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    history = context.user_data.get("history", [])
    user    = update.effective_user

    if len(history) < 4:
        await update.message.reply_text(
            "ℹ️ Для формирования отчёта нужно ответить хотя бы на несколько вопросов.\n"
            "Продолжим диалог?"
        )
        return CHATTING

    await update.message.reply_text("⏳ Формирую ваш персональный отчёт, подождите...")
    await update.message.chat.send_action("typing")

    history.append({
        "role": "user",
        "content": (
            "Сформируй подробный итоговый отчёт на основе нашего диалога. "
            "Включи: профиль управленца, выявленные проблемы, цели и приоритеты, "
            "рекомендации по взаимодействию с НАУЗ, конкретные проекты ассоциации "
            "которые могут быть полезны. Оформи структурированно с заголовками."
        ),
    })

    report_text = ai_response(history)
    history.append({"role": "assistant", "content": report_text})
    context.user_data["history"] = history

    save_dialog(user.id, user.username or "unknown", history)

    await update.message.reply_text(f"📊 ИТОГОВЫЙ ОТЧЁТ\n\n{report_text}")
    await update.message.reply_text(
        "✅ Отчёт сформирован и сохранён.\n\n"
        "Хотите продолжить диалог — просто напишите.\n"
        "Начать заново: /restart\n\n"
        "Спасибо за участие в опросе НАУЗ! 🏥\n"
        "Сайт: https://auz.clinic"
    )
    return CHATTING


# ══════════════════════════════════════════════
#  /restart
# ══════════════════════════════════════════════
async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("🔄 Начинаем сначала...")
    return await start(update, context)


# ══════════════════════════════════════════════
#  /help
# ══════════════════════════════════════════════
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "🤖 БОТ НАУЗ — ПОМОЩЬ\n\n"
        "Этот бот проводит профессиональное интервью для выявления ваших "
        "управленческих целей и задач в сфере здравоохранения.\n\n"
        "Команды:\n"
        "/start — начать диалог\n"
        "/report — получить итоговый отчёт\n"
        "/restart — начать заново\n"
        "/help — эта справка\n\n"
        "Совет: отвечайте развёрнуто — это помогает ИИ задавать более точные вопросы.\n\n"
        "Сайт НАУЗ: https://auz.clinic"
    )
    return CHATTING


# ══════════════════════════════════════════════
#  Обработка ошибок
# ══════════════════════════════════════════════
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Ошибка: {context.error}", exc_info=context.error)


# ══════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════
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
                CommandHandler("help", help_cmd),
            ],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("restart", restart),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_error_handler(error_handler)

    logger.info("Бот запущен. Нажмите Ctrl+C для остановки.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
