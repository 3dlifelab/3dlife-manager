from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from app import app
from sdbus_utils import SdbusNm, enums


class StationIsolationTests(TestCase):
    def setUp(self):
        self.manager = SdbusNm.__new__(SdbusNm)
        self.manager.nm = Mock()
        self.manager.wlan_device = SimpleNamespace(active_connection="/active")
        self.client = app.test_client()

    def test_forget_active_station_when_ap_has_same_ssid(self):
        paths = ["/ap", "/inactive_station", "/active_station"]
        profiles = {path: Mock() for path in paths}
        for path, profile in profiles.items():
            mode = "ap" if path == "/ap" else "infrastructure"
            profile.get_settings.return_value = {
                "connection": {},
                "802-11-wireless": {"ssid": ("ay", b"example"), "mode": ("s", mode)},
            }

        with (
            patch("app.network_manager", return_value=self.manager),
            patch("sdbus_utils.ActiveConnection", return_value=SimpleNamespace(connection="/active_station")),
            patch("sdbus_utils.NetworkConnectionSettings", side_effect=profiles.__getitem__),
            patch("sdbus_utils.NetworkManagerSettings") as settings,
        ):
            settings.return_value.list_connections.return_value = paths
            response = self.client.delete("/wifi/network/example")
            self.assertEqual(response.status_code, 200)
            profiles["/active_station"].delete.assert_called_once_with()
            profiles["/inactive_station"].delete.assert_not_called()
            profiles["/ap"].delete.assert_not_called()

            settings.return_value.list_connections.return_value = ["/ap"]
            self.assertEqual(self.client.delete("/wifi/network/example").status_code, 404)
            profiles["/ap"].delete.assert_not_called()

    def test_only_managed_client_interfaces_are_selected(self):
        devices = {
            "/uap0": SimpleNamespace(interface="uap0", managed=True, device_type=enums.DeviceType.WIFI),
            "/monitor": SimpleNamespace(interface="wlan2", managed=False, device_type=enums.DeviceType.WIFI),
            "/hotspot": SimpleNamespace(interface="wlan1", managed=True, device_type=enums.DeviceType.WIFI),
            "/station": SimpleNamespace(interface="wlan0", managed=True, device_type=enums.DeviceType.WIFI),
        }
        wireless = {
            "/hotspot": SimpleNamespace(interface="wlan1", mode=enums.WiFiOperationMode.AP),
            "/station": SimpleNamespace(interface="wlan0", mode=enums.WiFiOperationMode.UNKNOWN),
        }
        self.manager.nm.get_devices.return_value = list(devices)

        with (
            patch("sdbus_utils.NetworkDeviceGeneric", side_effect=devices.__getitem__),
            patch("sdbus_utils.NetworkDeviceWireless", side_effect=wireless.__getitem__),
        ):
            self.assertEqual(self.manager.get_wireless_interfaces(), [wireless["/station"]])

    def test_global_radio_disable_is_rejected_for_management_ap(self):
        with (
            patch("app.management_ap_configured", return_value=True),
            patch("app.network_manager") as manager,
        ):
            response = self.client.post("/wifi/toggle", json={"enable": False})
            self.assertEqual(response.status_code, 409)
            manager.assert_not_called()
