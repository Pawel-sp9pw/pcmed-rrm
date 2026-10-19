"""Generate local-only deployment configuration; never overwrite an existing installation."""
import argparse
import ipaddress
import json
import re
import secrets
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hostname", required=True)
    parser.add_argument("--vpn-bind", required=True)
    parser.add_argument("--artifact-host", action="append", required=True)
    args = parser.parse_args()
    hostname = args.hostname.lower()
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", hostname):
        parser.error("Use a DNS hostname without scheme or port")
    address = ipaddress.ip_address(args.vpn_bind)
    if address.version != 4 or not address.is_private or address.is_unspecified or address.is_loopback:
        parser.error("Use the server's private VPN IPv4 address")
    hosts = [host.lower() for host in args.artifact_host]
    if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host) for host in hosts):
        parser.error("Artifact hosts must be DNS hostnames")
    root = Path(__file__).resolve().parent.parent
    directory = root / "secrets"
    if (root / ".env").exists() or directory.exists():
        parser.error("Configuration exists; update it deliberately instead of rotating live secrets")
    directory.mkdir(mode=0o700)
    (directory / "packages").mkdir()
    origin = "https://" + hostname
    realm = (root / "deploy" / "realm.template.json").read_text(encoding="utf-8").replace("${ORIGIN}", origin)
    (directory / "realm.json").write_text(json.dumps(json.loads(realm), indent=2), encoding="utf-8")
    (directory / "frontend-config.json").write_text(json.dumps({"authority": origin + "/realms/pcmed", "clientId": "pcmed-console"}), encoding="utf-8")
    values = {"PCMED_HOSTNAME": hostname, "VPN_BIND_ADDRESS": str(address), "ARTIFACT_HOSTS": ",".join(hosts),
              "DATABASE_PASSWORD": secrets.token_hex(32), "IDENTITY_DATABASE_PASSWORD": secrets.token_hex(32), "KEYCLOAK_ADMIN_PASSWORD": secrets.token_hex(32)}
    environment = root / ".env"
    environment.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8")
    environment.chmod(0o600)
    print("Configuration generated. Install trusted TLS files as secrets/tls.crt and secrets/tls.key. Read README before startup.")


if __name__ == "__main__":
    main()
