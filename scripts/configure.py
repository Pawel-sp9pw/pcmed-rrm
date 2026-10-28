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
    parser.add_argument("--https-port", type=int, default=38443)
    parser.add_argument("--bootstrap-operator")
    parser.add_argument("--crl-port", type=int)
    args = parser.parse_args()
    if args.bootstrap_operator and not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{2,63}", args.bootstrap_operator):
        parser.error("Bootstrap operator must have 3..64 letters, digits, underscores or hyphens")
    if args.https_port != 443 and not 1024 <= args.https_port <= 49151:
        parser.error("HTTPS port must be 443 or in the configurable user-port range 1024..49151")
    if args.crl_port is not None and (not 1024 <= args.crl_port <= 49151 or args.crl_port == args.https_port):
        parser.error("CRL port must be a distinct user port 1024..49151")
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
    packages = directory / "packages"
    packages.mkdir()
    packages.chmod(0o755)
    if args.crl_port:
        public = directory / "pki-public"
        public.mkdir()
        public.chmod(0o755)
    origin = "https://" + hostname + (f":{args.https_port}" if args.https_port != 443 else "")
    realm = (root / "deploy" / "realm.template.json").read_text(encoding="utf-8").replace("${ORIGIN}", origin)
    realm = json.loads(realm)
    if args.bootstrap_operator:
        password = secrets.token_urlsafe(32)
        realm["users"] = [{"username": args.bootstrap_operator, "enabled": True,
                           "realmRoles": ["platform_admin"], "requiredActions": ["UPDATE_PASSWORD"],
                           "credentials": [{"type": "password", "value": password, "temporary": True}]}]
        first_login = directory / "first-login.json"
        first_login.write_text(json.dumps({"origin": origin, "username": args.bootstrap_operator, "password": password}, indent=2), encoding="utf-8")
        first_login.chmod(0o600)
    realm_file = directory / "realm.json"
    realm_file.write_text(json.dumps(realm, indent=2), encoding="utf-8")
    realm_file.chmod(0o644)
    frontend_config = directory / "frontend-config.json"
    frontend_config.write_text(json.dumps({"authority": origin + "/realms/pcmed", "clientId": "pcmed-console"}), encoding="utf-8")
    frontend_config.chmod(0o644)
    values = {"PCMED_HOSTNAME": hostname, "PCMED_ORIGIN": origin, "HTTPS_PORT": args.https_port, "VPN_BIND_ADDRESS": str(address), "ARTIFACT_HOSTS": ",".join(hosts),
              "DATABASE_PASSWORD": secrets.token_hex(32), "IDENTITY_DATABASE_PASSWORD": secrets.token_hex(32), "KEYCLOAK_ADMIN_PASSWORD": secrets.token_hex(32)}
    if args.crl_port:
        values.update({"CRL_PORT": args.crl_port, "COMPOSE_FILE": "compose.yaml:compose.pki.yaml"})
    environment = root / ".env"
    environment.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8")
    environment.chmod(0o600)
    print("Configuration generated. Install trusted TLS files as secrets/tls.crt and secrets/tls.key. Read README before startup.")


if __name__ == "__main__":
    main()
