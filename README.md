# Martin 2.0

Osobní AI asistent pro Windows 11 s českým rozhraním, hlasem a vizí.
Běží lokálně na Ollama, hovoří česky (Piper), umí přečíst obrazovku
a spravovat počítač - ale nikdy bez tvého vědomí a vždy pod bezpečnostní
politikou, kterou vynucuje kód, ne model.

Opravy stability a jejich skutečné ověření popisuje
[český protokol opravy](docs/OPRAVA_STABILITY_2026-10-21.md).
Hlášený okamžitý pád při zapnutí mikrofonu se zatím nepodařilo
spolehlivě zopakovat; původní příčina není potvrzena.

---

## Obsah

- [Co Martin umí](#co-martin-umí)
- [Instalace](#instalace)
- [Spuštění](#spuštění)
- [Ovládání](#ovládání)
- [Bezpečnost](#bezpečnost)
- [Hardwarové profily](#hardwarové-profily)
- [Vývoj](#vývoj)
- [Testy](#testy)
- [Sestavení exe](#sestavení-exe)
- [Omezení](#omezení)
- [Struktura projektu](#struktura-projektu)

---

## Co Martin umí

### Rozhraní
- Tmavý i světlý motiv, plynulé animace (přechody, pulzující indikátory)
- Chat, historie konverzací, správa paměti, přehled bezpečnostních událostí
- Systémová tray ikona, plovoucí okno pro rychlé dotazy
- Přehled hardwaru v reálném čase (CPU, RAM, VRAM, teplota, baterie)
- Celé rozhraní je v češtině

### Umělá inteligence
- Lokální inference přes Ollama (`qwen3.5:4b` - vidí, má nástroje, myslí)
- **Tool calling** - model si vybírá z 15 registrovaných nástrojů
- Streamované odpovědi (text se zobrazuje během generování)
- Automatické routování: jednoduché dotazy lokálně, složité do cloudu
- Cloudový záložní model `nemotron-3-nano:30b-cloud`
- **Local Only režim** - nic nikdy neodejde z počítače
- Režim přemýšlení lze vypnout (výchozí = rychlé odpovědi)

### Hlas
- **Piper TTS** - české hlasy Jirka a Kasandra, 100 % offline
- Předčítání zkráceného souhrnu místo celé dlouhé odpovědi
- Přerušitelné přehrávání, volitelné zvukové zařízení a rychlost
- Mikrofon zapneš tlačítkem nebo Ctrl+Shift+mezerník; dalším stiskem dokončíš nahrávku
- **Silero VAD** ve whisper.cpp pro filtrování ticha před přepisem
- Příkazy pro přerušení mluvení ("zastav", "ticho", "stop")

### Zrak
- Snímek obrazovky nebo konkrétního okna **až na výslovný požadavek**
- Podporuje více monitorů
- Analýza probíhá lokálně modelem s vizuálním schopnostmi
- Obsah snímku je pokládán za nedůvěryhodná data (ochrana proti prompt injection)

### Windows
- Spuštění aplikací a her (objevuje je v registru, Start menu a Steamu)
- Otevření složky, prohlížeče, stránky Nastavení Windows
- Zaměření existujícího okna, výpis otevřených oken
- Ovládání hlasitosti systému
- Čtení systémových statistik (CPU, RAM, disk, baterie, GPU)

### Paměť
- Dlouhodobá paměť v SQLite s fulltextovým vyhledáváním (FTS5)
- Ukládá preference, projekty, nastavení, důležité informace
- Do kontextu se nikdy nenačítá celá databáze - jen relevantní záznamy
- Vyhledávání, úpravy, mazání, export a import do JSON

---

## Instalace

### Požadavky
- Windows 11 x64
- [Ollama](https://ollama.com) - musí běžet na `http://127.0.0.1:11434`
- Python 3.12+ (jen pro vývoj ze zdroje)

### Ze ZIP archivu
1. Rozbal `Martin-2.0-win64.zip` kamkoli
2. Zkontroluj, že existuje `Martin/models/piper/` (české hlasy) a
   `Martin/models/vad/` (Silero)
3. Dvojklik na `Martin.exe` nebo `Spustit_Martin.bat`

### Ze zdroje
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[speech,dev]"
python run_martin.py
```

### Modely
```bash
ollama pull qwen3.5:4b
```

---

## Spuštění

```bash
# ze zdroje
python run_martin.py

# z balíčku
build_output\Martin\Martin.exe
```

Martin při startu ověří připojení k Ollama. Pokud Ollama nebeží, okno
se otevře, ale chat nebude fungovat - napiš to do pole a uvidíš chybu.

---

## Ovládání

| Akce | Klávesa |
|---|---|
| Odeslat zprávu | `Enter` |
| Nový řádek | `Shift + Enter` |
| Plovoucí okno | `Ctrl + Shift + M` |
| Poslouchat (push-to-talk) | `Ctrl + Shift + Space` |
| Focus do vstupu | `Ctrl + Shift + L` |
| Přepnout motiv | `Ctrl + Shift + T` |
| Zastavit mluvení | `Ctrl + Shift + C` |

Příklady, které Martin zvládne:

- *"Martine, otevři MSFS 2024."* - najde hru přes Steam a spustí ji
- *"Co je na obrazovce?"* - vyfotí obrazovku a popíše ji
- *"Jak mám nastavit hlasitost na 40?"* - provede změnu po potvrzení
- *"Zapamatuj si, že preferuji tmavý motiv."* - uloží do dlouhodobé paměti
- *"Přepni na herní profil."* - uvolní VRAM

---

## Bezpečnost

**Zásadní pravidlo: bezpečnost vynucuje kód aplikace, nikoli model.**
Model může jen *navrhnout* akci. Rozhodnutí vždy přijímá
`PolicyEngine` podle pevně dané úrovně nástroje, allowlistu a validace
argumentů.

| Úroveň | Význam | Příklady |
|---|---|---|
| `SAFE` | Jen čtení a spuštění schválených aplikací | `open_app`, `list_apps`, `system_stats`, `list_windows` |
| `CONFIRM` | Změna uživatelských dat - vyžaduje potvrzení | `set_volume`, `remember`, `set_power_profile` |
| `BLOCK` | Vždy zablokováno | destruktivní operace, eskalace práv, obejití zabezpečení |

Co Martin **neumí** a nikdy nebude umět:
- Spouštět libovolné příkazy v shellu (neexistuje žádný `run_command` nástroj)
- Mazat soubory rekurzivně
- Pracovat s hesly, přihlašovacími údaji či privátními klíči
- Obcházet zásady zabezpečení

Další ochrany:
- Cesty na souborech se kontrolují proti allowlistu (jen Plocha, Dokumenty,
  Stažené soubory, Obrázky, Videa, Hudba)
- URL se přijímají pouze `http://` a `https://`
- Stránky Nastavení Windows se otevírají výhradně z pevné mapy
- Zakázané interpreti (`cmd.exe`, `powershell.exe`, `wscript.exe`, ...) se nespustí
- Obsah snímku obrazovky se v promptu označuje jako nedůvěryhodná data
- Audit log zaznamenává každé rozhodnutí; hesla a tokeny se v něm
  **nikdy** neukládají (automaticky se maskují)
- Cloudový model dostává přesně stejné nástroje a podléhá stejným kontrolám

---

## Hardwarové profily

| Profil | Chování |
|---|---|
| `PERFORMANCE` | Plné GPU inference, minimální latence, model zůstává v paměti |
| `GAMING` | Model se odpojí od GPU (`keep_alive: 0`), VRAM se uvolní pro hry |
| `SMART` | Automaticky volí podle vytížení GPU/CPU a složitosti úlohy |

Přepnutí profilu lze i hlasem: *"Přepni na herní profil."* (vyžaduje potvrzení).

Uvolnění VRAM se **ověřuje** přes Ollama API - Martin nikdy netvrdí, že
paměť uvolnil, aniž by to opravdu ověřil.

---

## Vývoj

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[speech,build,dev]"

python run_martin.py       # spustit
pytest                    # testy
pyflakes martin            # statická kontrola
```

---

## Testy

```bash
pytest -q                       # vše
pytest tests/unit -q            # jen unit testy
pytest tests/integration -q     # proti běžícímu Ollama
pytest tests/adversarial -q     # bezpečnostní testy
```

Integranční testy se přeskočí, pokud Ollama není dostupná.
Adversariální testy ověřují, že bezpečnostní omezení drží i při
podvrženém vstupu.

---

## Sestavení exe

```bash
python -m PyInstaller --noconfirm --clean martin.spec
python packaging\make_installer.py
```

Výsledek:
- `build_output\Martin\Martin.exe` - spustitelná aplikace
- `build_output\Martin-2.0-win64.zip` - distribuce s modely a README

---

## Naměřené výkony

Měřeno na tomto počítači (i7-14700HX, RTX 5070 Laptop, 32 GB RAM).
Teplé modely = modely již načtené v paměti.

### Hlasový vstup a výstup

| Krok | Doba | Jak se měřilo |
|---|---|---|
| Aktivace mikrofonu | **1,0 ms** | návrat z `toggle_listening()` |
| Zastavení nahrávání | **0,6 ms** | návrat z `toggle_listening()` |
| Otevření zvukového zařízení | 0,27 s | reálné zařízení, mimo GUI vlákno |
| Rozpoznání (model `small`, 4 s zvuku) | 3,9 s | whisper.cpp + VAD |
| Rozpoznání (model `base`, 4 s zvuku) | 1,1 s | whisper.cpp + VAD |
| Syntéza hlasu (in-proces) | **0,61 s** | pro 0,62 s audia (1,0x real-time) |
| Syntéza hlasu (podproces, před opravou) | 11,7 s | pro 0,62 s audia (0,05x) |
| Načtení Piper hlasu (warm-up) | 5,6 - 9,6 s | jednou, v pozadí |
| Načtení modelu whisper.cpp | 0,2 - 3,0 s | jednou, v pozadí |

### Kompletní cyklus odpovědi (teplé modely)

| Krok | Doba |
|---|---|
| První token LLM | **0,28 - 0,42 s** |
| Začátek mluvení (streamovací TTS) | **2,23 s** |
| Začátek mluvení bez warm-upu | 12,69 s |

### Responzivita GUI

| Scénář | Největší pauza v GUI |
|---|---|
| Aktivace mikrofonu | 0,0 ms |
| Během nahrávání | 0,0 ms |
| Během rozpoznávání řeči | **11,2 ms** |

Před opravou se GUI zastavilo na desítky sekund až minuty při aktivaci
STT a při syntéze hlasu v zabalené aplikaci.

---

## Omezení

Přehled věcí, které **nejsou** hotové nebo byly ověřeny jen částečně:

- **Rozpoznávání řeči (STT)** - běží přes **whisper.cpp** (`pywhispercpp`),
  ne přes faster-whisper. Důvod: zásada zabezpečení Windows (WDAC,
  Policy ID `0283ac0f`) blokuje nativní knihovnu `av/logging.pyd`, kterou
  faster-whisper potřebuje. whisper.cpp používá vlastní knihovnu, která
  zásadou dotčena není. Podporuje GPU (CUDA) i CPU.
- **Slyšitelnost přehrávání** - Piper syntetizuje správně (ověřeno) a
  zvuk se přehrává, ale v prostředí, ve kterém testy běžely, nebylo možné
  výstup **slyšet**. Overeno je, že syntéza vrátí správné PCM audio
  (22050 Hz, int16) a přehrávání ho bez chyby spotřebuje.
- **Vlastní hlas uživatele** - nahrávání z reálného mikrofonu bylo ověřeno
  (zařízení se otevře, signál se zachycuje), ale v testovacím prostředí
  nikdo nevystupoval do mikrofonu. Rozpoznání vlastní řeči tedy nebylo
  provedeno. Ověřeno bylo rozpoznání reálného zvuku syntetizovaného Piperem
  a odmítnutí reálného šumu z mikrofonu.
- **Volba zvukového zařízení** - seznam zařízení se načte, ale uložené
  nastavení se v UI ještě nepropisuje do konkrétního zařízení.
- **Připnutí okna do systémové tray** - ikona funguje, ale chybí
  kontextové menu s nabídkou skrýt okno doprava.
- **Bez kódu pro instalaci** - distribuce je ZIP, ne MSI/EXE instalátor
  s průvodcem.
- **Synchronizace konverzací** - historie je lokální, bez synchronizace
  mezi zařízeními.
- **Funkční testy UI** - rozhraní je ověřeno spuštěním a snímkem obrazovky,
  ale ne má automatizované testy kliknutí. Chybí testy pro přepínání
  stránek a práci s pamětí přes UI.

---

## Struktura projektu

```
martin/
  app_context.py      centrální stav a signály aplikace
  paths.py            cesty, rozlišení vývoje a balíčku
  core/               nastavení, logování
  llm/                Ollama klient, routování, orchestrátor
  speech/             Piper TTS, faster-whisper STT, Silero VAD
  vision/             snímání obrazovky, vizuální analýza
  memory/             SQLite paměť, historie konverzací
  tools/              15 nástrojů dostupných modelu
  security/           policy engine, audit, redakce
  hardware/           monitoring, profily výkonu
  system/             objev aplikací, okna, hlasitost, statistiky
  ui/                 PySide6 okna, motivy, animované widgety
tests/
  unit/               izolované testy
  integration/        testy proti běžícímu Ollama
  adversarial/        bezpečnostní testy
packaging/            specifikace PyInstaller, instalátor
```

---

## Licence

MIT
