import logging
import subprocess
from uuid import uuid4
import os

import sdbus
from sdbus_block.networkmanager import (
    NetworkManager,
    NetworkDeviceGeneric,
    NetworkDeviceWireless,
    NetworkConnectionSettings,
    NetworkManagerSettings,
    AccessPoint,
    NetworkManagerConnectionProperties,
    IPv4Config,
    ActiveConnection,
    enums,
    exceptions,
)

NONE = 0  # The access point has no special security requirements.
PAIR_WEP40 = 1  # 40/64-bit WEP is supported for pairwise/unicast encryption.
PAIR_WEP104 = 2  # 104/128-bit WEP is supported for pairwise/unicast encryption.
PAIR_TKIP = 4  # TKIP is supported for pairwise/unicast encryption.
PAIR_CCMP = 8  # AES/CCMP is supported for pairwise/unicast encryption.
GROUP_WEP40 = 16  # 40/64-bit WEP is supported for group/broadcast encryption.
GROUP_WEP104 = 32  # 104/128-bit WEP is supported for group/broadcast encryption.
GROUP_TKIP = 64  # TKIP is supported for group/broadcast encryption.
GROUP_CCMP = 128  # AES/CCMP is supported for group/broadcast encryption.
KEY_MGMT_PSK = 256  # WPA/RSN Pre-Shared Key encryption
KEY_MGMT_802_1X = 512  # 802.1x authentication and key management
KEY_MGMT_SAE = 1024  # WPA/RSN Simultaneous Authentication of Equals
KEY_MGMT_OWE = 2048  # WPA/RSN Opportunistic Wireless Encryption
KEY_MGMT_OWE_TM = 4096  # WPA/RSN Opportunistic Wireless Encryption transition mode
KEY_MGMT_EAP_SUITE_B_192 = 8192  # WPA3 Enterprise Suite-B 192


def get_encryption(flags):
    if flags == 0:
        return "Open"

    encryption_mapping = {
        PAIR_WEP40: "WEP",
        PAIR_WEP104: "WEP",
        PAIR_TKIP: "TKIP",
        PAIR_CCMP: "AES",
        GROUP_WEP40: "WEP",
        GROUP_WEP104: "WEP",
        GROUP_TKIP: "TKIP",
        GROUP_CCMP: "AES",
        KEY_MGMT_PSK: "WPA-PSK",
        KEY_MGMT_802_1X: "802.1x",
        KEY_MGMT_SAE: "WPA-SAE",
        KEY_MGMT_OWE: "OWE",
        KEY_MGMT_OWE_TM: "OWE-TM",
        KEY_MGMT_EAP_SUITE_B_192: "WPA3-B192",
    }

    encryption_methods = []
    for flag, method_name in encryption_mapping.items():
        if flags & flag and method_name not in encryption_methods:
            encryption_methods.append(method_name)
    return " ".join(encryption_methods)


def WifiChannels(freq: str):
    if freq == "2484":
        return "2.4", "14"
    try:
        freq = float(freq)
    except ValueError:
        return "?", "?"
    if 2412 <= freq <= 2472:
        return "2.4", str(int((freq - 2407) / 5))
    elif 3657.5 <= freq <= 3692.5:
        return "3", str(int((freq - 3000) / 5))
    elif 4915 <= freq <= 4980:
        return "5", str(int((freq - 4000) / 5))
    elif 5035 <= freq <= 5885:
        return "5", str(int((freq - 5000) / 5))
    elif 6455 <= freq <= 7115:
        return "6", str(int((freq - 5950) / 5))
    else:
        return "?", "?"


class SdbusNm:
    def popup_handler(self,msg, level=0):
        print(f"[POPUP-{level}] {msg}")
    def __init__(self, popup_callback):
        self.popup = popup_callback  # ← Сначала сохраняем колбэк
        
        # Инициализация D-Bus
        self.system_bus = sdbus.sd_bus_open_system()
        if self.system_bus is None:
            return
        
        sdbus.set_default_bus(self.system_bus)
        
        # Создание объекта NetworkManager
        self.nm = NetworkManager()
        
        # ✅ Проверка ПОСЛЕ создания объекта
        if not self.ensure_nm_running():
            raise RuntimeError("NetworkManager не отвечает")
        
        # Остальная инициализация
        self.wlan_device = (
            self.get_wireless_interfaces()[0]
            if self.get_wireless_interfaces()
            else None
        )
        self.wifi = self.wlan_device is not None
        self.monitor_connection = False
        self.wifi_state = -1

    def ensure_nm_running(self):
        """Проверяет доступность NetworkManager через D-Bus"""
        try:
            # Пытаемся получить список устройств — если NM не работает, тут будет ошибка
            _ = self.nm.get_devices()
            return True
        except Exception as e:
            self.popup(f"NetworkManager недоступен: {e}", 2)
            return False

    def is_wifi_enabled(self):
        return self.nm.wireless_enabled

    def get_interfaces(self):
        return [
            NetworkDeviceGeneric(device).interface for device in self.nm.get_devices()
        ]

    def get_wireless_interfaces(self):
        devices = {path: NetworkDeviceGeneric(path) for path in self.nm.get_devices()}
        return [
            NetworkDeviceWireless(path)
            for path, device in devices.items()
            if device.device_type == enums.DeviceType.WIFI
        ]

    def get_primary_interface(self):
        if self.nm.primary_connection == "/":
            if self.wlan_device:
                return self.wlan_device.interface
            return next(
                (interface for interface in self.get_interfaces() if interface != "lo"),
                None,
            )
        gateway = ActiveConnection(self.nm.primary_connection).devices[0]
        return NetworkDeviceGeneric(gateway).interface

    @staticmethod
    def get_known_networks():
        known_networks = []
        saved_network_paths = NetworkManagerSettings().list_connections()
        for netpath in saved_network_paths:
            saved_con = NetworkConnectionSettings(netpath)
            con_settings = saved_con.get_settings()
            if con_settings["connection"]["type"][1] == "802-11-wireless":
                known_networks.append(
                    {
                        "SSID": con_settings["802-11-wireless"]["ssid"][1].decode(),
                        "UUID": con_settings["connection"]["uuid"][1],
                    }
                )
        return known_networks

    def is_known(self, ssid):
        return any(net["SSID"] == ssid for net in self.get_known_networks())

    def get_ip_address(self):
        active_connection_path = self.nm.primary_connection
        if not active_connection_path or active_connection_path == "/":
            return "?"
        active_connection = ActiveConnection(active_connection_path)
        ip_info = IPv4Config(active_connection.ip4_config)
        return ip_info.address_data[0]["address"][1]

    def get_networks(self):
        networks = []
        if self.wlan_device:
            all_aps = [AccessPoint(result) for result in self.wlan_device.access_points]
            networks.extend(
                {
                    "SSID": ap.ssid.decode("utf-8"),
                    "known": self.is_known(ap.ssid.decode("utf-8")),
                    "security": get_encryption(
                        ap.rsn_flags or ap.wpa_flags or ap.flags
                    ),
                    "frequency": WifiChannels(ap.frequency)[0],
                    "signal_level": ap.strength,
                    "BSSID": ap.hw_address,
                }
                for ap in all_aps
                if ap.ssid
            )
            return sorted(networks, key=lambda i: i["signal_level"], reverse=True)
        return networks

    def get_bssid_from_ssid(self, ssid):
        return next(net["BSSID"] for net in self.get_networks() if ssid == net["SSID"])

    def get_connected_ap(self):
        if self.wlan_device.active_access_point == "/":
            return None
        return AccessPoint(self.wlan_device.active_access_point)

    def get_connected_bssid(self):
        return (
            self.get_connected_ap().hw_address
            if self.get_connected_ap() is not None
            else None
        )

    def get_security_type(self, ssid):
        return next(
            (
                network["security"]
                for network in self.get_networks()
                if network["SSID"] == ssid
            ),
            None,
        )

    def add_network(self, ssid, psk, eap_method, identity="", phase2=None):
        security_type = self.get_security_type(ssid)
        logging.debug(f"Adding network of type: {security_type}")
        if security_type is None:
            return {"error": "network_not_found", "message": "Network not found"}

        if self.is_known(ssid):
            self.delete_network(ssid)

        properties: NetworkManagerConnectionProperties = {
            "connection": {
                "id": ("s", ssid),
                "uuid": ("s", str(uuid4())),
                "type": ("s", "802-11-wireless"),
                "interface-name": ("s", self.wlan_device.interface),
            },
            "802-11-wireless": {
                "mode": ("s", "infrastructure"),
                "ssid": ("ay", ssid.encode("utf-8")),
                "security": ("s", "802-11-wireless-security"),
            },
            "ipv4": {"method": ("s", "auto")},
            "ipv6": {"method": ("s", "auto")},
        }

        if security_type == "Open":
            properties["802-11-wireless-security"] = {
                "key-mgmt": ("s", "none"),
            }
        elif "WPA-PSK" in security_type:
            properties["802-11-wireless-security"] = {
                "key-mgmt": ("s", "wpa-psk"),
                "psk": ("s", psk),
            }
        elif "SAE" in security_type:
            properties["802-11-wireless-security"] = {
                "key-mgmt": ("s", "sae"),
                "psk": ("s", psk),
            }
        elif "WPA3-B192" in security_type:
            properties["802-11-wireless-security"] = {
                "key-mgmt": ("s", "wpa-eap-suite-b-192"),
                "psk": ("s", psk),
            }
        elif "OWE" in security_type:
            properties["802-11-wireless-security"] = {
                "key-mgmt": ("s", "owe"),
            }
        elif "802.1x" in security_type:
            properties["802-11-wireless-security"] = {
                "key-mgmt": ("s", "wpa-eap"),
                "eap": ("as", [eap_method]),
                "identity": ("s", identity),
                "password": ("s", psk.encode("utf-8")),
            }
            if phase2:
                if eap_method == "ttls":
                    properties["802-11-wireless-security"]["phase2_autheap"] = ("s", phase2)
                else:
                    properties["802-11-wireless-security"]["phase2_auth"] = ("s", phase2)
        elif "WEP" in security_type:
            properties["802-11-wireless-security"] = {
                "key-mgmt": ("s", "none"),
                "wep-key-type": ("u", 2),
                "wep-key0": ("s", psk),
                "auth-alg": ("s", "shared"),
            }
        else:
            return {
                "error": "unknown_security_type",
                "message": "Unknown security type",
            }

        try:
            NetworkManagerSettings().add_connection(properties)
            return {"status": "success"}
        except exceptions.NmSettingsPermissionDeniedError:
            logging.exception("Insufficient privileges")
            return {
                "error": "insufficient_privileges",
                "message": "Insufficient privileges",
            }
        except exceptions.NmConnectionInvalidPropertyError:
            logging.exception("Invalid property")
            return {"error": "psk_invalid", "message": "Invalid password"}
        except Exception as e:
            logging.exception("Couldn't add network")
            return {"error": "unknown", "message": "Couldn't add network" + f"\n{e}"}

    def disconnect_network(self):
        self.wlan_device.disconnect()

    def delete_network(self, ssid):
        if path := self.get_connection_path_by_ssid(ssid):
            self.delete_connection_path(path)
        else:
            logging.debug(f"SSID '{ssid}' not found among saved connections")

    def delete_connection_path(self, path):
        try:
            NetworkConnectionSettings(path).delete()
            logging.info(f"Deleted connection path: {path}")
        except Exception as e:
            logging.exception(f"Failed to delete connection path: {path} - {e}")
            return {
                "error": "deletion_failed",
                "message": "Failed to delete connection" + f"\n{e}",
            }

    def rescan(self):
        try:
            return self.wlan_device.request_scan({})
        except Exception as e:
            self.popup(f"Unexpected error: {e}")

    def get_connection_path_by_ssid(self, ssid):
        existing_networks = NetworkManagerSettings().list_connections()
        for connection_path in existing_networks:
            connection_settings = NetworkConnectionSettings(
                connection_path
            ).get_settings()
            if (
                connection_settings.get("802-11-wireless")
                and connection_settings["802-11-wireless"].get("ssid")
                and connection_settings["802-11-wireless"]["ssid"][1].decode() == ssid
            ):
                return connection_path
        return None

    def connect(self, ssid):
        if target_connection := self.get_connection_path_by_ssid(ssid):
            self.popup(f"{ssid}\n{'Starting WiFi Association'}", 1)
            try:
                active_connection = self.nm.activate_connection(target_connection)
                return target_connection
            except Exception as e:
                logging.exception("Unexpected error")
                self.popup(f"Unexpected error: {e}")
        else:
            self.popup(f"SSID '{ssid}' not found among saved connections")

    def toggle_wifi(self, enable):
        self.nm.wireless_enabled = enable

    def get_ethernet_status(self):
        import subprocess
        import re
        
        try:
            # 1. Получаем список Ethernet интерфейсов через ip command
            result = subprocess.run(
                ['/usr/bin/ip', '-o', 'link', 'show'],
                capture_output=True, text=True, timeout=5
            )
            
            ethernet_interfaces = []
            for line in result.stdout.split('\n'):
                if line.strip():
                    parts = line.split(': ')
                    if len(parts) >= 2:
                        iface_name = parts[1].split('@')[0]
                        # Пропускаем loopback и виртуальные интерфейсы
                        if iface_name not in ['lo', 'docker0', 'br-'] and \
                        (iface_name.startswith('eth') or iface_name.startswith('end')):
                            ethernet_interfaces.append(iface_name)
            
            self.popup(f"Найдено Ethernet интерфейсов: {ethernet_interfaces}", 1)
            
            if not ethernet_interfaces:
                return {"connected": False, "ip_address": None, "state": 0, "interface": None}
            
            # 2. Проверяем каждый интерфейс
            for iface in ethernet_interfaces:
                # Проверка наличия линка (кабель подключен)
                try:
                    with open(f'/sys/class/net/{iface}/carrier', 'r') as f:
                        carrier = f.read().strip()
                    link_up = carrier == '1'
                except:
                    link_up = False
                
                # Получаем IP адрес
                ip_address = None
                if link_up:
                    result = subprocess.run(
                        ['/usr/bin/ip', '-4', 'addr', 'show', iface],
                        capture_output=True, text=True, timeout=5
                    )
                    match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', result.stdout)
                    if match:
                        ip_address = match.group(1)
                
                self.popup(f"Ethernet {iface}: link={link_up}, ip={ip_address}", 1)
                
                # Если есть IP — считаем подключенным
                if link_up and ip_address:
                    return {
                        "connected": True,
                        "ip_address": ip_address,
                        "state": 100,
                        "interface": iface
                    }
            
            # Кабель есть, но IP нет
            return {
                "connected": False,
                "ip_address": None,
                "state": 30,  # DISCONNECTED
                "interface": ethernet_interfaces[0] if ethernet_interfaces else None
            }
            
        except Exception as e:
            self.popup(f"Ошибка получения Ethernet статуса: {e}", 2)
            return {"connected": False, "ip_address": None, "state": 0, "interface": None}
        
    def monitor_connection_status(self):
        state = self.wlan_device.state
        if self.wifi_state != state:
            logging.debug(f"State changed: {state} {self.wlan_device.state_reason}")
            if self.wifi_state == -1:
                logging.debug("Starting to monitor state")
            elif state in [
                enums.DeviceState.PREPARE,
                enums.DeviceState.CONFIG,
            ]:
                self.popup("Connecting", 1)
            elif state in [
                enums.DeviceState.IP_CONFIG,
                enums.DeviceState.IP_CHECK,
                enums.DeviceState.SECONDARIES,
            ]:
                self.popup("Getting IP address", 1)
            elif state in [
                enums.DeviceState.ACTIVATED,
            ]:
                self.popup("Network connected", 1)
            elif state in [
                enums.DeviceState.DISCONNECTED,
                enums.DeviceState.DEACTIVATING,
            ]:
                self.popup("Network disconnected")
            elif state == enums.DeviceState.FAILED:
                self.popup("Connection failed")
            self.wifi_state = state
        return self.monitor_connection

    def enable_monitoring(self, enable):
        self.monitor_connection = enable




