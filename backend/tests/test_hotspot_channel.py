from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from app import app
from sdbus_utils import HotspotChannelError, SdbusNm, WifiTarget


class HotspotChannelTests(TestCase):
    def setUp(self):
        self.nm = SdbusNm.__new__(SdbusNm)
        self.nm.wlan_device = SimpleNamespace(
            interface="wlan0",
            access_points=["/same", "/other", "/local"],
        )

    def test_picks_same_frequency_even_if_other_band_is_stronger(self):
        def point(frequency, strength, address):
            return SimpleNamespace(
                frequency=frequency, strength=strength, ssid=b"Router",
                hw_address=address, flags=0, wpa_flags=0, rsn_flags=0,
            )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            phy = (root / "phy0")
            phy.mkdir()
            for name in ("wlan0", "uap0"):
                (root / name).mkdir()
                (root / name / "phy80211").symlink_to(phy)
            local_mac = "02:00:00:00:00:01"
            (root / "uap0" / "address").write_text(local_mac + "\n")
            aps = {
                "/same": point(2437, 30, "02:00:00:00:00:02"),
                "/other": point(5180, 99, "02:00:00:00:00:03"),
                "/local": point(2437, 100, local_mac),
            }
            with (
                patch("sdbus_utils.management_ap_configured", return_value=True),
                patch("sdbus_utils.Path", side_effect=lambda _, name: root / name),
                patch("sdbus_utils.subprocess.run", return_value=SimpleNamespace(
                    stdout="Interface uap0\n\tchannel 6 (2437 MHz), width: 20 MHz\n",
                )),
                patch("sdbus_utils.AccessPoint", side_effect=aps.__getitem__),
            ):
                target = self.nm.select_hotspot_compatible_target("Router")
                self.assertEqual(target, WifiTarget("/same", "Open", "bg", 6))

                with patch("sdbus_utils.NetworkManagerSettings") as settings:
                    self.nm.add_network("Router", "", None, target=target)
                    properties = settings.return_value.add_connection.call_args.args[0]
                    wireless = properties["802-11-wireless"]
                    self.assertEqual(wireless["band"], ("s", "bg"))
                    self.assertEqual(wireless["channel"], ("u", 6))

                self.nm.wlan_device.access_points = ["/other", "/local"]
                with self.assertRaisesRegex(HotspotChannelError, "2437"):
                    self.nm.select_hotspot_compatible_target("Router")

    def test_api_rejects_incompatible_target_before_touching_profiles(self):
        manager = Mock()
        manager.select_hotspot_compatible_target.side_effect = HotspotChannelError("wrong channel")
        with patch("app.network_manager", return_value=manager):
            response = app.test_client().post("/wifi/connect", json={"ssid": "Router", "password": "example"})
        self.assertEqual(response.status_code, 409)
        manager.get_connection_path_by_ssid.assert_not_called()
        manager.add_network.assert_not_called()
        manager.connect.assert_not_called()

    def test_pinning_a_saved_profile_preserves_credentials(self):
        with patch("sdbus_utils.NetworkConnectionSettings") as settings:
            profile = settings.return_value
            profile.get_settings.return_value = {
                "802-11-wireless": {},
                "802-11-wireless-security": {"key-mgmt": ("s", "wpa-psk")},
            }
            profile.get_secrets.return_value = {
                "802-11-wireless-security": {"psk": ("s", "example password")},
            }
            self.nm.pin_saved_profile("/profile", WifiTarget("/same", "", "bg", 6))
            updated = profile.update.call_args.args[0]
            self.assertEqual(updated["802-11-wireless"]["channel"], ("u", 6))
            self.assertEqual(updated["802-11-wireless-security"]["psk"], ("s", "example password"))

    def test_activation_uses_selected_access_point(self):
        self.nm.nm = Mock()
        self.nm.nm.get_device_by_ip_iface.return_value = "/wlan0"
        target = WifiTarget("/same", "", "bg", 6)
        self.nm.connect("/profile", target)
        self.nm.nm.activate_connection.assert_called_once_with("/profile", "/wlan0", "/same")

    def test_standalone_wifi_does_not_require_hotspot(self):
        with patch("sdbus_utils.management_ap_configured", return_value=False):
            self.assertIsNone(self.nm.select_hotspot_compatible_target("Router"))
