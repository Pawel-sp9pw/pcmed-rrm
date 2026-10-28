"""One host-side workflow: collect settings, create an unprivileged LXC, install and verify PC MED."""
import argparse
import hashlib
import ipaddress
import json
import os
import re
import secrets
import subprocess
import tempfile
import urllib.request
import uuid
from pathlib import Path

SCRIPTS_REVISION = "4a742048372462aa93b2e1246603604876c8f9c8"
CORE_REVISION = "a14f2d451d1b358673b5f89e170f66bd6631e249"
DOCKER_SCRIPT_SHA256 = "6c104947c3a1fbdb890393fc7e65210e1ac342a5ab5fc2a36c0336dcb8a7e7c8"
PRIVATE_NETWORKS = [ipaddress.IPv4Network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]


def validate(settings):
    network = ipaddress.IPv4Interface(settings["address_cidr"])
    if not any(network.network.subnet_of(block) for block in PRIVATE_NETWORKS) or network.network.prefixlen > 30:
        raise ValueError("Adres centrali musi byc w prywatnej sieci IPv4 z prefiksem /8../30.")
    if network.ip in (network.network.network_address, network.network.broadcast_address):
        raise ValueError("Adres centrali nie moze byc adresem sieci ani broadcast.")
    gateway = ipaddress.IPv4Address(settings["gateway"])
    if gateway not in network.network or gateway in (network.ip, network.network.network_address, network.network.broadcast_address):
        raise ValueError("Brama musi byc innym adresem hosta w tej samej podsieci.")
    for address in settings["dns"].split():
        if ipaddress.IPv4Address(address).is_unspecified or ipaddress.IPv4Address(address).is_loopback:
            raise ValueError("DNS musi byc dostepny z kontenera, nie 0.0.0.0 ani localhost.")
    if not settings["dns"].split():
        raise ValueError("Podaj przynajmniej jeden serwer DNS IPv4.")
    if not settings["allowed_cidrs"]:
        raise ValueError("Podaj dozwolone sieci zrodlowe VPN/zarzadzania.")
    for value in settings["allowed_cidrs"]:
        allowed = ipaddress.IPv4Network(value, strict=True)
        if not any(allowed.subnet_of(block) for block in PRIVATE_NETWORKS):
            raise ValueError("Dozwolone sieci musza byc prywatnymi CIDR, nie 0.0.0.0/0.")
    for key in ("bridge", "storage", "template_storage"):
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", settings[key]):
            raise ValueError(f"Nieprawidlowa wartosc {key}.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,62}", settings["hostname"]):
        raise ValueError("Nieprawidlowa nazwa kontenera.")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{2,63}", settings["operator"]):
        raise ValueError("Nieprawidlowa nazwa pierwszego operatora.")
    for name, minimum, maximum in (("ctid", 100, 999999999), ("cores", 2, 128), ("memory", 4096, 1048576), ("disk", 20, 65536), ("port", 1024, 49151), ("crl_port", 1024, 49151)):
        if not minimum <= settings[name] <= maximum:
            raise ValueError(f"{name}: dozwolony zakres {minimum}..{maximum}.")
    if settings["tls_mode"] not in ("auto", "import"):
        raise ValueError("TLS: wybierz auto albo import.")
    if settings["crl_port"] == settings["port"]:
        raise ValueError("Port CRL musi byc inny niz port HTTPS.")
    if settings["tls_mode"] == "import":
        for key in ("tls_cert", "tls_key", "trusted_ca"):
            if not Path(settings[key]).is_file():
                raise ValueError(f"Brak pliku {key} na hoscie Proxmox.")
    return str(network.ip)


def community_environment(settings, marker, password):
    return {
        "PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin"), "HOME": "/root", "TERM": os.environ.get("TERM", "xterm"),
        "LANG": "C.UTF-8", "LXC_PLATFORM": "pve", "mode": "generated", "MODE": "default", "PHS_SILENT": "1", "var_unattended": "1",
        "COMMUNITY_SCRIPTS_URL": f"https://raw.githubusercontent.com/community-scripts/ProxmoxVE/{SCRIPTS_REVISION}",
        "COMMUNITY_SCRIPTS_CORE_URL": f"https://raw.githubusercontent.com/community-scripts/core/{CORE_REVISION}",
        "var_os": "debian", "var_version": "13", "var_ctid": str(settings["ctid"]), "var_hostname": settings["hostname"],
        "var_cpu": str(settings["cores"]), "var_ram": str(settings["memory"]), "var_disk": str(settings["disk"]),
        "var_brg": settings["bridge"], "var_net": settings["address_cidr"], "var_gateway": settings["gateway"], "var_ns": ",".join(settings["dns"].split()),
        "var_container_storage": settings["storage"], "var_template_storage": settings["template_storage"],
        "var_unprivileged": "1", "var_nesting": "1", "var_keyctl": "1", "var_ssh": "no", "var_ipv6_method": "none",
        "var_docker_socket": "n", "var_docker_compose": "y", "var_docker_lxcfs": "n", "var_pw": password,
        "var_tags": f"pcmed;{marker}", "var_timezone": "Europe/Warsaw",
    }


def verify_container(configuration, settings, marker):
    values = dict(line.split(":", 1) for line in configuration.splitlines() if ":" in line and not line.startswith("#"))
    values = {key: value.strip() for key, value in values.items()}
    network = dict(item.split("=", 1) for item in values.get("net0", "").split(",") if "=" in item)
    features = set(values.get("features", "").split(","))
    if (values.get("unprivileged") != "1" or marker not in values.get("tags", "").split(";") or
            values.get("hostname") != settings["hostname"] or network.get("ip") != settings["address_cidr"] or
            network.get("bridge") != settings["bridge"] or not {"nesting=1", "keyctl=1"}.issubset(features)):
        raise ValueError("Utworzony CT nie ma oczekiwanej tozsamosci/ustawien. Odmowa instalacji w innym lub uprzywilejowanym kontenerze.")
    if values.get("lxc.apparmor.profile") == "unconfined":
        raise ValueError("Odmowa pracy z wylaczonym AppArmor. Zaktualizuj host Proxmox/LXC zamiast wylaczac izolacje.")


def ask(value, title, default=None):
    if value is not None:
        return value
    entered = input(title + (f" [{default}]" if default is not None else "") + ": ").strip()
    if entered:
        return entered
    if default is not None:
        return default
    raise ValueError(f"Pole wymagane: {title}")


def install(settings, source_root, runner=subprocess.run, downloader=urllib.request.urlopen, output_root=Path("/root"), log_root=Path("/var/log")):
    address = validate(settings)
    identifier = str(settings["ctid"])
    marker = "pcmed-install-" + uuid.uuid4().hex[:12]
    log_path = log_root / f"pcmed-lxc-{identifier}-{marker}.log"
    password = "PcMed_" + secrets.token_urlsafe(32)
    outputs = {"state": output_root / f"pcmed-lxc-{identifier}-install.json", "credentials": output_root / f"pcmed-lxc-{identifier}-first-login.json",
               "ca": output_root / f"pcmed-lxc-{identifier}-ca.crt"}
    if any(path.exists() or path.is_symlink() for path in outputs.values()):
        raise ValueError("Pliki poprzedniej instalacji dla tego CTID juz istnieja; odmowa nadpisania.")
    with log_path.open("x", encoding="utf-8") as logfile:
        log_path.chmod(0o600)

        def execute(arguments, capture=False, environment=None):
            result = runner(arguments, check=True, text=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE if capture else logfile,
                            stderr=logfile, env=environment)
            return result.stdout.strip() if capture else ""

        try:
            execute(["git", "-C", str(source_root), "diff", "--quiet"])
            execute(["git", "-C", str(source_root), "diff", "--cached", "--quiet"])
            revision = execute(["git", "-C", str(source_root), "rev-parse", "HEAD"], capture=True)
            available = execute(["pvesh", "get", "/cluster/nextid", "--vmid", identifier], capture=True)
            if available != identifier:
                raise ValueError("CTID jest juz zajety w klastrze. Wybierz inny numer.")
            execute(["ip", "link", "show", "dev", settings["bridge"]])
            for content, storage in (("rootdir", settings["storage"]), ("vztmpl", settings["template_storage"])):
                listing = execute(["pvesm", "status", "--content", content], capture=True)
                if not any(len(parts) >= 3 and parts[0] == storage and parts[2] == "active" for parts in (line.split() for line in listing.splitlines()[1:])):
                    raise ValueError(f"Storage {storage} nie jest aktywny lub nie obsluguje {content}.")
            state = {"ctid": settings["ctid"], "marker": marker, "source_revision": revision, "stage": "creating", "log": str(log_path), "root_password": password}

            def save_state():
                outputs["state"].write_text(json.dumps(state, indent=2), encoding="utf-8")
                outputs["state"].chmod(0o600)

            with tempfile.TemporaryDirectory(prefix="pcmed-lxc-") as temporary:
                temporary = Path(temporary)
                url = f"https://raw.githubusercontent.com/community-scripts/ProxmoxVE/{SCRIPTS_REVISION}/ct/docker.sh"
                with downloader(url, timeout=30) as response:
                    script = response.read(1048577)
                if len(script) > 1048576 or hashlib.sha256(script).hexdigest() != DOCKER_SCRIPT_SHA256:
                    raise ValueError("Instalator Community Scripts ma niezgodny SHA-256.")
                helper = temporary / "docker.sh"
                helper.write_bytes(script)
                save_state()
                print(f"[1/5] Tworze nieuprzywilejowany LXC {identifier} i instaluje Docker...")
                execute(["bash", str(helper)], environment=community_environment(settings, marker, password))
                configuration = execute(["pct", "config", identifier], capture=True)
                verify_container(configuration, settings, marker)
                execute(["pct", "set", identifier, "--onboot", "1"])
                if execute(["pct", "status", identifier], capture=True) != "status: running":
                    execute(["pct", "start", identifier])
                state["stage"] = "container-created"
                save_state()
                print("[2/5] Instaluje wymagane pakiety wewnatrz kontenera...")
                execute(["pct", "exec", identifier, "--", "apt-get", "update"])
                execute(["pct", "exec", identifier, "--", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y", "git", "python3", "openssl", "curl", "ca-certificates", "iproute2", "iptables"])
                print("[3/5] Przenosze te sama wersje PC MED do kontenera...")
                bundle = temporary / "source.bundle"
                execute(["git", "-C", str(source_root), "bundle", "create", str(bundle), "HEAD"])
                execute(["pct", "push", identifier, str(bundle), "/root/pcmed-source.bundle", "--perms", "0600"])
                execute(["pct", "exec", identifier, "--", "git", "-c", "core.hooksPath=/dev/null", "clone", "/root/pcmed-source.bundle", "/root/pcmed-source"])
                actual = execute(["pct", "exec", identifier, "--", "git", "-C", "/root/pcmed-source", "rev-parse", "HEAD"], capture=True)
                if actual != revision:
                    raise ValueError("Wersja kodu w kontenerze rozni sie od zatwierdzonej wersji hosta.")
                arguments = ["--bind", address, "--hostname", address, "--port", str(settings["port"]), "--operator", settings["operator"]]
                for network in settings["allowed_cidrs"]:
                    arguments.extend(["--allow-cidr", network])
                if settings["tls_mode"] == "auto":
                    arguments.extend(["--generate-tls", "--crl-port", str(settings["crl_port"])])
                else:
                    for option, field, destination in (("--tls-cert", "tls_cert", "/root/pcmed-tls.crt"), ("--tls-key", "tls_key", "/root/pcmed-tls.key"), ("--trusted-ca", "trusted_ca", "/root/pcmed-ca.crt")):
                        execute(["pct", "push", identifier, str(Path(settings[field]).resolve()), destination, "--perms", "0600"])
                        arguments.extend([option, destination])
                state["stage"] = "installing-service"
                save_state()
                print("[4/5] Konfiguruje HTTPS, bazy, panel, konta i usluge PC MED...")
                execute(["pct", "exec", identifier, "--", "bash", "/root/pcmed-source/deploy/proxmox/install-server.sh", *arguments])
                print("[5/5] Sprawdzam aktywna usluge i gotowosc HTTPS/OIDC/API...")
                execute(["pct", "exec", identifier, "--", "systemctl", "is-active", "--quiet", "pcmed-stack.service"])
                execute(["pct", "exec", identifier, "--", "python3", "/opt/pcmed-rmm/deploy/proxmox/verify-server.py", "--timeout", "30"])
                execute(["pct", "pull", identifier, "/etc/pcmed/first-login.json", str(outputs["credentials"])])
                execute(["pct", "pull", identifier, "/etc/pcmed/pki/trust.crt", str(outputs["ca"])])
                outputs["credentials"].chmod(0o600)
                outputs["ca"].chmod(0o644)
                probe_arguments = ["python3", str(source_root / "deploy/proxmox/verify-server.py"), "--origin", f"https://{address}:{settings['port']}",
                                   "--ca-file", str(outputs["ca"]), "--timeout", "30"]
                if settings["tls_mode"] == "auto":
                    probe_arguments.extend(["--crl-url", f"http://{address}:{settings['crl_port']}/ca.crl"])
                    execute(["pct", "exec", identifier, "--", "systemctl", "is-active", "--quiet", "pcmed-crl.timer"])
                execute(probe_arguments)
                state["stage"] = "verified"
                save_state()
        except Exception:
            print(f"Instalacja przerwana. Nie deklaruje gotowosci ani nie usuwam kontenera. CTID: {identifier}; log root: {log_path}")
            raise
    print(f"GOTOWE: https://{address}:{settings['port']} — LXC {identifier}, pcmed-stack aktywna i HTTPS/OIDC/API sprawdzone.")
    print(f"Pierwsze logowanie (zmiana hasla obowiazkowa): {outputs['credentials']}")
    print(f"Publiczny CA do importu na komputerach: {outputs['ca']}; klucz prywatny CA pozostaje w kontenerze.")


def main():
    parser = argparse.ArgumentParser(description="Automatyczna instalacja PC MED w nowym LXC Proxmox; brakujace dane sa zbierane przed instalacja.")
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[2])
    for name in ("ctid", "cores", "memory", "disk", "port", "crl-port"):
        parser.add_argument("--" + name, type=int)
    for name in ("address-cidr", "gateway", "dns", "bridge", "storage", "template-storage", "hostname", "operator", "tls-mode", "tls-cert", "tls-key", "trusted-ca"):
        parser.add_argument("--" + name)
    parser.add_argument("--allow-cidr", action="append", dest="allowed_cidrs")
    parser.add_argument("--yes", action="store_true")
    options = parser.parse_args()
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        parser.error("Uruchom jako root na hoscie Proxmox VE.")

    def resolve(value, title, default=None):
        if options.yes:
            if value is not None:
                return value
            if default is not None:
                return default
            parser.error(f"Tryb --yes wymaga wartosci: {title}")
        return ask(value, title, default)

    defaults = {"cores": 4, "memory": 8192, "disk": 40, "port": 38443, "crl_port": 38445, "hostname": "pcmed-central", "operator": "pcmed-admin", "tls_mode": "auto"}
    settings = {key: getattr(options, key) for key in defaults}
    for key, default in defaults.items():
        settings[key] = resolve(settings[key], key.replace("_", " "), default)
    next_id = options.ctid if options.ctid is not None else subprocess.check_output(["pvesh", "get", "/cluster/nextid"], text=True).strip()
    settings["ctid"] = int(resolve(options.ctid, "Nowy CTID", next_id))
    titles = {"address_cidr": "Adres centrali z rzeczywistym prefiksem, np. 172.20.0.8/24", "gateway": "Brama IPv4 kontenera", "dns": "DNS IPv4 (oddzielone spacjami)",
              "bridge": "Most Proxmox, np. vmbr0", "storage": "Storage dysku LXC, np. local-lvm", "template_storage": "Storage szablonow, np. local"}
    for key, title in titles.items():
        settings[key] = resolve(getattr(options, key), title)
    settings["allowed_cidrs"] = options.allowed_cidrs or resolve(None, "Dozwolone sieci VPN/zarzadzania (CIDR oddzielone spacjami)").split()
    for key in ("ctid", "cores", "memory", "disk", "port", "crl_port"):
        settings[key] = int(settings[key])
    if settings["tls_mode"] == "import":
        for key in ("tls_cert", "tls_key", "trusted_ca"):
            settings[key] = resolve(getattr(options, key), f"Sciezka PEM {key} na hoscie")
    address = validate(settings)
    print(f"Nowy LXC {settings['ctid']}, {settings['address_cidr']}, bridge {settings['bridge']}, storage {settings['storage']}, TLS {settings['tls_mode']}.")
    print("Zainstaluje Docker w NIEUPRZYWILEJOWANYM LXC z nesting/keyctl, PC MED i autostart. Nie wylaczam AppArmor. Nie modyfikuje istniejacego CT.")
    print(f"Panel: https://{address}:{settings['port']}. Wymagany dostep do internetu podczas instalacji oraz aktualny host PVE/LXC.")
    if not options.yes and input("Wpisz INSTALUJ, aby wykonac calosc: ").strip() != "INSTALUJ":
        raise SystemExit("Anulowano bez tworzenia kontenera.")
    install(settings, options.source_root.resolve())


if __name__ == "__main__":
    main()
