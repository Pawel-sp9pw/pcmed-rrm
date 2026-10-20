#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Uruchom jako root na hoscie Proxmox VE.' >&2; exit 1; }
for command in qm pveversion curl sha256sum; do
  command -v "$command" >/dev/null || { echo "Brak $command; to musi byc host Proxmox VE." >&2; exit 1; }
done
revision=764e4232ba28afd07503bb4ab5e69c437eaa3f53
core_revision=5888304899562faec368dfec7648edbe8c417020
expected=1496e20436a2ea249a5f4531327f767c9b95fef8922e9aefe9a295e2eff51ed6
umask 077
installer=$(mktemp)
trap 'rm -f -- "$installer"' EXIT
curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
  "https://raw.githubusercontent.com/community-scripts/ProxmoxVE/$revision/vm/docker-vm.sh" -o "$installer"
printf '%s  %s\n' "$expected" "$installer" | sha256sum --check --status
cat <<'MESSAGE'
PC MED: tworzenie NOWEJ VM przez oficjalny Docker VM Community Scripts.
To nie jest instalacja Dockera na hoscie Proxmox ani uprzywilejowany LXC.
Skrypt zewnetrzny pracuje jako root, pobiera obrazy OS i Docker oraz zmienia hosta.
Przeczytaj jego kod i zasady projektu przed zatwierdzeniem.

W kreatorze wybierz Advanced, Debian 13, min. 4 CPU / 8 GB RAM / 40 GB dysku.
Wlacz Cloud-Init, ustaw imiennego uzytkownika i klucz SSH (bez autologowania root).
Adres centrali: 172.20.0.8. Wpisz WLASNY prefiks, brame, DNS, bridge i storage.
Nie zgadujemy /24 ani adresu bramy. Upewnij sie, ze 172.20.0.8 jest wolny.
VM musi miec dostep do internetu na czas pobierania oraz trasy do sieci VPN.
MESSAGE
read -r -p 'Wpisz CREATE, aby uruchomic kreator Community Scripts: ' confirmation
[[ "$confirmation" == CREATE ]] || exit 1
export COMMUNITY_SCRIPTS_URL="https://raw.githubusercontent.com/community-scripts/ProxmoxVE/$revision"
export COMMUNITY_SCRIPTS_CORE_URL="https://raw.githubusercontent.com/community-scripts/core/$core_revision"
unset COMMUNITY_SCRIPTS_CORE_DIR
bash "$installer"
printf '\nVM utworzona przez kreator. Instalacja aplikacji: docs/PROXMOX.md, etap 2.\n'
