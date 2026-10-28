#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo 'Uruchom jako root na hoscie Proxmox VE.' >&2; exit 1; }
for command in pveversion pct pvesh pvesm; do
  command -v "$command" >/dev/null || { echo "Brak $command: to musi byc host Proxmox VE." >&2; exit 1; }
done
missing=no
for command in git python3 curl openssl whiptail; do
  command -v "$command" >/dev/null || missing=yes
done
if [[ "$missing" == yes || ! -s /etc/ssl/certs/ca-certificates.crt ]]; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y git python3 curl openssl whiptail ca-certificates
fi
staging=$(mktemp -d /tmp/pcmed-lxc.XXXXXXXX)
cleanup() {
  [[ "$staging" == /tmp/pcmed-lxc.* && -d "$staging" && ! -L "$staging" ]] && rm -rf -- "$staging"
}
trap cleanup EXIT
source_root=''
if [[ -f "${BASH_SOURCE[0]:-}" ]]; then
  candidate=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
  if [[ -f "$candidate/compose.yaml" && -f "$candidate/deploy/proxmox/lxc.py" ]] && git -C "$candidate" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    source_root="$candidate"
  fi
fi
if [[ -z "$source_root" ]]; then
  git -c core.hooksPath=/dev/null clone --branch codex/rmm-mvp --single-branch \
    https://github.com/Pawel-sp9pw/pcmed-rrm.git "$staging/source"
  source_root="$staging/source"
fi
python3 "$source_root/deploy/proxmox/lxc.py" --source-root "$source_root" "$@"
