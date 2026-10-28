#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
address=172.20.0.8
hostname=172.20.0.8
port=38443
crl_port=38445
certificate=''
key=''
trusted_ca=''
generate_tls=no
operator=pcmed-admin
allowed=()
while (($#)); do
  case "$1" in
    --bind) address="${2:?}"; shift 2 ;;
    --hostname) hostname="${2:?}"; shift 2 ;;
    --port) port="${2:?}"; shift 2 ;;
    --crl-port) crl_port="${2:?}"; shift 2 ;;
    --tls-cert) certificate="${2:?}"; shift 2 ;;
    --tls-key) key="${2:?}"; shift 2 ;;
    --trusted-ca) trusted_ca="${2:?}"; shift 2 ;;
    --generate-tls) generate_tls=yes; shift ;;
    --operator) operator="${2:?}"; shift 2 ;;
    --allow-cidr) allowed+=("${2:?}"); shift 2 ;;
    *) echo "Nieznany argument: $1" >&2; exit 1 ;;
  esac
done
[[ $EUID -eq 0 ]] || { echo 'Uruchom jako root WEWNATRZ LXC/VM Docker.' >&2; exit 1; }
! command -v pveversion >/dev/null || { echo 'Nie instalujemy aplikacji na hoscie Proxmox.' >&2; exit 1; }
[[ ${#allowed[@]} -gt 0 ]] || {
  echo 'Wymagane --allow-cidr SIEC_VPN (mozna powtarzac).' >&2; exit 1;
}
if [[ "$generate_tls" == no ]]; then
  [[ -f "$certificate" && -f "$key" && -f "$trusted_ca" ]] || { echo 'Podaj --generate-tls albo --tls-cert PEM --tls-key PEM --trusted-ca PEM.' >&2; exit 1; }
  certificate=$(realpath -e -- "$certificate")
  key=$(realpath -e -- "$key")
  trusted_ca=$(realpath -e -- "$trusted_ca")
fi
for command in docker git python3 openssl ip ss systemctl iptables iptables-restore tar; do
  command -v "$command" >/dev/null || { echo "Brak $command. Zainstaluj wymagania z docs/PROXMOX.md." >&2; exit 1; }
done
docker compose version
docker info >/dev/null
source_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
git -C "$source_root" diff --quiet
git -C "$source_root" diff --cached --quiet
[[ ! -e /opt/pcmed-rmm && ! -L /opt/pcmed-rmm && ! -e /etc/pcmed && ! -L /etc/pcmed && ! -e /etc/systemd/system/pcmed-stack.service ]] || {
  echo 'Instalacja juz istnieje. Odmowa nadpisania konfiguracji i sekretow.' >&2; exit 1;
}
ip -j address show | python3 -c 'import json,sys; address=sys.argv[1]; found=any(item.get("local")==address for link in json.load(sys.stdin) for item in link.get("addr_info",[])); sys.exit(0 if found else "Adres bind nie jest przypisany do kontenera/VM")' "$address"
[[ "$port" =~ ^[0-9]+$ && "$port" -ge 1024 && "$port" -le 49151 ]] || { echo 'Nieprawidlowy port HTTPS.' >&2; exit 1; }
if ss -H -ltn "sport = :$port" | grep -q .; then echo 'Port jest juz zajety.' >&2; exit 1; fi
configuration_args=()
if [[ "$generate_tls" == yes ]]; then
  [[ "$crl_port" =~ ^[0-9]+$ && "$crl_port" -ge 1024 && "$crl_port" -le 49151 && "$crl_port" != "$port" ]] || { echo 'Nieprawidlowy port CRL.' >&2; exit 1; }
  if ss -H -ltn "sport = :$crl_port" | grep -q .; then echo 'Port CRL jest zajety.' >&2; exit 1; fi
  configuration_args=(--crl-port "$crl_port")
fi
python3 - "$source_root" "$address" "$port" "${allowed[@]}" <<'PYTHON'
import importlib.util
import sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("pcmed_firewall", Path(sys.argv[1]) / "deploy/proxmox/firewall.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.rules({"address": sys.argv[2], "port": int(sys.argv[3]), "allowed_cidrs": sys.argv[4:]})
PYTHON
tls_stage=$(mktemp -d /tmp/pcmed-tls.XXXXXXXX)
cleanup() {
  [[ "$tls_stage" == /tmp/pcmed-tls.* && -d "$tls_stage" && ! -L "$tls_stage" ]] && rm -rf -- "$tls_stage"
}
trap cleanup EXIT
if [[ "$generate_tls" == yes ]]; then
  python3 "$source_root/deploy/proxmox/tls.py" --directory "$tls_stage/issued" --hostname "$hostname" --address "$address" --crl-url "http://${address}:${crl_port}/ca.crl"
  certificate="$tls_stage/issued/server.crt"
  key="$tls_stage/issued/server.key"
  trusted_ca="$tls_stage/issued/ca.crt"
fi
openssl x509 -in "$certificate" -noout -checkend 86400
openssl verify -purpose sslserver -CAfile "$trusted_ca" "$certificate"
cert_public=$(openssl x509 -in "$certificate" -pubkey -noout | openssl pkey -pubin -outform DER | sha256sum)
key_public=$(openssl pkey -in "$key" -pubout -outform DER | sha256sum)
[[ "$cert_public" == "$key_public" ]] || { echo 'Certyfikat i klucz nie pasuja.' >&2; exit 1; }
if [[ "$hostname" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  openssl x509 -in "$certificate" -noout -checkip "$hostname" | grep -q 'does match'
else
  openssl x509 -in "$certificate" -noout -checkhost "$hostname" | grep -q 'does match'
fi
install -d -m 700 /opt/pcmed-rmm /etc/pcmed /etc/pcmed/pki
if [[ "$generate_tls" == yes ]]; then
  cp -a -- "$tls_stage/issued" /etc/pcmed/pki/issued
fi
git -C "$source_root" archive HEAD | tar -x -C /opt/pcmed-rmm
cd /opt/pcmed-rmm
python3 scripts/configure.py --hostname "$hostname" --vpn-bind "$address" --https-port "$port" --artifact-host "$hostname" --bootstrap-operator "$operator" "${configuration_args[@]}"
install -m 644 "$certificate" secrets/tls.crt
install -m 600 "$key" secrets/tls.key
install -m 644 "$trusted_ca" /etc/pcmed/pki/trust.crt
install -m 600 secrets/first-login.json /etc/pcmed/first-login.json
if [[ "$generate_tls" == yes ]]; then
  install -m 644 /etc/pcmed/pki/issued/ca.crl secrets/pki-public/ca.crl
fi
python3 - "$address" "$port" "${allowed[@]}" <<'PYTHON'
import json
import sys
from pathlib import Path
Path("/etc/pcmed/firewall.json").write_text(json.dumps({"address": sys.argv[1], "port": int(sys.argv[2]), "allowed_cidrs": sys.argv[3:]}))
PYTHON
if [[ "$generate_tls" == yes ]]; then
  python3 - "$crl_port" <<'PYTHON'
import json
import sys
from pathlib import Path
path = Path("/etc/pcmed/firewall.json")
configuration = json.loads(path.read_text())
configuration["crl_port"] = int(sys.argv[1])
path.write_text(json.dumps(configuration))
PYTHON
  cat > /etc/systemd/system/pcmed-crl.service <<'UNIT'
[Unit]
Description=Renew PC MED private CA signed revocation list
[Service]
Type=oneshot
UMask=0077
ExecStart=/usr/bin/python3 /opt/pcmed-rmm/deploy/proxmox/refresh-crl.py
UNIT
  cat > /etc/systemd/system/pcmed-crl.timer <<'UNIT'
[Unit]
Description=Daily PC MED CRL renewal
[Timer]
OnCalendar=daily
Persistent=true
[Install]
WantedBy=timers.target
UNIT
fi
chmod 600 /etc/pcmed/firewall.json
docker compose config --quiet
cat > /etc/systemd/system/pcmed-stack.service <<'UNIT'
[Unit]
Description=PC MED RMM stack and private Docker ingress policy
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target
PartOf=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/pcmed-rmm
ExecStartPre=/usr/bin/python3 /opt/pcmed-rmm/deploy/proxmox/firewall.py
ExecStart=/usr/bin/docker compose up --build --wait --wait-timeout 300
ExecStartPost=/usr/bin/python3 /opt/pcmed-rmm/deploy/proxmox/verify-server.py
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=1800
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target docker.service
UNIT
systemctl daemon-reload
if [[ "$generate_tls" == yes ]]; then systemctl enable --now pcmed-crl.timer; fi
if ! systemctl enable --now pcmed-stack.service; then
  journalctl -u pcmed-stack.service -n 80 --no-pager >&2
  docker compose ps -a >&2
  exit 1
fi
systemctl is-active --quiet pcmed-stack.service
printf '\nCentrala dziala: https://%s:%s\nPierwsze konto: /etc/pcmed/first-login.json (root, zmiana hasla przy pierwszym logowaniu).\n' "$hostname" "$port"
printf 'Sekrety: /opt/pcmed-rmm/.env (root). Nie udostepniaj tego pliku.\n'
