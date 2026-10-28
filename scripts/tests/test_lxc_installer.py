import contextlib
import hashlib
import functools
import http.server
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load(name, filename):
    specification = importlib.util.spec_from_file_location(name, ROOT / "deploy/proxmox" / filename)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


LXC = load("lxc_installer", "lxc.py")
TLS = load("installer_tls", "tls.py")
READINESS = load("installer_readiness", "verify-server.py")
CRL = load("installer_crl", "refresh-crl.py")


def settings():
    return {"ctid": 120, "address_cidr": "172.20.0.8/24", "gateway": "172.20.0.1", "dns": "172.20.0.1 1.1.1.1", "bridge": "vmbr0",
            "storage": "local-lvm", "template_storage": "local", "hostname": "pcmed-central", "operator": "pcmed-admin", "cores": 4,
            "memory": 8192, "disk": 40, "port": 38443, "crl_port": 38445, "allowed_cidrs": ["10.44.0.0/24", "172.20.0.0/24"], "tls_mode": "auto"}


class FakeProxmox:
    def __init__(self, failure=None):
        self.commands = []
        self.environment = None
        self.failure = failure

    def __call__(self, arguments, **options):
        self.commands.append(arguments)
        if self.failure and self.failure(arguments):
            raise subprocess.CalledProcessError(1, arguments)
        output = ""
        if arguments[0] == "bash":
            self.environment = options["env"]
        elif arguments[0] == "pvesh":
            output = "120"
        elif arguments[0] == "pvesm":
            output = "Name Type Status\nlocal-lvm lvmthin active\nlocal dir active\n"
        elif arguments[:2] == ["pct", "config"]:
            output = ("hostname: pcmed-central\nunprivileged: 1\nfeatures: nesting=1,keyctl=1\n"
                      "net0: name=eth0,bridge=vmbr0,ip=172.20.0.8/24,gw=172.20.0.1\ntags: " + self.environment["var_tags"])
        elif arguments[:2] == ["pct", "status"]:
            output = "status: running"
        elif arguments[:2] == ["pct", "pull"]:
            Path(arguments[-1]).write_text("test-export", encoding="utf-8")
        elif arguments[-2:] == ["rev-parse", "HEAD"]:
            output = "a" * 40
        return subprocess.CompletedProcess(arguments, 0, stdout=output)


class LxcInstallerTests(unittest.TestCase):
    def test_inputs_reject_unsafe_networks_and_shell_values(self):
        self.assertEqual(LXC.validate(settings()), "172.20.0.8")
        invalid = {"address_cidr": ["172.20.0.0/24", "172.20.0.255/24", "8.8.8.8/24", "172.20.0.8/32"],
                   "gateway": ["172.21.0.1", "172.20.0.8"], "dns": ["", "127.0.0.1"], "allowed_cidrs": [[], ["0.0.0.0/0"], ["10.0.0.1/24"]],
                   "bridge": ["vmbr0;reboot", "../vmbr0"], "operator": ["bad user"], "memory": [1024], "port": [22], "tls_mode": ["none"]}
        for key, values in invalid.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    LXC.validate({**settings(), key: value})

    def test_environment_is_unattended_pinned_and_has_no_docker_tcp_socket(self):
        environment = LXC.community_environment(settings(), "pcmed-install-test", "test-password")
        self.assertEqual(environment["mode"], "generated")
        self.assertEqual(environment["PHS_SILENT"], "1")
        self.assertEqual(environment["var_docker_socket"], "n")
        self.assertEqual(environment["var_unprivileged"], "1")
        self.assertEqual(environment["var_net"], "172.20.0.8/24")
        self.assertEqual(environment["var_ns"], "172.20.0.1,1.1.1.1")
        self.assertIn(LXC.CORE_REVISION, environment["COMMUNITY_SCRIPTS_CORE_URL"])
        self.assertNotIn("COMMUNITY_SCRIPTS_CORE_DIR", environment)

    def test_refuse_wrong_or_privileged_container(self):
        original = "hostname: pcmed-central\nunprivileged: 1\nfeatures: nesting=1,keyctl=1\nnet0: bridge=vmbr0,ip=172.20.0.8/24\ntags: nonce"
        LXC.verify_container(original, settings(), "nonce")
        for value in (original.replace("unprivileged: 1", "unprivileged: 0"), original.replace("tags: nonce", "tags: other"),
                      original.replace("172.20.0.8/24", "172.20.0.9/24"), original + "\nlxc.apparmor.profile: unconfined"):
            with self.subTest(configuration=value), self.assertRaises(ValueError):
                LXC.verify_container(value, settings(), "nonce")

    def run_install(self, runner, directory):
        script = b"test-helper"
        with patch.object(LXC, "DOCKER_SCRIPT_SHA256", hashlib.sha256(script).hexdigest()):
            LXC.install(settings(), ROOT, runner=runner, downloader=lambda *arguments, **options: io.BytesIO(script),
                        output_root=directory, log_root=directory)

    def test_complete_workflow_creates_installs_verifies_and_exports(self):
        runner = FakeProxmox()
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()) as output:
            directory = Path(temporary)
            self.run_install(runner, directory)
            state = json.loads((directory / "pcmed-lxc-120-install.json").read_text())
            self.assertEqual(state["stage"], "verified")
            self.assertNotIn(state["root_password"], output.getvalue())
            self.assertTrue(state["root_password"].startswith("PcMed_"))
            self.assertIn("GOTOWE", output.getvalue())
        commands = runner.commands
        helper_index = next(index for index, command in enumerate(commands) if command[0] == "bash")
        service_index = next(index for index, command in enumerate(commands) if "/root/pcmed-source/deploy/proxmox/install-server.sh" in command)
        self.assertLess(helper_index, service_index)
        self.assertIn("--generate-tls", commands[service_index])
        self.assertIn(["pct", "exec", "120", "--", "systemctl", "is-active", "--quiet", "pcmed-stack.service"], commands)
        self.assertTrue(any(command[0] == "python3" and "--origin" in command for command in commands))
        self.assertFalse(any("destroy" in command or "unconfined" in command for command in commands))

    def test_failed_service_or_host_probe_never_reports_success_or_removes_ct(self):
        for failure in (lambda command: "is-active" in command, lambda command: command[0] == "python3"):
            runner = FakeProxmox(failure=failure)
            with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()) as output:
                directory = Path(temporary)
                with self.assertRaises(subprocess.CalledProcessError):
                    self.run_install(runner, directory)
                state = json.loads((directory / "pcmed-lxc-120-install.json").read_text())
                self.assertNotEqual(state["stage"], "verified")
                self.assertNotIn("GOTOWE", output.getvalue())
                self.assertFalse(any("destroy" in command for command in runner.commands))

    def test_occupied_id_aborts_before_creation(self):
        runner = FakeProxmox()

        def occupied(arguments, **options):
            result = runner(arguments, **options)
            if arguments[0] == "pvesh":
                result.stdout = "121"
            return result

        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
            self.run_install(occupied, Path(temporary))
        self.assertFalse(any(command[0] == "bash" for command in runner.commands))

    def test_download_hash_mismatch_aborts_before_execution(self):
        runner = FakeProxmox()
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
            LXC.install(settings(), ROOT, runner=runner, downloader=lambda *arguments, **options: io.BytesIO(b"tampered"),
                        output_root=Path(temporary), log_root=Path(temporary))
        self.assertFalse(any(command[0] == "bash" for command in runner.commands))

    def test_existing_state_is_not_overwritten(self):
        runner = FakeProxmox()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            state = directory / "pcmed-lxc-120-install.json"
            state.write_text("existing", encoding="utf-8")
            with self.assertRaises(ValueError):
                self.run_install(runner, directory)
            self.assertEqual(state.read_text(), "existing")
        self.assertEqual(runner.commands, [])

    def test_readiness_failure_cannot_be_reported_as_success(self):
        with patch.object(READINESS, "probe", side_effect=ValueError("bad issuer")), patch.object(READINESS.ssl, "create_default_context"), self.assertRaises(RuntimeError):
            READINESS.verify("https://172.20.0.8:38443", "unused-ca", timeout=0)

    @unittest.skipUnless(shutil.which("openssl"), "OpenSSL required")
    def test_generated_tls_verifies_ip_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "issued"
            TLS.generate(directory, "172.20.0.8", "172.20.0.8", "http://172.20.0.8:38445/ca.crl")
            command = ["openssl", "verify", "-purpose", "sslserver", "-verify_ip", "172.20.0.8", "-CAfile", str(directory / "ca.crt"), "-crl_check", "-CRLfile", str(directory / "ca-crl.pem"), str(directory / "server.crt")]
            subprocess.run(command, check=True, capture_output=True)
            public = Path(temporary) / "public"
            public.mkdir()
            CRL.refresh(directory, public)
            self.assertTrue((public / "ca.crl").exists())
            self.assertFalse((public / "ca.key").exists())
            with self.assertRaises(FileExistsError):
                TLS.generate(directory, "172.20.0.8", "172.20.0.8")
            if os.name != "nt":
                self.assertEqual((directory / "ca.key").stat().st_mode & 0o777, 0o600)

    @unittest.skipUnless(os.name == "nt" and shutil.which("openssl") and shutil.which("pwsh"), "Windows/OpenSSL/PowerShell required")
    def test_windows_checks_online_revocation_without_importing_machine_ca(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "issued"
            handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
            with http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
                port = server.server_address[1]
                TLS.generate(directory, "172.20.0.8", "172.20.0.8", f"http://127.0.0.1:{port}/ca.crl")
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    script = "$root=[Security.Cryptography.X509Certificates.X509Certificate2]::CreateFromPem([IO.File]::ReadAllText($env:PCMED_TEST_PKI+'/ca.crt')); "
                    script += "$leaf=[Security.Cryptography.X509Certificates.X509Certificate2]::CreateFromPem([IO.File]::ReadAllText($env:PCMED_TEST_PKI+'/server.crt')); "
                    script += "$chain=[Security.Cryptography.X509Certificates.X509Chain]::new(); $chain.ChainPolicy.TrustMode='CustomRootTrust'; $null=$chain.ChainPolicy.CustomTrustStore.Add($root); "
                    script += "$chain.ChainPolicy.RevocationMode='Online'; if(-not $chain.Build($leaf)) { $chain.ChainStatus | Format-List; exit 1 }; $chain.Dispose(); $root.Dispose(); $leaf.Dispose()"
                    subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", script], env={**os.environ, "PCMED_TEST_PKI": str(directory)},
                                   capture_output=True, text=True, check=True, timeout=45)
                finally:
                    server.shutdown()
                    thread.join(timeout=5)
