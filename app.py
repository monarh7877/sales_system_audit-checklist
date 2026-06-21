"""
Backend для оплаты чек-листа "Аудит воронки продаж" через ЮКассу.

Логика:
1. Пользователь заходит на сайт, видит кнопку "Оплатить".
2. Кнопка дёргает /create-payment -> сервер создаёт платёж в ЮКассе,
   возвращает ссылку на страницу оплаты.
3. Пользователь оплачивает на стороне ЮКассы.
4. ЮКасса присылает уведомление на /yookassa-webhook (когда оплата прошла).
5. Пользователь возвращается на сайт по return_url с payment_id в адресе.
6. Сайт спрашивает /check-payment?payment_id=... — сервер отвечает,
   оплачено или нет. Если оплачено — открывает доступ к чек-листу.

Установка:
  pip install flask yookassa --break-system-packages

Запуск:
  python app.py

Переменные окружения (задаются в Railway -> Variables):
  YOOKASSA_SHOP_ID      - твой shopId (например 1389490)
  YOOKASSA_SECRET_KEY   - секретный ключ (тестовый или продакшен)
  RETURN_URL            - адрес, куда вернётся пользователь после оплаты
                          (например https://sales-system-audit.up.railway.app/)
"""

import os
import uuid
import logging
from flask import Flask, request, jsonify, send_from_directory
from yookassa import Configuration, Payment

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder=".", static_url_path="")

# ==== НАСТРОЙКИ ЮКАССЫ ====
Configuration.account_id = os.environ.get("YOOKASSA_SHOP_ID", "")
Configuration.secret_key = os.environ.get("YOOKASSA_SECRET_KEY", "")
RETURN_URL = os.environ.get("RETURN_URL", "https://example.com/")
PRICE_RUB = "1490.00"

# Диагностика: смотрим repr() значений, чтобы заметить пробелы/скрытые символы
logger.info(f"DEBUG shop_id repr: {repr(Configuration.account_id)}, длина: {len(Configuration.account_id)}")
logger.info(f"DEBUG secret_key repr: {repr(Configuration.secret_key)}, длина: {len(Configuration.secret_key)}")

# Простое хранилище статусов оплаты в памяти.
# ВНИМАНИЕ: при перезапуске сервера данные сбрасываются.
# Для продакшена лучше заменить на базу данных (см. примечание внизу файла).
paid_payments = set()


@app.route("/")
def index():
    """Отдаёт главную страницу (чек-лист) — index.html должен лежать рядом."""
    return send_from_directory(".", "index.html")


@app.route("/create-payment", methods=["POST"])
def create_payment():
    """Создаёт платёж в ЮКассе и возвращает ссылку на страницу оплаты."""
    idempotence_key = str(uuid.uuid4())

    try:
        payment = Payment.create(
            {
                "amount": {"value": PRICE_RUB, "currency": "RUB"},
                "confirmation": {
                    "type": "redirect",
                    "return_url": RETURN_URL,
                },
                "capture": True,
                "description": "Аудит воронки продаж — диагностический чек-лист",
            },
            idempotence_key,
        )

        return jsonify(
            {
                "payment_id": payment.id,
                "confirmation_url": payment.confirmation.confirmation_url,
            }
        )

    except Exception as e:
        logger.error(f"Ошибка создания платежа: {e}")
        # Дополнительно выводим детали ответа сервера ЮКассы, если они есть
        if hasattr(e, "response") and e.response is not None:
            try:
                logger.error(f"Тело ответа ЮКассы: {e.response.text}")
            except Exception:
                pass
        return jsonify({"error": "Не удалось создать платёж"}), 500


@app.route("/check-payment", methods=["GET"])
def check_payment():
    """Проверяет, оплачен ли платёж с данным payment_id."""
    payment_id = request.args.get("payment_id", "")

    if not payment_id:
        return jsonify({"paid": False, "error": "payment_id не указан"}), 400

    # Сначала смотрим в локальный кэш (быстрый путь после вебхука)
    if payment_id in paid_payments:
        return jsonify({"paid": True})

    # Если в кэше нет — спрашиваем напрямую у ЮКассы (на случай,
    # если вебхук еще не пришёл или не настроен)
    try:
        payment = Payment.find_one(payment_id)
        if payment.status == "succeeded":
            paid_payments.add(payment_id)
            return jsonify({"paid": True})
        else:
            return jsonify({"paid": False, "status": payment.status})
    except Exception as e:
        logger.error(f"Ошибка проверки платежа: {e}")
        return jsonify({"paid": False, "error": "Не удалось проверить платёж"}), 500


@app.route("/yookassa-webhook", methods=["POST"])
def yookassa_webhook():
    """
    Эндпоинт, на который ЮКасса присылает уведомления о смене статуса платежа.
    Этот URL нужно один раз указать в личном кабинете ЮКассы:
    Интеграция -> HTTP-уведомления -> вставить:
    https://<твой-домен-railway>/yookassa-webhook
    """
    data = request.get_json(force=True, silent=True) or {}
    event = data.get("event", "")
    obj = data.get("object", {})
    payment_id = obj.get("id", "")

    logger.info(f"Получено уведомление от ЮКассы: {event}, payment_id={payment_id}")

    if event == "payment.succeeded" and payment_id:
        paid_payments.add(payment_id)

    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
