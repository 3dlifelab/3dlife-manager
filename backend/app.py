from ipaddress import IPv4Address
import time

from flask import Flask, jsonify, request
from sdbus import SdBusBaseError
from sdbus_block.networkmanager import enums

from sdbus_utils import HotspotChannelError, SdbusNm, management_ap_configured

app = Flask(__name__)
CONNECTION_TIMEOUT = 8
POLL_INTERVAL = 0.5


def network_manager():
    return SdbusNm(lambda message, level=0: app.logger.debug("%s", message))


@app.before_request
def check_request_origin():
    if request.method not in {"POST", "DELETE"}:
        return
    origin = request.headers.get("Origin")
    if origin and origin != request.host_url.rstrip("/"):
        return jsonify(error="Cross-origin Wi-Fi changes are forbidden"), 403


@app.errorhandler(SdBusBaseError)
def dbus_error(error):
    app.logger.error("NetworkManager operation failed (%s)", type(error).__name__)
    return jsonify(error="NetworkManager operation failed"), 503


def wifi_device_required(nm):
    if not nm.wifi:
        return jsonify(error="Wi-Fi adapter not found"), 503


@app.get("/wifi/networks")
def list_networks():
    return jsonify(network_manager().get_networks())


@app.get("/wifi/status")
def wifi_status():
    nm = network_manager()
    connected_ap = nm.get_connected_ap()
    wifi = {
        "enabled": nm.is_wifi_enabled(),
        "connected": connected_ap is not None,
        "ssid": connected_ap.ssid.decode("utf-8", errors="surrogateescape") if connected_ap else None,
        "ip_address": nm.get_ip_address() if connected_ap else None,
    }
    ethernet = nm.get_ethernet_status()

    active_connection = None
    if ethernet["connected"]:
        active_connection = {"type": "ethernet", "name": "Ethernet", "ip": ethernet["ip_address"]}
    elif wifi["connected"]:
        active_connection = {"type": "wifi", "name": wifi["ssid"], "ip": wifi["ip_address"]}

    return jsonify(wifi=wifi, ethernet=ethernet, active_connection=active_connection)


@app.post("/wifi/connect")
def connect_network():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Expected a JSON object"), 400

    ssid = data.get("ssid")
    password = data.get("password", "")
    eap_method = data.get("eap_method")
    identity = data.get("identity", "")
    phase2 = data.get("phase2")
    if not isinstance(ssid, str) or not ssid:
        return jsonify(error="SSID is required"), 400
    try:
        valid_ssid = len(ssid.encode("utf-8", errors="surrogateescape")) <= 32
        # NetworkManager accepts arbitrary SSID bytes, including non-UTF-8 values.
    except UnicodeEncodeError:
        valid_ssid = False
    if not valid_ssid:
        return jsonify(error="Invalid SSID"), 400
    if not isinstance(password, str) or not isinstance(identity, str):
        return jsonify(error="Password and identity must be strings"), 400
    if any(value is not None and not isinstance(value, str) for value in (eap_method, phase2)):
        return jsonify(error="EAP method and phase2 must be strings"), 400

    nm = network_manager()
    if error := wifi_device_required(nm):
        return error
    try:
        target = nm.select_hotspot_compatible_target(ssid)
    except HotspotChannelError as error:
        return jsonify(error=str(error)), 409
    connection_path = nm.get_connection_path_by_ssid(ssid)
    new_profile = connection_path is None
    if new_profile:
        result = nm.add_network(ssid, password, eap_method, identity, phase2, target=target)
        if "error" in result:
            return jsonify(result), 400
        connection_path = result["path"]

    if target and not new_profile:
        nm.pin_saved_profile(connection_path, target)

    connected = False
    try:
        active_path = nm.connect(connection_path, target)
        deadline = time.monotonic() + CONNECTION_TIMEOUT
        while time.monotonic() < deadline:
            state = nm.wlan_device.state
            if state == enums.DeviceState.FAILED:
                return jsonify(status="failed", ssid=ssid, error="Wi-Fi activation failed"), 409
            if state == enums.DeviceState.ACTIVATED:
                ip_address = nm.get_ip_address(active_path)
                if ip_address:
                    address = IPv4Address(ip_address)
                    if not address.is_unspecified and not address.is_link_local:
                        connected = True
                        return jsonify(status="connected", ssid=ssid, ip_address=ip_address)
            time.sleep(POLL_INTERVAL)
        return jsonify(status="failed", ssid=ssid, error="Connection timeout"), 504
    finally:
        if new_profile and not connected:
            try:
                nm.delete_connection_path(connection_path)
            except SdBusBaseError:
                app.logger.exception("Could not remove failed Wi-Fi profile")


@app.post("/wifi/disconnect")
def disconnect_network():
    nm = network_manager()
    if error := wifi_device_required(nm):
        return error
    nm.disconnect_network()
    return jsonify(status="disconnected")


@app.delete("/wifi/network/<path:ssid>")
def delete_network(ssid):
    if not network_manager().delete_network(ssid):
        return jsonify(error="Saved client Wi-Fi profile not found"), 404
    return jsonify(status="deleted", ssid=ssid)


@app.post("/wifi/toggle")
def toggle_wifi():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("enable"), bool):
        return jsonify(error="Expected a boolean enable field"), 400
    if not data["enable"] and management_ap_configured():
        return jsonify(error="Disabling the Wi-Fi radio would stop the management access point"), 409
    nm = network_manager()
    if error := wifi_device_required(nm):
        return error
    nm.toggle_wifi(data["enable"])
    return jsonify(wifi_enabled=nm.is_wifi_enabled())


@app.post("/wifi/rescan")
def rescan_networks():
    nm = network_manager()
    if error := wifi_device_required(nm):
        return error

    previous_scan = nm.wlan_device.last_scan
    nm.rescan()
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        if nm.wlan_device.last_scan != previous_scan:
            return jsonify(status="scan_completed")
        time.sleep(POLL_INTERVAL)
    return jsonify(status="scan_started"), 202


@app.post("/wifi/monitor")
def toggle_monitoring():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("enable"), bool):
        return jsonify(error="Expected a boolean enable field"), 400
    app.config["WIFI_MONITORING"] = data["enable"]
    return jsonify(monitoring=data["enable"])


@app.get("/wifi/monitor/status")
def monitor_status():
    nm = network_manager()
    nm.monitor_connection_status()
    return jsonify(
        wifi_state=getattr(nm.wifi_state, "name", "UNKNOWN"),
        monitoring=app.config.get("WIFI_MONITORING", False),
    )
