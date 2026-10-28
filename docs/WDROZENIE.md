# Wdrożenie PC MED: centrala, bramka i komputery klientów

**Proxmox:** rozpocznij od [PROXMOX.md](PROXMOX.md) — jeden skrypt tworzy LXC przez Community Scripts i wykonuje pełną instalację centrali, HTTPS, konta i autostartu, z końcowym sprawdzeniem usługi. Nie musisz wchodzić do kontenera. Sekcja 3 poniżej opisuje wyłącznie alternatywny, ręczny start Compose; nie powtarzaj jej po instalacji automatycznej.

Pierwsze konto utworzone automatycznie: dane na hoście Proxmox w `/root/pcmed-lxc-CTID-first-login.json` (tylko root). Pierwsze logowanie wymaga zmiany hasła. Publiczny CA jest w `/root/pcmed-lxc-CTID-ca.crt`; rozprowadź go do zaufanych magazynów operatorów i bramek, nigdy jego klucz prywatny. Przy automatycznym CA bramki muszą także mieć dostęp przez VPN do TCP 38445, udostępniającego wyłącznie podpisaną listę CRL. MFA nadal jest opcjonalne.

## 1. Co pobrać i gdzie są pliki EXE

Kod jest w gałęzi **codex/rmm-mvp**, w [PR #1](https://github.com/Pawel-sp9pw/pcmed-rrm/pull/1). Dopóki PR nie zostanie scalony, domyślna gałąź `main` nie zawiera MVP. Do instalacji Windows nie trzeba kompilować źródeł.

Na GitHub otwórz **Actions → Verify MVP → najnowszy zakończony przebieg dla codex/rmm-mvp → Artifacts → windows-mvp**. Pobranie artefaktu wymaga zalogowania do GitHuba. Rozpakuj cały ZIP do `C:\PcMed`. Nie uruchamiaj instalacji wewnątrz ZIP i nie przenoś samych EXE bez pozostałych plików.

| Element | Plik po rozpakowaniu | Gdzie instalować |
| --- | --- | --- |
| Klient / agent | `Agent\PcMed.Agent.exe` | Każdy zarządzany komputer Windows |
| Serwer pośredniczący / bramka | `Gateway\PcMed.Gateway.exe` | Jeden komputer Windows u klienta, mający VPN do centrali |
| Okna komunikatów | `Agent\Notifier\PcMed.Notifier.exe` | Komputery z agentem; start przy logowaniu użytkownika |
| Instalacja klienta | `Install-Agent.ps1` | Uruchom z PowerShell 7 jako administrator |
| Instalacja bramki | `Install-Gateway.ps1` | Uruchom z PowerShell 7 jako administrator |

EXE agenta i bramki są programami usług Windows, a nie graficznymi instalatorami. Skrypty instalacyjne konfigurują je i rejestrują usługi. Wersja MVP wymaga zainstalowanych bibliotek .NET 10; nie jest samodzielnym instalatorem typu Setup.exe.

Alternatywnie pobierz artefakt **windows-install-zip**, zawierający `pcmed-windows-mvp.zip` i jego plik `.sha256`. Rozpakuj artefakt, sprawdź hash ZIP przez `Get-FileHash -Algorithm SHA256`, porównaj z `.sha256`, a następnie rozpakuj właściwy ZIP do pustego katalogu `C:\PcMed`. Nie dopisuj plików do katalogu paczki przed instalacją — manifest celowo odrzuca pliki spoza dystrybucji. Sekrety i certyfikaty trzymaj w osobnym katalogu.

**Centrala nie ma pliku EXE.** Zgodnie z architekturą FastAPI/PostgreSQL działa na serwerze Linux przez Docker Compose. Jej instalację opisuje następna sekcja.

## 2. Przygotuj adresy

Przykładowa sieć używana w tej instrukcji:

| Ustawienie | Przykład — zastąp własną wartością |
| --- | --- |
| Adres centrali | `172.20.0.8`, URL `https://172.20.0.8:38443` |
| Adres VPN centrali | `172.20.0.8` |
| Nazwa bramki w LAN klienta | `gateway.firma.lan` |
| Adres LAN bramki | `192.168.20.10` |
| Podsieć klienta | `192.168.20.0/24` |
| Port centrali | TCP 38443, dostępny przez VPN |
| Port bramki | TCP 38444, dostępny z LAN klienta |

Operator i bramka muszą rozwiązywać nazwę centrali i mieć do niej dostęp przez VPN. Stacje robocze muszą rozwiązywać nazwę bramki i mieć do niej dostęp po LAN. Stacje nie potrzebują własnego VPN ani internetu do pobierania zadań i instalatorów z bramki.

## 3. Instalacja centrali na Linux

Potrzebne są Git, Python 3.12+, Docker Engine i Docker Compose v2. Dla Ubuntu użyj [oficjalnej instrukcji instalacji Docker Engine](https://docs.docker.com/engine/install/ubuntu/). Polecenia poniżej wykonuj jako administrator wdrożenia mający dostęp do Dockera.

Ręczny start wymaga poprawnej zapory dla portu publikowanego przez Docker; samo UFW może nie wystarczyć. Wariant Proxmox automatyzuje to w [PROXMOX.md](PROXMOX.md).

### 3.1. Pobierz właściwą gałąź

```sh
git clone --branch codex/rmm-mvp --single-branch https://github.com/Pawel-sp9pw/pcmed-rrm.git
cd pcmed-rrm
python3 --version
docker compose version
```

### 3.2. Wygeneruj konfigurację

Użyj adresu rzeczywiście przypisanego do interfejsu VPN serwera. Konfigurator odrzuca `0.0.0.0` i adresy publiczne.

```sh
python3 scripts/configure.py \
  --hostname 172.20.0.8 \
  --vpn-bind 172.20.0.8 \
  --artifact-host 172.20.0.8
```

Powstaną `.env` z losowymi hasłami oraz folder `secrets`. Nie uruchamiaj konfiguratora ponownie na istniejącej instalacji. Nie publikuj tych plików na GitHubie.

### 3.3. Przygotuj DNS i certyfikat centrali

Dla centrali `172.20.0.8` przygotuj certyfikat serwerowy z **SAN IP:172.20.0.8**, wystawiony przez firmowe, zaufane CA:

- pełny łańcuch certyfikatu PEM: `secrets/tls.crt`;
- klucz prywatny PEM bez hasła: `secrets/tls.key`.

```sh
chmod 700 secrets
chmod 600 .env secrets/tls.key
```

Jeśli korzystasz z własnego CA, jego publiczny certyfikat musi być zaufany przez przeglądarkę operatora i komputery Windows. Klucz prywatny CA pozostaje u administratora CA. Nie zastępuj zaufania certyfikatowi wyłączeniem weryfikacji HTTPS. Nazw z końcówką `.lan` nie zweryfikuje publiczne CA — dla nich potrzebujesz firmowego CA albo własnej domeny i odpowiednich certyfikatów.

### 3.4. Uruchom centralę

```sh
docker compose config --quiet
docker compose up --build -d
docker compose ps -a
docker compose logs --tail 100 migrate api keycloak
```

Oczekiwany wynik: `migrate` zakończony kodem 0, `api` w stanie healthy, `web` i `keycloak` uruchomione, w logu Keycloak zaimportowany realm `pcmed`. Otwórz `https://172.20.0.8:38443/` w przeglądarce przez VPN. Zapora serwera powinna dopuszczać TCP 38443 wyłącznie z właściwej sieci VPN/zarządzania.

### 3.5. Utwórz konta i pierwszego klienta

1. Lokalnie na serwerze odczytaj hasło `KEYCLOAK_ADMIN_PASSWORD` z `.env`. Nie przesyłaj całego pliku `.env` w zgłoszeniach.
2. Otwórz `https://172.20.0.8:38443/admin/`. Zaloguj się jako `bootstrap-admin`.
3. Wybierz realm **pcmed**. Utwórz imienne konto operatora, ustaw mu hasło i przypisz rolę realm `platform_admin`. Konto bootstrap służy tylko administracji Keycloak, nie logowaniu do panelu PC MED.
4. Zaloguj się nowym kontem na `https://172.20.0.8:38443/`. Dodaj klienta, np. „Firma Kowalski”.
5. Dla zwykłych operatorów utwórz w Keycloak grupę, której nazwą jest pełny identyfikator klienta ze stopki panelu. Dodaj do grupy użytkowników z rolą `operator`, `approver` albo `viewer`. `platform_admin` ma dostęp do wszystkich klientów.
6. Do zatwierdzania instalatorów/skryptów przygotuj drugie imienne konto z rolą `approver`, przypisane do tego samego klienta.
7. W konsoli Keycloak przejdź do realm **master**, utwórz własne imienne konto administracyjne i przypisz mu rolę realm `admin`. Sprawdź logowanie tym kontem do konsoli administracyjnej w osobnej sesji, a dopiero potem usuń `bootstrap-admin`. Konto z rolą `platform_admin` w realm `pcmed` i administrator Keycloak to dwa różne poziomy dostępu.

MFA jest opcjonalne. Nie trzeba konfigurować OTP, aby się zalogować. Wybrane konto może włączyć je w konsoli konta Keycloak.

## 4. Wymagania Windows

Komputery muszą mieć wspierany Windows x64 oraz:

- PowerShell 7.2 lub nowszy do uruchomienia skryptu instalacji;
- agent i moduł komunikatów: **.NET 10 Desktop Runtime x64**, zawierający podstawowy runtime .NET;
- bramka: **ASP.NET Core Runtime 10 x64** oraz podstawowy .NET Runtime 10, który jest jego zależnością.

Pobieraj aktualne poprawki z [oficjalnej strony .NET 10](https://dotnet.microsoft.com/en-us/download/dotnet/10.0) i [oficjalnej instrukcji PowerShell](https://learn.microsoft.com/en-us/powershell/scripting/install/installing-powershell-on-windows). SDK i Visual Studio nie są potrzebne na końcówkach. Instalatory wymaganych runtime można wcześniej skopiować do sieci klienta, jeśli końcówki nie mają internetu.

Uruchom **PowerShell 7 jako administrator**, przejdź do rozpakowanej paczki:

```powershell
cd C:\PcMed
pwsh --version
dotnet --list-runtimes
```

Paczka zawiera `manifest.json`: instalator sprawdza odciski wszystkich plików, odrzuca dodatkowe pliki i dowiązania. Pobieraj paczkę tylko z zaufanego Actions i sprawdzaj jej zewnętrzny SHA-256. Manifest wykrywa uszkodzenia, ale sam nie uwierzytelnia autora; MVP nie ma podpisu Authenticode.

Jeżeli obowiązują firmowe wymagania podpisywania skryptów, zastosuj je także do plików instalacyjnych. Nie wyłączaj globalnie polityki wykonania skryptów.

## 5. Instalacja serwera pośredniczącego u klienta

### 5.1. VPN, DNS i certyfikaty

1. Na wybranym komputerze uruchom VPN do centrali. Sprawdź, że `https://172.20.0.8:38443/` otwiera się bez błędu certyfikatu.
2. Nadaj bramce stały adres LAN, np. `192.168.20.10`. W lokalnym DNS ustaw `gateway.firma.lan → 192.168.20.10`.
3. Przygotuj PFX z certyfikatem serwera z **SAN IP:192.168.20.10** oraz opcjonalnie DNS `gateway.firma.lan`, pełnym łańcuchem oraz kluczem prywatnym. W magazynie `LocalMachine\My` musi znajdować się certyfikat z kluczem dostępnym dla LocalSystem. Certyfikat musi mieć EKU serverAuth. Instalator wybiera go po konkretnym thumbprint i sprawdza ważność, zaufanie, klucz prywatny oraz SAN IP.
4. Jeśli używasz własnego CA, zainstaluj publiczny certyfikat CA w magazynie zaufanych głównych urzędów **komputera lokalnego** bramki i każdej stacji roboczej. W domenie można rozesłać go przez GPO.

Przykład importu, z własnymi ścieżkami:

```powershell
Import-Certificate -FilePath C:\Certyfikaty\firmowe-ca.cer -CertStoreLocation Cert:\LocalMachine\Root
$pfxPassword = Read-Host 'Hasło PFX bramki' -AsSecureString
$cert = Import-PfxCertificate -FilePath C:\Certyfikaty\gateway.firma.lan.pfx -CertStoreLocation Cert:\LocalMachine\My -Password $pfxPassword | Where-Object HasPrivateKey
```

Pliku PFX z kluczem bramki nie kopiuj na stacje robocze — one potrzebują tylko publicznego certyfikatu CA.

Aby sprawdzić uprawnienia do klucza, uruchom `certlm.msc`, otwórz **Osobisty → Certyfikaty**, kliknij certyfikat bramki prawym przyciskiem i wybierz **Wszystkie zadania → Zarządzaj kluczami prywatnymi**. Konto `SYSTEM` powinno mieć odczyt. Właściwości certyfikatu powinny potwierdzać posiadanie odpowiadającego mu klucza prywatnego.

### 5.2. Token i instalacja

W panelu PC MED wybierz klienta → **Bramki LAN → Dodaj bramkę**. Zachowaj pokazany token; nie jest później dostępny do odczytu.

W PowerShell 7 jako administrator, z katalogu paczki:

```powershell
./Install-Gateway.ps1 `
  -CentralUrl https://172.20.0.8:38443 `
  -LanDnsName gateway.firma.lan `
  -LanSubnet 192.168.20.0/24 `
  -LanAddress 192.168.20.10 `
  -CertificateThumbprint $cert.Thumbprint `
  -ArtifactHosts 172.20.0.8
```

Podaj token bramki w ukrytym monicie. Powstanie usługa `PcMedGateway` i reguła zapory TCP 38444, ograniczona do podanej podsieci oraz profilu Domain/Private. Program jest instalowany w `C:\Program Files\PcMed\Gateway`.

```powershell
Get-Service PcMedGateway
```

Oczekiwany stan: **Running**. Przekaż administratorowi stacji publiczny odcisk certyfikatu (nie klucz prywatny):

```powershell
$gatewaySha256 = $cert.GetCertHashString([Security.Cryptography.HashAlgorithmName]::SHA256)
$gatewaySha256
```

Ten odcisk SHA-256 należy przekazać niezależnym zaufanym kanałem. Thumbprint użyty do wyboru certyfikatu w magazynie to zwykle SHA-1 — nie należy ich mylić.

 Sam wpis bramki w panelu oznacza utworzenie danych dostępu, a nie dowód działania usługi. Łączność potwierdzi rejestracja agenta przez tę bramkę.

## 6. Instalacja klienta na każdym komputerze

1. Sprawdź zaufanie do CA. Otrzymaj od administratora **SHA-256 certyfikatu bramki** przez zaufany kanał i przypisz go do `$gatewaySha256` (64 znaki). Nie jest to thumbprint SHA-1, token ani hash pliku EXE.
2. W panelu wybierz właściwego klienta → **Komputery → Zarejestruj komputer**. Wygeneruj osobny token dla tej końcówki; ważny jest przez 15 minut i tylko do jednej rejestracji.
3. Rozpakuj paczkę na końcówce. W PowerShell 7 jako administrator:

```powershell
cd C:\PcMed
./Install-Agent.ps1 -GatewayCertificateSha256 $gatewaySha256
```

4. Instalator wyszuka bramkę po HTTPS w lokalnym LAN i sprawdzi CA, SAN IP, ważność oraz oczekiwany SHA-256 certyfikatu. Przy jednym wyniku potwierdź adresem `TAK`, a następnie podaj jednorazowy token w ukrytym monicie. Przy dużej/wielokrotnej podsieci dodaj `-ScanCidr 192.168.20.0/24`. Możesz wskazać ręcznie `-GatewayUrl https://192.168.20.10:38444`; odcisk nadal jest wymagany.
5. Sprawdź usługę:

```powershell
Get-Service PcMedAgent
```

6. W panelu odśwież listę komputerów. Końcówka powinna pojawić się jako Online, z połączeniem „Bramka LAN”.
7. Wyloguj i zaloguj użytkownika Windows, aby uruchomił się moduł komunikatów. W już otwartej sesji można uruchomić go ręcznie jako zwykły użytkownik:

```powershell
& 'C:\Program Files\PcMed\Agent\Notifier\PcMed.Notifier.exe'
```

Każdy komputer wymaga własnej instalacji i własnego tokenu. Na komputerze będącym bramką również można zainstalować agenta, jeżeli ma być zarządzany. Nie otwieraj portów przychodzących na końcówkach.

## 7. Pierwszy test po instalacji

1. Wyślij krótki komunikat do jednej końcówki z aktywnym modułem Notifier. Sprawdź okno Windows i wynik w Zadaniach.
2. Dodaj prosty skrypt diagnostyczny do Biblioteki. Drugie konto przegląda treść i zatwierdza definicję; autor nie może zatwierdzić własnego kodu.
3. Zleć go na jednej testowej końcówce. Sprawdź kod wyjścia i wynik przed próbą masowego wykonania.
4. Aby przetestować instalator, skopiuj sprawdzony MSI/EXE na centralę do `secrets/packages/`. Użyj adresu `https://172.20.0.8:38443/packages/nazwa.msi` i SHA-256 oryginalnego pliku. Bramka oraz centrala muszą dopuszczać ten host.
5. Sprawdź zachowanie po utracie VPN i jego przywróceniu. Bramka potrzebuje centrali do autoryzacji; nie wykonuje zadań offline.

## 8. Gdy coś nie działa

| Objaw | Co sprawdzić |
| --- | --- |
| Na GitHubie widać tylko `.gitignore` | Wybierz gałąź `codex/rmm-mvp`, a nie `main`; PR nie jest jeszcze scalony |
| Nie ma EXE w „Download ZIP” kodu | Źródła i programy to osobne paczki; pobierz artefakt **windows-mvp** z Actions |
| Dwuklik EXE otwiera okno i je zamyka | To program usługi; zainstaluj go odpowiednim skryptem, sprawdź runtime i konfigurację |
| Agent/bramka zgłasza brak .NET | Zainstaluj odpowiedni runtime .NET 10 x64 wskazany w sekcji 4 |
| Błąd HTTPS | Sprawdź nazwę DNS, SAN, ważność i łańcuch certyfikatu oraz CA w `LocalMachine\Root` |
| Rejestracja zwraca 401 | Token wygasł/został już użyty albo token bramki został odwołany; wygeneruj właściwy nowy token |
| Rejestracja zwraca 403 | Bramka i token rejestracji muszą należeć do tego samego klienta |
| Komputer Offline | Sprawdź `PcMedAgent`, bramkę, VPN i port 38444; online wynika z heartbeat w ostatnich 90 s |
| Komunikat nie pojawia się | Użytkownik musi być zalogowany i mieć uruchomiony `PcMed.Notifier.exe` |
| Zadanie „Do weryfikacji” | Sprawdź skutki na końcówce; nie zakładaj, że można bezpiecznie wykonać je ponownie |

Konfiguracja programów: `C:\Program Files\PcMed\Agent\appsettings.json` oraz `C:\Program Files\PcMed\Gateway\appsettings.json`. Sekrety i dziennik: `C:\ProgramData\PcMed`. Logi usług sprawdzaj w Podglądzie zdarzeń Windows. Dla centrali użyj `docker compose logs --tail 100 api keycloak web`.

Instalator celowo odmawia nadpisania istniejącej usługi. Aktualizację wykonuj po zatrzymaniu usługi i zachowaniu katalogu ProgramData; instrukcje bezpieczeństwa, kopii zapasowych i ograniczenia MVP znajdują się w głównym README. Testy CI potwierdzają kod i start Compose, ale nie zastępują pilotażu na rzeczywistym VPN/LAN i końcówkach klienta.
