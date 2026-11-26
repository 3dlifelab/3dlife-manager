import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
import subprocess
from uuid import uuid4

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
    if str(freq) == "2484":
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
    elif freq == 5935:
        return "6", "2"
    elif 5955 <= freq <= 7115:
        return "6", str(int((freq - 5950) / 5))
    else:
        return "?", "?"


AP_INTERFACE = "uap0"
AP_SETUP_UNIT = Path("/etc/systemd/system/3dlife-ap-interface.service")


def station_settings(profile):
    wireless = profile.get("802-11-wireless")
    if wireless is None or "ssid" not in wireless:
        return None
    if wireless.get("mode", ("s", "infrastructure"))[1] != "infrastructure":
        return None
    interface = profile["connection"].get("interface-name")
    if interface and interface[1] == AP_INTERFACE:
        return None
    return wireless


def management_ap_configured():
    return AP_SETUP_UNIT.is_file() or Path("/sys/class/net", AP_INTERFACE).exists()


class HotspotChannelError(Exception):
    pass


@dataclass(frozen=True)
class WifiTarget:
    path: str
    security: str
    band: str
    channel: int

    @property
    def channel_settings(self):
        return {"band": ("s", self.band), "channel": ("u", self.channel)}


def access_point_security(ap):
    flags = ap.rsn_flags | ap.wpa_flags
    if not flags and ap.flags & 1:
        return "WEP"
    return get_encryption(flags) or "Unknown"


class SdbusNm:
    def popup_handler(self,msg, level=0):
        print(f"[POPUP-{level}] {msg}")
    def __init__(self, popup_callback):
        self.popup = popup_callback  # ← Сначала сохраняем колбэк
        
        # Инициализация D-Bus
        self.system_bus = sdbus.sd_bus_open_system()
        if self.system_bus is None:
            raise RuntimeError("Системная шина D-Bus недоступна")

        sdbus.set_default_bus(self.system_bus)
        
        self.nm = NetworkManager(bus=self.system_bus)
        wireless_interfaces = self.get_wireless_interfaces()
        self.wlan_device = wireless_interfaces[0] if wireless_interfaces else None
        self.wifi = self.wlan_device is not None
        self.monitor_connection = False
        self.wifi_state = -1

    def is_wifi_enabled(self):
        return self.nm.wireless_enabled

    def get_interfaces(self):
        return [
            NetworkDeviceGeneric(device).interface for device in self.nm.get_devices()
        ]

    def get_wireless_interfaces(self):
        interfaces = []
        for path in self.nm.get_devices():
            device = NetworkDeviceGeneric(path)
            if device.device_type != enums.DeviceType.WIFI:
                continue
            if device.interface == AP_INTERFACE or not device.managed:
                continue
            wireless = NetworkDeviceWireless(path)
            if wireless.mode != enums.WiFiOperationMode.AP:
                interfaces.append(wireless)
        return sorted(interfaces, key=lambda device: device.interface != "wlan0")

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
            if wireless := station_settings(con_settings):
                known_networks.append(
                    {
                        "SSID": wireless["ssid"][1].decode(errors="surrogateescape"),
                        "UUID": con_settings["connection"]["uuid"][1],
                    }
                )
        return known_networks

    def is_known(self, ssid):
        return any(net["SSID"] == ssid for net in self.get_known_networks())

    def get_ip_address(self, active_path=None):
        if not self.wlan_device:
            return None
        device_connection = self.wlan_device.active_connection
        if device_connection == "/" or (active_path and device_connection != active_path):
            return None
        config_path = ActiveConnection(device_connection).ip4_config
        if config_path == "/":
            return None
        addresses = IPv4Config(config_path).address_data
        return addresses[0]["address"][1] if addresses else None

    def get_networks(self):
        if not self.wlan_device:
            return []
        known_ssids = {network["SSID"] for network in self.get_known_networks()}
        networks = []
        for path in self.wlan_device.access_points:
            ap = AccessPoint(path)
            ssid = ap.ssid.decode("utf-8", errors="surrogateescape")
            if not ssid:
                continue
            networks.append({
                "SSID": ssid,
                "known": ssid in known_ssids,
                "security": access_point_security(ap),
                "frequency": WifiChannels(ap.frequency)[0],
                "signal_level": ap.strength,
                "BSSID": ap.hw_address,
            })
        return sorted(networks, key=lambda network: network["signal_level"], reverse=True)

    def get_bssid_from_ssid(self, ssid):
        return next(net["BSSID"] for net in self.get_networks() if ssid == net["SSID"])

    def get_connected_ap(self):
        if not self.wlan_device:
            return None
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

    def select_hotspot_compatible_target(self, ssid):
        if not management_ap_configured():
            return None

        hotspot = Path("/sys/class/net", AP_INTERFACE)
        station = Path("/sys/class/net", self.wlan_device.interface)
        try:
            if (hotspot / "phy80211").resolve(strict=True) != (station / "phy80211").resolve(strict=True):
                return None
            hotspot_address = (hotspot / "address").read_text().strip().lower()
            result = subprocess.run(
                ["/usr/sbin/iw", "dev", AP_INTERFACE, "info"],
                capture_output=True, text=True, timeout=2, check=True,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise HotspotChannelError("Не удалось определить канал точки управления") from error

        match = re.search(r"^\s*channel\s+(\d+)\s+\((\d+) MHz\)", result.stdout, re.MULTILINE)
        if not match:
            raise HotspotChannelError("Не удалось определить канал точки управления")
        channel, frequency = map(int, match.groups())
        band = {"2.4": "bg", "5": "a", "6": "6GHz"}.get(WifiChannels(frequency)[0])
        if band is None:
            raise HotspotChannelError(f"Точка управления работает на неподдерживаемой частоте {frequency} МГц")

        selected_path = None
        selected_ap = None
        for path in self.wlan_device.access_points:
            ap = AccessPoint(path)
            if ap.ssid.decode("utf-8", errors="surrogateescape") != ssid or ap.frequency != frequency:
                continue
            if ap.hw_address.lower() == hotspot_address:
                continue
            if selected_ap is None or ap.strength > selected_ap.strength:
                selected_path, selected_ap = path, ap

        if selected_ap is None:
            raise HotspotChannelError(
                f"Сеть недоступна на канале {channel} ({frequency} МГц), "
                "который использует точка управления"
            )

        return WifiTarget(selected_path, access_point_security(selected_ap), band, channel)

    @staticmethod
    def pin_saved_profile(connection_path, target):
        profile = NetworkConnectionSettings(connection_path)
        settings = profile.get_settings()
        wireless = settings["802-11-wireless"]
        if all(wireless.get(key) == value for key, value in target.channel_settings.items()):
            return

        # GetSettings never returns secrets. Keep credentials when saving the channel lock.
        for section in ("802-11-wireless-security", "802-1x"):
            if section in settings:
                secrets = profile.get_secrets(section)
                settings[section].update(secrets.get(section, {}))
        wireless.update(target.channel_settings)
        profile.update(settings)

    def add_network(self, ssid, psk, eap_method, identity="", phase2=None, *, target=None):
        security_type = target.security if target else self.get_security_type(ssid)
        logging.debug(f"Adding network of type: {security_type}")
        if security_type is None:
            return {"error": "network_not_found", "message": "Network not found"}

        properties: NetworkManagerConnectionProperties = {
            "connection": {
                "id": ("s", ssid),
                "uuid": ("s", str(uuid4())),
                "type": ("s", "802-11-wireless"),
                "interface-name": ("s", self.wlan_device.interface),
            },
            "802-11-wireless": {
                "mode": ("s", "infrastructure"),
                "ssid": ("ay", ssid.encode("utf-8", errors="surrogateescape")),
            },
            "ipv4": {"method": ("s", "auto")},
            "ipv6": {"method": ("s", "auto")},
        }

        if target:
            properties["802-11-wireless"].update(target.channel_settings)

        if security_type not in ("Open", "OWE", "OWE-TM") and not psk:
            return {"error": "Password required for new network"}

        if security_type == "Open":
            return self.save_network(properties)
        if "WPA-PSK" in security_type:
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
            return {"error": "WPA3 Enterprise Suite-B requires certificate configuration"}
        elif "OWE" in security_type:
            properties["802-11-wireless-security"] = {
                "key-mgmt": ("s", "owe"),
            }
        elif "802.1x" in security_type:
            if not eap_method or not identity:
                return {"error": "EAP method and identity are required"}
            properties["802-11-wireless-security"] = {"key-mgmt": ("s", "wpa-eap")}
            properties["802-1x"] = {
                "eap": ("as", [eap_method]),
                "identity": ("s", identity),
                "password": ("s", psk),
            }
            if phase2:
                key = "phase2-autheap" if eap_method == "ttls" else "phase2-auth"
                properties["802-1x"][key] = ("s", phase2)
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

        return self.save_network(properties)

    @staticmethod
    def save_network(properties):
        try:
            path = NetworkManagerSettings().add_connection(properties)
            return {"path": path}
        except exceptions.NmSettingsPermissionDeniedError:
            logging.exception("Insufficient privileges")
            return {
                "error": "insufficient_privileges",
                "message": "Insufficient privileges",
            }
        except exceptions.NmConnectionInvalidPropertyError:
            logging.exception("Invalid property")
            return {"error": "psk_invalid", "message": "Invalid password"}
        except Exception:
            logging.exception("Couldn't add network")
            raise

    def disconnect_network(self):
        self.wlan_device.disconnect()

    def delete_network(self, ssid):
        preferred_path = None
        if self.wlan_device:
            active_path = self.wlan_device.active_connection
            if active_path != "/":
                preferred_path = ActiveConnection(active_path).connection

        path = self.get_connection_path_by_ssid(ssid, preferred_path)
        if path is None:
            return False

        self.delete_connection_path(path)
        return True

    def delete_connection_path(self, path):
        NetworkConnectionSettings(path).delete()

    def rescan(self):
        self.wlan_device.request_scan({})

    def get_connection_path_by_ssid(self, ssid, preferred_path=None):
        first_match = None
        for path in NetworkManagerSettings().list_connections():
            wireless = station_settings(NetworkConnectionSettings(path).get_settings())
            if wireless is None or wireless["ssid"][1].decode(errors="surrogateescape") != ssid:
                continue
            if preferred_path is None or path == preferred_path:
                return path
            first_match = first_match or path
        return first_match

    def connect(self, connection_path, target=None):
        device_path = self.nm.get_device_by_ip_iface(self.wlan_device.interface)
        return self.nm.activate_connection(connection_path, device_path, target.path if target else "/")

    def toggle_wifi(self, enable):
        self.nm.wireless_enabled = enable

    def get_ethernet_status(self):
        try:
            result = subprocess.run(
                ["/usr/bin/ip", "-j", "-4", "address", "show"],
                capture_output=True, text=True, timeout=3, check=True,
            )
            interfaces = json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, ValueError):
            logging.exception("Could not read interface addresses")
            return {"connected": False, "ip_address": None, "state": 0, "interface": None}

        first_interface = None
        for interface in interfaces:
            name = interface["ifname"]
            if not name.startswith(("eth", "en")) or interface.get("link_type") != "ether":
                continue
            first_interface = first_interface or name
            if "LOWER_UP" not in interface.get("flags", []):
                continue
            for address in interface.get("addr_info", []):
                if address.get("family") == "inet":
                    return {
                        "connected": True,
                        "ip_address": address["local"],
                        "state": 100,
                        "interface": name,
                    }

        return {
            "connected": False,
            "ip_address": None,
            "state": 30 if first_interface else 0,
            "interface": first_interface,
        }

    def monitor_connection_status(self):
        state = self.wlan_device.state if self.wlan_device else enums.DeviceState.UNAVAILABLE
        if self.wifi_state != state:
            logging.debug("Wi-Fi state changed to %s", state)
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




