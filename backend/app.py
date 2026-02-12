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
    
@app.route("/wifi/networks", methods=["GET"])
def list_networks():
    nm = SdbusNm(popup_handler)
    rescan_networks
    networks = nm.get_networks()
    return make_json_response(networks)


@app.route("/wifi/status", methods=["GET"])
def wifi_status():
    nm = SdbusNm(popup_handler)
    connected_ap = nm.get_connected_ap()
    ssid = connected_ap.ssid.decode("utf-8") if connected_ap else None
    data = {
        "enabled": nm.is_wifi_enabled(),
        "connected_bssid": nm.get_connected_bssid(),
        "ip_address": nm.get_ip_address(),
        "name": ssid
    }
    return make_json_response(data)


@app.route("/wifi/connect", methods=["POST"])
def connect_network():
    nm = SdbusNm(popup_handler)
    data = request.json
    ssid = data.get("ssid")
    password = data.get("password", "").strip()  # убираем пробелы
    eap_method = data.get("eap_method", None)
    identity = data.get("identity", "")
    phase2 = data.get("phase2", None)

    # Проверяем, существует ли уже соединение с этой сетью
    if not nm.is_known(ssid):
        # Только если сеть НОВАЯ — добавляем её
        result = nm.add_network(ssid, password, eap_method, identity, phase2)
        if "error" in result:
            return make_json_response(result, status=400)
    else:
        popup_handler(f"Сеть {ssid} уже известна, используем существующее соединение", level=1)

    # Подключаемся (активируем соединение)
    try:
        nm.connect(ssid)
        return make_json_response({"status": "connecting", "ssid": ssid})
    except Exception as e:
        return make_json_response({"error": str(e)}, status=500)


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
        # Запускаем сканирование
        popup_handler("Запуск сканирования Wi-Fi...", level=1)
        nm.rescan()  # Единственный вызов
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

def delayed_rescan(nm, delay=2):
    nm.rescan()
    time.sleep(delay)

if __name__ == "__main__":
    # use_reloader=False критично для корректной работы D-Bus
    app.run(host="0.0.0.0", port=5001, debug=True)
