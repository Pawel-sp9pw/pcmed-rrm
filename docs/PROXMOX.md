# Proxmox: automatyczna instalacja PC MED w LXC

## 1. Jedno polecenie na hoście Proxmox

Jako **root w konsoli hosta Proxmox VE** uruchom:

~~~sh
curl -fsSL https://raw.githubusercontent.com/Pawel-sp9pw/pcmed-rrm/codex/rmm-mvp/deploy/proxmox/install-lxc.sh -o /root/pcmed-install-lxc.sh && bash /root/pcmed-install-lxc.sh
~~~

To jest jedna pełna instalacja, nie instrukcja wykonania drugiego etapu w kontenerze. **Nie trzeba ręcznie tworzyć LXC, instalować zależności, generować certyfikatów ani uruchamiać usług.** Nie trzeba też wcześniej klonować repozytorium.

Skrypt pobiera kod z gałęzi `codex/rmm-mvp`, dopóki [PR #1](https://github.com/Pawel-sp9pw/pcmed-rrm/pull/1) nie jest scalony. Uruchamia kod jako root, więc używaj wyłącznie zaufanego repozytorium; [kod instalatora](../deploy/proxmox/install-lxc.sh) jest dostępny do przeglądu. Poprzednia nazwa `create-vm.sh` jest tylko przekierowaniem do tego samego instalatora LXC.

## 2. O co zapyta instalator

- Numer nowego kontenera (domyślnie wolny CTID z klastra), CPU/RAM/dysk: domyślnie **4 CPU / 8192 MB / 40 GB**.
- **Adres centrali z faktycznym prefiksem**, np. `172.20.0.8/24`, brama i DNS. Adres centrali to **172.20.0.8**, ale prefiks i brama muszą odpowiadać Twojej sieci — nie zostały podane i skrypt ich nie zgaduje.
- Most sieciowy Proxmox, np. `vmbr0`, storage dysku LXC, np. `local-lvm`, oraz storage szablonów, np. `local`.
- Dozwolone sieci źródłowe VPN i zarządzania. Uwzględnij również sieć/adres hosta Proxmox, z którego instalator sprawdza gotowość panelu. Nigdy `0.0.0.0/0`.
- Nazwę kontenera i pierwszego operatora (domyślnie `pcmed-admin`), port HTTPS (domyślnie **38443**) i port listy unieważnień certyfikatów CRL (domyślnie **38445**).
- TLS: `auto` generuje własny CA i certyfikat; `import` pyta o lokalne pliki PEM certyfikatu, klucza i zaufanego CA na hoście, a potem sam kopiuje je do kontenera. Certyfikat importowany musi mieć **SAN IP:172.20.0.8** i pełny łańcuch.

Po podsumowaniu wpisz `INSTALUJ`. Dalej instalator pracuje bez pytań i bez ręcznego wchodzenia do kontenera. Potrzebny jest aktualny, obsługiwany Proxmox/LXC, wolny adres i dostęp do repozytoriów podczas instalacji. Ewentualna zapora Proxmox lub routera musi przepuszczać wybrane porty z dozwolonych sieci.

## 3. Co zrobi sam

1. Sprawdzi parametry, dostępność CTID w klastrze, most i typy storage; nie nadpisuje istniejącego kontenera ani plików poprzedniej instalacji.
2. Utworzy **nieuprzywilejowany LXC Debian 13** z nesting/keyctl przez przypięty [Docker LXC Community Scripts](https://github.com/community-scripts/ProxmoxVE/blob/4a742048372462aa93b2e1246603604876c8f9c8/ct/docker.sh) w trybie bezobsługowym. Nie wystawia gniazda Docker TCP ani nie wyłącza AppArmor.
3. Sprawdzi znacznik tożsamości, adres i nieuprzywilejowany tryb faktycznie utworzonego CT. Odmówi instalowania aplikacji w innym kontenerze.
4. Przez `pct exec` zainstaluje wymagane pakiety. Przeniesie do CT dokładnie ten sam commit aplikacji przez lokalny Git bundle, bez drugiego pobierania innej wersji kodu.
5. Wygeneruje/importuje TLS, losowe hasła baz i Keycloak, pierwsze konto operatora z obowiązkową zmianą hasła oraz konfigurację panelu, API i PostgreSQL.
6. Skonfiguruje zaporę `DOCKER-USER` wyłącznie dla wybranego prywatnego adresu i portów, uruchomi migracje, zbuduje i uruchomi stos Compose jako `pcmed-stack.service`.
7. Włączy autostart kontenera oraz usługi. W trybie automatycznego CA włączy także codzienne odnawianie CRL.
8. Sprawdzi stan systemd oraz **HTTPS z weryfikacją CA, panel, issuer OIDC, klucze RS256 i odrzucenie niezalogowanego API**. Sprawdzenie wykona w CT i z hosta Proxmox; sprawdzi również dostępność i podpis CRL.

**`GOTOWE` pojawia się dopiero po poprawnym przejściu kontroli.** Błąd któregokolwiek etapu kończy instalator kodem niezerowym, zamiast udawać uruchomienie usługi.

Nie wymagamy uprzywilejowanego LXC, `unconfined`, wyłączenia seccomp ani globalnej zmiany polityki AppArmor. Jeśli Docker nie może działać w nesting na danej wersji hosta, instalacja zatrzyma się z diagnostyką — nie obniży automatycznie izolacji.

## 4. Wynik i pierwsze logowanie

Dla przykładowego CTID `120`:

| Element | Wynik |
| --- | --- |
| Panel | `https://172.20.0.8:38443` |
| Konto i pierwsze hasło | na hoście: `/root/pcmed-lxc-120-first-login.json`, tylko root |
| Publiczny CA dla operatorów/bramek | na hoście: `/root/pcmed-lxc-120-ca.crt` |
| Stan instalacji i hasło konsoli CT | na hoście: `/root/pcmed-lxc-120-install.json`, tylko root |
| Chroniony log | na hoście: `/var/log/pcmed-lxc-120-pcmed-install-….log` |
| Aplikacja | w CT: `/opt/pcmed-rmm` |
| Usługa i sekrety | w CT: `pcmed-stack.service`, `/etc/pcmed` i `/opt/pcmed-rmm/.env` |

Instalator podaje rzeczywiste ścieżki na końcu, nie wypisuje haseł na ekran. Zaimportuj **publiczny** CA do zaufanego magazynu przeglądarki i `LocalMachine\\Root` bramek Windows. Nie rozprowadzaj klucza CA ani plików z hasłami. Po pierwszym logowaniu zmień hasło i utwórz klientów oraz imienne konta; MFA pozostaje opcjonalne. Pierwszy operator aplikacji i administrator konsoli Keycloak to osobne konta.

Automatyczny CA ma ważność 10 lat, certyfikat serwera 397 dni. Zaplanuj jego wymianę przed wygaśnięciem i aktualizację ewentualnych pinów; ten instalator nie wykonuje automatycznej rotacji pinowanych certyfikatów. Klucz CA pozostaje w CT w `/etc/pcmed/pki/issued`, dostępnym tylko dla root — uwzględnij go w zaszyfrowanej kopii.

CRL to **podpisane dane publiczne**, a nie panel czy API. Tryb `auto` publikuje wyłącznie `/ca.crl` przez HTTP na TCP 38445, tylko na adresie centrali i dla tych samych dozwolonych sieci. Pozostałe ścieżki zwracają 404, a metody zapisu są zabronione. CRL ma ważność 7 dni i jest odnawiana codziennie przez `pcmed-crl.timer`; serwer WWW nie dostaje klucza CA. Dzięki temu Windows zachowuje włączone sprawdzanie unieważnienia certyfikatów. Nie blokuj tego portu na trasie bramki–centrala. W trybie `import` port CRL nie jest publikowany; dostępność CRL/OCSP zapewnia wystawca Twojego certyfikatu.

Bramki klientów nadal korzystają z lokalnego HTTPS TCP **38444**, a końcówki nie mają portów przychodzących. Instalacja i wykrywanie bramki: [WDROZENIE.md](WDROZENIE.md#5-instalacja-serwera-pośredniczącego-u-klienta). Porty są konfigurowalne; ich numer nie jest zabezpieczeniem.

## 5. W pełni bezobsługowe uruchomienie

Można przekazać parametry zamiast odpowiadać na pytania. Poniższe wartości sieciowe to **przykład**, zastąp je rzeczywistymi:

~~~sh
bash /root/pcmed-install-lxc.sh --ctid 120 --address-cidr 172.20.0.8/24 --gateway 172.20.0.1 --dns '172.20.0.1 1.1.1.1' --bridge vmbr0 --storage local-lvm --template-storage local --allow-cidr 172.20.0.0/24 --allow-cidr 10.44.0.0/24 --yes
~~~

`--yes` przyjmuje domyślne zasoby/TLS/konto i nie otwiera pytań; brak wymaganej wartości kończy się błędem przed tworzeniem CT. Dla importu dodaj `--tls-mode import --tls-cert /root/centrala.crt --tls-key /root/centrala.key --trusted-ca /root/firmowe-ca.crt`. Pełna lista: `python3 deploy/proxmox/lxc.py --help` w pobranym repozytorium.

## 6. Błędy, kopie i granice weryfikacji

Przerwana instalacja **nie usuwa kontenera ani danych**. Zachowaj log i prywatny plik stanu; nie uruchamiaj w ciemno ponownego tworzenia z tym samym CTID. Najpierw ustal etap i przyczynę. Istniejące instalacje nie są automatycznie migrowane ani resetowane.

Kopie powinny objąć oba PostgreSQL (aplikacja i Keycloak), `.env`, `secrets/`, `/etc/pcmed` oraz prywatne pliki instalacyjne na hoście. Szyfruj kopie i sprawdź odtworzenie; backup samego kontenera nie zastępuje testu odtwarzania baz.

Przypięte Community Scripts: ProxmoxVE `4a742048372462aa93b2e1246603604876c8f9c8`, core `a14f2d451d1b358673b5f89e170f66bd6631e249`; główny skrypt Docker LXC jest dodatkowo weryfikowany SHA-256. Obrazy OS i repozytoria pakietów nadal pochodzą z upstream, nie jest to instalacja offline ani w pełni odtwarzalny łańcuch dostaw. PC MED nie jest oficjalną pozycją w katalogu Community Scripts.

Testy automatyczne obejmują symulowany pełny przebieg poleceń Proxmox, błędy i ochronę istniejących kontenerów, generowanie TLS/CRL, rzeczywiste sprawdzanie unieważnienia w Windows oraz start całego stosu Compose z HTTPS/OIDC. **Nie wykonano rzeczywistego utworzenia LXC na Twoim Proxmox** — do tego nadal potrzebny jest dostęp do hosta. Nie deklarujemy wdrożenia produkcyjnego bez takiej weryfikacji.
