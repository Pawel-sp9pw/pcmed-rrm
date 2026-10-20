# Proxmox Community Scripts → PC MED

To są **dwa wykonywalne etapy instalacji**, nie deklaracja, że VM została już utworzona. Nie mamy dostępu administracyjnego do Twojego Proxmox. Centrala ma adres **172.20.0.8**, z którym bramki klientów łączą się przez VPN.

## 1. Nowa VM Docker na Proxmox

Na **hoście Proxmox**, jako root:

```sh
git clone --branch codex/rmm-mvp --single-branch https://github.com/Pawel-sp9pw/pcmed-rrm.git
cd pcmed-rrm
less deploy/proxmox/create-vm.sh
bash deploy/proxmox/create-vm.sh
```

Wrapper pobiera i sprawdza SHA-256 oficjalnego [Docker VM z Proxmox Community Scripts](https://github.com/community-scripts/ProxmoxVE/blob/764e4232ba28afd07503bb4ab5e69c437eaa3f53/vm/docker-vm.sh), a po wpisaniu `CREATE` uruchamia jego kreator. Nie instaluje Dockera bezpośrednio na hoście PVE ani nie tworzy uprzywilejowanego kontenera. Community Scripts to zewnętrzny projekt, **PC MED nie jest oficjalnym skryptem w jego katalogu**.

Przypięte wersje: ProxmoxVE `764e4232ba28afd07503bb4ab5e69c437eaa3f53`, core `5888304899562faec368dfec7648edbe8c417020`. Kontrola SHA dotyczy głównego skryptu; core ma przypięte adresy wersji. Obrazy systemu, repozytoria pakietów i instalator Docker są nadal pobierane przez projekt upstream — nie jest to w pełni odtwarzalny/offline łańcuch dostaw. Przejrzyj zewnętrzny kod przed wykonaniem jako root.

W kreatorze:

- **Advanced**, Debian 13, minimum **4 CPU / 8 GB RAM / 40 GB dysku**; więcej miejsca na instalatory i kopie.
- Wybierz własne VMID, storage i bridge/VLAN.
- **Cloud-Init włączony**, imienny użytkownik i klucz SSH. Nie używaj wariantu nocloud z automatycznym logowaniem root.
- Adres **172.20.0.8 z rzeczywistym prefiksem**, właściwa brama i DNS. Prefiks, brama i bridge nie zostały podane — nie zakładamy ich wartości. Adres musi być wolny.
- Zapewnij trasę z VPN klientów do VM oraz dostęp do repozytoriów podczas instalacji. Nie wystawiaj panelu w internecie.

Poczekaj na zakończenie instalacji Docker w VM. W razie potrzeby sprawdź `/var/log/install-docker.log`. Zaloguj się do **VM**, nie do hosta PVE.

## 2. Instalacja centrali wewnątrz VM

Poniższe polecenia wykonuj jako root **w VM Docker**:

```sh
apt-get update
apt-get install -y git python3 openssl curl ca-certificates iproute2 iptables
docker version
docker compose version
git clone --branch codex/rmm-mvp --single-branch https://github.com/Pawel-sp9pw/pcmed-rrm.git /root/pcmed-source
cd /root/pcmed-source
```

Przygotuj certyfikat z firmowego CA, przeznaczony do TLS serwera, z **SAN IP:172.20.0.8**. Pełny łańcuch PEM zapisz np. jako `/root/certyfikaty/centrala.crt`, klucz PEM bez hasła jako `/root/certyfikaty/centrala.key`. Klucz pozostaje wyłącznie na serwerze. Publiczny certyfikat CA rozprowadź do operatorów i `LocalMachine\Root` bramek Windows. Przy własnym PKI zadbaj również o dostępność CRL/OCSP.

Uruchom instalator z **rzeczywistymi** sieciami źródłowymi VPN i zarządzania. Wartości poniżej zastąp swoimi, nie otwieraj `0.0.0.0/0`:

```sh
bash deploy/proxmox/install-server.sh \
  --tls-cert /root/certyfikaty/centrala.crt \
  --tls-key /root/certyfikaty/centrala.key \
  --allow-cidr 10.44.0.0/24 \
  --allow-cidr 172.20.0.0/24
```

Adresy sieci na końcu to **przykłady**, nie wykryta konfiguracja. Domyślnie `--bind 172.20.0.8 --hostname 172.20.0.8 --port 38443`. Dla własnego DNS można użyć `--hostname rmm.pcmed.lan`, z odpowiednim SAN i rekordem DNS na 172.20.0.8; wszystkie bramki muszą wtedy używać tego samego URL z portem.

Instalator sprawdza lokalny adres, wolny port, ważność certyfikatu i zgodność klucza, odmawia nadpisywania instalacji, kopiuje zatwierdzony lokalny commit do `/opt/pcmed-rmm`, generuje losowe sekrety i uruchamia usługę `pcmed-stack`. Port HTTPS jest publikowany **tylko na 172.20.0.8**; bazy pozostają wewnętrzne.

Zapora filtruje port publikowany przez Dockera w `DOCKER-USER` po oryginalnym adresie i porcie docelowym (DNAT). Nie polegamy wyłącznie na UFW. Reguły dotyczą tylko PC MED i są odtwarzane przy starcie systemd/Docker. Wymagany jest standardowy backend Docker **iptables**, nie eksperymentalny backend nftables. Dodatkowa zapora PVE/VPN musi dopuszczać TCP 38443 z wybranych sieci. Jeśli coś blokuje start, sprawdź dziennik; nie usuwaj kontroli zapory.

## 3. Sprawdzenie i konta

```sh
systemctl status pcmed-stack --no-pager
journalctl -u pcmed-stack -n 80 --no-pager
cd /opt/pcmed-rmm
docker compose ps -a
curl --fail --cacert /root/certyfikaty/firmowe-ca.crt \
  https://172.20.0.8:38443/realms/pcmed/.well-known/openid-configuration
```

Oczekiwany issuer: `https://172.20.0.8:38443/realms/pcmed`. Otwórz **https://172.20.0.8:38443**, następnie skonfiguruj konta i klientów według [WDROZENIE.md, sekcja 3.5](WDROZENIE.md#35-utwórz-konta-i-pierwszego-klienta). Hasło bootstrap jest w `/opt/pcmed-rmm/.env`, tylko dla administratora. MFA pozostaje opcjonalne. Nie udostępniaj `.env`, kluczy ani kopii bazy.

## 4. Bramki i wykrywanie na stacjach

- Centrala **TCP 38443** przez VPN; bramka **TCP 38444** tylko na wskazanym LAN IPv4 i podsieci klienta; agenci **bez portów przychodzących**.
- Porty 38443/38444 mieszczą się w nieprzypisanym zakresie 38423–38461 rejestru [IANA](https://www.iana.org/assignments/service-names-port-numbers/service-names-port-numbers.xhtml) sprawdzonym 20.10.2026. To zmniejsza ryzyko kolizji z przypisanymi usługami, **nie zapewnia bezpieczeństwa ani wyłączności**. Oba porty są konfigurowalne; instalatory kontrolują zajętość portu nasłuchu.
- Certyfikat bramki musi mieć EKU **serverAuth**, klucz prywatny i **SAN IP jej stałego adresu LAN** (np. IP:192.168.20.10); opcjonalnie także nazwę DNS. Instalacja wybiera konkretny certyfikat po thumbprint, a nie pierwszy pasujący Subject.
- `Install-Agent.ps1` bez `GatewayUrl` skanuje aktywny lokalny Ethernet/Wi-Fi: tylko RFC1918 IPv4, maks. 1022 adresy, 32 połączenia równolegle, jeden port, limit całego skanu 90 s. Nie skanuje całego VPN ani internetu; większe/wielokrotne sieci wymagają `-ScanCidr` obejmującego adres stacji.
- Skan nie wysyła sekretów. Wymaga SHA-256 certyfikatu otrzymanego niezależnie od administratora oraz prawidłowego zaufania CA, SAN i ważności. Sama odpowiedź „jestem bramką” nie wystarcza. Przy jednej pasującej bramce użytkownik wpisuje `TAK`; zero lub wiele wyników oznacza konieczność jawnego URL.
- Pin certyfikatu zostaje w konfiguracji i jest sprawdzany przy dalszych połączeniach. Nie wyłączamy walidacji TLS. Wymiana certyfikatu wymaga zaplanowanej aktualizacji pinów na agentach.

Dokładne polecenia instalacji bramki i końcówek: [WDROZENIE.md](WDROZENIE.md#5-instalacja-serwera-pośredniczącego-u-klienta).

## 5. Utrzymanie i istniejące instalacje

Kopie muszą obejmować oba PostgreSQL (aplikacja i Keycloak), `/opt/pcmed-rmm/.env`, `secrets/`, `/etc/pcmed/firewall.json` i certyfikaty; szyfruj je i przetestuj odtworzenie poza środowiskiem operacyjnym. Snapshot VM nie zastępuje sprawdzonej kopii baz.

Na wcześniejszej instalacji nie uruchamiaj ponownie konfiguratora. Zmiana portu/hosta zmienia issuer OIDC: uzgodnij przerwę, wykonaj kopię, ustaw `PCMED_ORIGIN` i `HTTPS_PORT` w `.env`, a także adresy klienta Keycloak, konfigurację panelu i bramek, DNS/certyfikaty i zapory. Import realm nie aktualizuje istniejącego realm automatycznie. To nie jest automatyczny migrator starej instalacji.

CI sprawdza kod, reguły i uruchomienie stosu Compose. Utworzenie VM na rzeczywistym Proxmox, routing VPN, certyfikaty, wykrywanie w docelowym LAN i test jednej końcówki pozostają obowiązkowymi krokami odbioru. Nie wykonano ich na Twojej infrastrukturze.
