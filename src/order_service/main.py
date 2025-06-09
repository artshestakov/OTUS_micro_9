import requests
from enum import Enum
from flask import Flask, jsonify, request
from functools import wraps
# ----------------------------------------------------------------------------------------------------------------------
app = Flask(__name__)
idempotency_store = {} # Хранилище для idempotency keys
# ----------------------------------------------------------------------------------------------------------------------
class SERVICE_PORT(Enum):
    PAYMENT = 5000,
    STOCK = 5001,
    DELIVERY = 5002
# ----------------------------------------------------------------------------------------------------------------------
def idempotent(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):

        # Получаем ключ из заголовка
        idempotency_key = request.headers.get('Idempotency-Key')

        # Если такого нет - 400ка
        if not idempotency_key:
            return jsonify({'error': 'Idempotency-Key header is required'}), 400

        # Проверяем, есть ли уже такой ключ
        if idempotency_key in idempotency_store:
            return jsonify(idempotency_store[idempotency_key]['response']),\
                idempotency_store[idempotency_key]['status_code']

        # Выполняем функцию и сохраняем результат
        response = f(*args, **kwargs)
        idempotency_store[idempotency_key] = {
            'response': response[0].get_json(),
            'status_code': response[1]}

        # Ограничим размер хранилища
        if len(idempotency_store) > 100:
            idempotency_store.pop(next(iter(idempotency_store)))

        return response

    return decorated_function
# ----------------------------------------------------------------------------------------------------------------------
@app.route('/orders', methods=['POST'])
@idempotent
def create_order():
    data = request.json
    order_id = data['order_id']

    # Проверяем, не существует ли уже такой заказ
    if order_id in idempotency_store.values():
        return jsonify({'error': 'Order already exists'}), 400

    try:
        payment_resp = requests.post(
            f"http://127.0.0.1:{SERVICE_PORT.PAYMENT}/payments/validate",
            json={'order_id': order_id, 'amount': data['amount']},
            timeout=5)
        payment_resp.raise_for_status()
    except Exception as e:
        return jsonify({'error': f'Payment failed: {str(e)}'}), 400

    try:
        stock_resp = requests.post(
            f"http://127.0.0.1:{SERVICE_PORT.STOCK}/stock/reserve",
            json={'order_id': order_id, 'items': data['items']},
            timeout=5)
        stock_resp.raise_for_status()
    except Exception as e:
        requests.post(f"http://127.0.0.1:{SERVICE_PORT.PAYMENT}/payments/cancel", json={'order_id': order_id})
        return jsonify({'error': f'Stock reservation failed: {str(e)}'}), 400

    try:
        delivery_resp = requests.post(
            f"http://127.0.0.1:{SERVICE_PORT.DELIVERY}/delivery/reserve",
            json={'order_id': order_id, 'address': data['address'], 'timeslot': data['timeslot']},
            timeout=5)
        delivery_resp.raise_for_status()
    except Exception as e:
        requests.post(f"http://127.0.0.1:{SERVICE_PORT.PAYMENT}/payments/cancel", json={'order_id': order_id})
        requests.post(f"http://127.0.0.1:{SERVICE_PORT.STOCK}/stock/release", json={'order_id': order_id})
        return jsonify({'error': f'Delivery reservation failed: {str(e)}'}), 400

    return jsonify({'status': 'Order created successfully', 'order_id': order_id}), 201
# ----------------------------------------------------------------------------------------------------------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=50000)
# ----------------------------------------------------------------------------------------------------------------------
