from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import json
import threading
import time
from sdbus_utils import SdbusNm  # твой класс
from sdbus_block.networkmanager import enums

app = Flask(__name__)
CORS(app, resources={r"/wifi/*": {"origins": "*"}})  # разрешает все домены (только для dev!)

# Callback для сообщений (можно кастомизировать под GUI)
def popup_handler(msg, level=0):
    print(f"[POPUP-{level}] {msg}")

# Вспомогательная функция для красивого JSON
def make_json_response(data, status=200):
    return Response(
        json.dumps(data, indent=2, ensure_ascii=False),
        status=status,
        mimetype="application/json"
    )

# Константы для проверки 
CONNECTION_TIMEOUT = 10  # секунд на попытку подключения
POLL_INTERVAL = 1        # интервал опроса статуса

@app.route("/wifi/networks", methods=["GET"])
def list_networks():
    nm = SdbusNm(popup_handler)
    # Исправлено: был вызов функции вместо метода nm.rescan()
    nm.rescan() 
    # Небольшая задержка, чтобы сканирование успело начаться (опционально)
    time.sleep(0.5) 
    networks = nm.get_networks()
    return make_json_response(networks)


@app.route("/wifi/status", methods=["GET"])
@app.route("/wifi/status", methods=["GET"])
def wifi_status():
    nm = SdbusNm(popup_handler)
    
    # === Wi-Fi статус ===
    connected_ap = nm.get_connected_ap()
    ssid = connected_ap.ssid.decode("utf-8") if connected_ap else None
    
    wifi_data = {
        "enabled": nm.is_wifi_enabled(),
        "connected": connected_ap is not None,
        "ssid": ssid,
        "ip_address": nm.get_ip_address() if connected_ap else None
    }
    
    # === Ethernet статус (НОВОЕ) ===
    ethernet_data = nm.get_ethernet_status()
    
    # === Определяем активное соединение для отображения ===
    # Приоритет: Ethernet > Wi-Fi
    if ethernet_data["connected"]:
        active_connection = {
            "type": "ethernet",
            "name": "Ethernet",
            "ip": ethernet_data["ip_address"]
        }
    elif wifi_data["connected"]:
        active_connection = {
            "type": "wifi",
            "name": wifi_data["ssid"],
            "ip": wifi_data["ip_address"]
        }
    else:
        active_connection = None
    
    return make_json_response({
        "wifi": wifi_data,
        "ethernet": ethernet_data,
        "active_connection": active_connection  # Готовые данные для шапки
    })

@app.route("/wifi/connect", methods=["POST"])
def connect_network():
    nm = SdbusNm(popup_handler)
    data = request.json
    ssid = data.get("ssid")
    # Получаем пароль, но не передаем его, если сеть известна
    password = data.get("password", "").strip()
    eap_method = data.get("eap_method", None)
    identity = data.get("identity", "")
    phase2 = data.get("phase2", None)

    if not ssid:
        return make_json_response({"error": "SSID is required"}, status=400)

    is_known = nm.is_known(ssid)
    popup_handler(f"Сеть {ssid} {'известна' if is_known else 'новая'}, пароль предоставлен: {bool(password)}", level=1)

    # 1. Добавляем профиль ТОЛЬКО если сеть новая
    if not is_known:
        if not password:
            return make_json_response({"error": "Password required for new network"}, status=400)
        
        try:
            result = nm.add_network(ssid, password, eap_method, identity, phase2)
            if "error" in result:
                return make_json_response(result, status=400)
            popup_handler(f"Профиль для {ssid} создан", level=1)
        except Exception as e:
            error_msg = str(e)
            # Ловим ошибку неверного формата пароля (WPA2 требует 8-63 символа)
            if "psk: property is invalid" in error_msg:
                return make_json_response({
                    "error": "Invalid password format (WPA2 requires 8-63 characters)"
                }, status=400)
            return make_json_response({"error": f"Failed to add network: {error_msg}"}, status=500)
    else:
        # Для известной сети пароль не передаем в add_network
        popup_handler(f"Используем существующий профиль для {ssid}", level=1)

    # 2. Инициируем подключение
    try:
        nm.connect(ssid)
    except Exception as e:
        # Если ошибка при подключении к известной сети — возможно пароль изменился
        if is_known:
            popup_handler(f"Ошибка подключения к известной сети, пробуем обновить...", level=2)
            try:
                # Пытаемся пересоздать профиль с новым паролем если он был передан
                if password:
                    nm.delete_network(ssid)
                    nm.add_network(ssid, password, eap_method, identity, phase2)
                    nm.connect(ssid)
                else:
                    raise e
            except Exception as retry_e:
                return make_json_response({"error": str(retry_e)}, status=500)
        else:
            nm.delete_network(ssid)
            return make_json_response({"error": str(e)}, status=500)

    # 3. Ожидание и ВАЛИДАЦИЯ подключения
    popup_handler(f"Ожидание результата подключения к {ssid}...", level=1)
    
    CONNECTION_TIMEOUT = 5
    POLL_INTERVAL = 1
    STABLE_SUCCESS_COUNT = 3
    
    start_time = time.time()
    success_count = 0
    final_status = "failed"
    error_message = "Connection timeout"

    while (time.time() - start_time) < CONNECTION_TIMEOUT:
        time.sleep(POLL_INTERVAL)
        
        nm.monitor_connection_status()
        current_state = nm.wifi_state
        ip_address = nm.get_ip_address()
        
        popup_handler(f"State: {current_state}, IP: {ip_address}", level=1)

        # Явный провал авторизации
        if current_state == enums.DeviceState.FAILED:
            error_message = "Authentication failed (wrong password)"
            popup_handler("Состояние FAILED - неверный пароль", level=2)
            break
        
        # Успешное подключение
        if current_state == enums.DeviceState.ACTIVATED:
            if ip_address and ip_address != "0.0.0.0" and not ip_address.startswith("169.254"):
                success_count += 1
                popup_handler(f"Успешная проверка {success_count}/{STABLE_SUCCESS_COUNT}", level=1)
                
                if success_count >= STABLE_SUCCESS_COUNT:
                    final_status = "connected"
                    popup_handler(f"Подключение подтверждено (IP: {ip_address})", level=0)
                    break
            else:
                popup_handler("ACTIVATED но IP не получен, ждем...", level=1)
                success_count = 0
        else:
            if success_count > 0:
                error_message = "Connection lost during authentication"
                popup_handler("Соединение разорвано в процессе авторизации", level=2)
            success_count = 0

    # 4. Обработка результата
    if final_status == "connected":
        return make_json_response({
            "status": "connected", 
            "ssid": ssid,
            "message": "Password valid and connected",
            "ip_address": nm.get_ip_address()
        })
    else:
        # Если сеть была НОВАЯ и не подключилась — удаляем профиль
        # Если сеть была ИЗВЕСТНАЯ — оставляем профиль (вдруг просто глюк сети)
        if not is_known:
            try:
                nm.delete_network(ssid)
                popup_handler(f"Профиль {ssid} удален после неудачи", level=1)
            except:
                pass
            
        return make_json_response({
            "status": "failed", 
            "ssid": ssid,
            "error": error_message
        }, status=401)

@app.route("/wifi/disconnect", methods=["POST"])
def disconnect_network():
    nm = SdbusNm(popup_handler)
    nm.disconnect_network()
    return make_json_response({"status": "disconnected"})


@app.route("/wifi/network/<ssid>", methods=["DELETE"])
def delete_network(ssid):
    nm = SdbusNm(popup_handler)
    nm.delete_network(ssid)
    return make_json_response({"status": "deleted", "ssid": ssid})


@app.route("/wifi/toggle", methods=["POST"])
def toggle_wifi():
    nm = SdbusNm(popup_handler)
    data = request.json
    enable = data.get("enable", True)
    nm.toggle_wifi(enable)
    return make_json_response({"wifi_enabled": nm.is_wifi_enabled()})

@app.route("/wifi/rescan", methods=["POST"])
def rescan_networks():
    nm = SdbusNm(popup_handler)
    try:
        popup_handler("Запуск сканирования Wi-Fi...", level=1)
        nm.rescan()
        return make_json_response({"status": "scan_started"})
    except Exception as e:
        popup_handler(f"Ошибка сканирования: {e}", level=2)
        return make_json_response({"status": "error", "message": str(e)}, status=500)

@app.route("/wifi/monitor", methods=["POST"])
def toggle_monitoring():
    data = request.json
    enable = data.get("enable", True)
    nm = SdbusNm(popup_handler)
    nm.enable_monitoring(enable)
    return make_json_response({"monitoring": enable})

@app.route("/wifi/monitor/status", methods=["GET"])
def monitor_status():
    nm = SdbusNm(popup_handler)
    nm.monitor_connection_status()
    
    state_map = {
        enums.DeviceState.UNKNOWN: "UNKNOWN",
        enums.DeviceState.UNMANAGED: "UNMANAGED",
        enums.DeviceState.UNAVAILABLE: "UNAVAILABLE",
        enums.DeviceState.DISCONNECTED: "DISCONNECTED",
        enums.DeviceState.PREPARE: "PREPARE",
        enums.DeviceState.CONFIG: "CONFIG",
        enums.DeviceState.IP_CONFIG: "IP_CONFIG",
        enums.DeviceState.IP_CHECK: "IP_CHECK",
        enums.DeviceState.SECONDARIES: "SECONDARIES",
        enums.DeviceState.ACTIVATED: "ACTIVATED",
        enums.DeviceState.DEACTIVATING: "DEACTIVATING",
        enums.DeviceState.FAILED: "FAILED",
    }
    return make_json_response({
        "wifi_state": state_map.get(nm.wifi_state, "UNKNOWN"),
        "monitoring": nm.monitor_connection,
    })

if __name__ == "__main__":
    # use_reloader=False критично для корректной работы D-Bus
    app.run(host="0.0.0.0", port=5001, debug=True, use_reloader=False)