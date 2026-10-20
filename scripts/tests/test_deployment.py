import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("firewall", ROOT / "deploy/proxmox/firewall.py")
FIREWALL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIREWALL)


class DeploymentTests(unittest.TestCase):
    def configure(self, *options):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "scripts").mkdir()
        (root / "deploy").mkdir()
        shutil.copy2(ROOT / "scripts/configure.py", root / "scripts/configure.py")
        shutil.copy2(ROOT / "deploy/realm.template.json", root / "deploy/realm.template.json")
        arguments = [sys.executable, str(root / "scripts/configure.py"), "--hostname", "172.20.0.8", "--vpn-bind", "172.20.0.8", "--artifact-host", "172.20.0.8", *options]
        result = subprocess.run(arguments, capture_output=True, text=True)
        return root, result, arguments

    def test_high_port_propagates_to_oidc_and_panel(self):
        root, result, arguments = self.configure()
        self.assertEqual(result.returncode, 0, result.stderr)
        environment = (root / ".env").read_text()
        self.assertIn("PCMED_ORIGIN=https://172.20.0.8:38443\n", environment)
        self.assertIn("HTTPS_PORT=38443\n", environment)
        panel = json.loads((root / "secrets/frontend-config.json").read_text())
        self.assertEqual(panel["authority"], "https://172.20.0.8:38443/realms/pcmed")
        realm = json.loads((root / "secrets/realm.json").read_text())
        self.assertIn("https://172.20.0.8:38443", json.dumps(realm))
        original = (root / ".env").read_bytes()
        self.assertNotEqual(subprocess.run(arguments, capture_output=True).returncode, 0)
        self.assertEqual((root / ".env").read_bytes(), original)

    def test_standard_https_remains_explicitly_supported(self):
        root, result, _ = self.configure("--https-port", "443")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PCMED_ORIGIN=https://172.20.0.8\n", (root / ".env").read_text())

    def test_reject_invalid_ports(self):
        for port in ("0", "1023", "49152", "65536"):
            with self.subTest(port=port):
                root, result, _ = self.configure("--https-port", port)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root / ".env").exists())

    def test_docker_firewall_uses_original_destination(self):
        policy = FIREWALL.rules({"address": "172.20.0.8", "port": 38443, "allowed_cidrs": ["10.44.0.0/24", "172.20.0.0/24"]})
        self.assertIn("--ctorigdst 172.20.0.8 --ctorigdstport 38443 --ctdir ORIGINAL", policy)
        self.assertLess(policy.index("-s 10.44.0.0/24 -j RETURN"), policy.index("-j DROP"))
        self.assertNotIn("-F DOCKER-USER", policy)
        self.assertIn("-A PCMED-IN -j RETURN\nCOMMIT", policy)

    def test_firewall_requires_explicit_private_sources(self):
        for networks in ([], ["0.0.0.0/0"], ["8.8.8.0/24"], ["172.20.0.1/24"], ["10.0.0.0/7"], ["::/0"]):
            with self.subTest(networks=networks), self.assertRaises(ValueError):
                FIREWALL.rules({"address": "172.20.0.8", "port": 38443, "allowed_cidrs": networks})


if __name__ == "__main__":
    unittest.main()
