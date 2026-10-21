# Martin 2.0: oprava stability, 21. 10. 2026

## Co lze tvrdit

Původní uživatelský pád ihned po zapnutí mikrofonu nebyl při ovládání
původního EXE ani původního ZIP spolehlivě reprodukován. Jeho přesná příčina
zůstává **NEOVĚŘENÁ**. Historický Windows protokol obsahoval nativní pády
zdrojového Pythonu v knihovnách Whisper a PortAudio; toto není důkaz, že
stejnou příčinu měl uživatelem hlášený pád EXE.

Oprava řeší samostatně prokázané závady a přidává diagnostiku pro další výskyt.
PortAudio zůstává v procesu GUI; izolace dekodéru nemůže zabránit všem pádům
zvukového ovladače. Zabezpečení Windows nebylo měněno.

## Opravené závady

- Otevření a zavření mikrofonu vlastní stejné pracovní vlákno. Zrušení během
  pozdního otevření zařízení již nenechá zařízení otevřené. Callback nesoutěží
  se zastavením ovladače o stejný zámek. Zvuk se převádí na 16 kHz.
- Whisper běží v samostatném procesu s autentizovaným loopback protokolem,
  pevnými operacemi, limitem dat, timeoutem a obnovením po pádu. Model a VAD
  musí být dostupné; při chybě se požadavek nevykoná.
- Výjimky Pythonu, vláken a Qt se logují. Nativní stopy zapisuje faulthandler
  do souborů fault-PID.log. STT proces má vlastní log, aby nesoutěžil o rotaci.
- Přepis se předává do Qt pomocí queued signal/slot. QThread správně vlastní
  chatový worker; zavírání čeká na jeho dokončení. Síťové požadavky mají timeout.
- Odpověď asistenta má vlastní bublinu. Duplicitní odesílání při generování
  je blokováno, Enter odešle a Shift+Enter vloží nový řádek.
- Český systémový prompt se soustředí na poslední dotaz, nepřidává opakované
  pozdravy a neslibuje neprovedené akce. Nedochází k libovolnému mazání odpovědí
  modelu. Do kontextu se nepřidávají nesouvisející poslední vzpomínky.
- TTS zpracovává celé věty, zachovává mezery mezi tokeny, odstraňuje Markdown
  před syntézou, neodhazuje věty při naplnění fronty a po konci vstupu skončí.
  Přerušení zastavuje i streamované předčítání. Syntézy jsou serializované.
- Ollama posílá obrázky ke zprávě uživatele, schopnosti modelu čte přes /api/show.
  Poškozený nebo předčasně ukončený stream hlásí chybu. Profil posílá num_gpu
  a keep_alive do požadavků; odpojení modelu se ověřuje přes /api/ps.
- Validátor open_app dostává správné argumenty. Složky se validují a otevírají
  stejným převodem cesty. Konečný cíl nesmí být blokovaný interpret ani skript.
  Potvrzení citlivé akce platí jen pro konkrétní volání.
  Snímek obrazovky vyžaduje vlastní potvrzení uživatele; o pořízení nemůže
  rozhodnout sám model. Odkazy aplikací mají omezená URL schémata.
- Win32 enumerace má správný callback a 64bitové typy. Snímek okna kontroluje
  výsledek PrintWindow/GetDIBits a uvolňuje GDI objekty. Virtuální plocha není
  chybně označena jako hlavní monitor. Obrazové instrukce mají systémové varování.
- Ovládání hlasitosti získává COM rozhraní ve vlákně volajícího. Mute nastavuje
  požadovaný stav místo bezpodmínečného přepnutí.
- Build používá omezený PATH. Při prvním diagnostickém sestavení byl prokázán
  konflikt cizích CRT DLL z hostitelského prostředí, který znemožňoval import QtCore.
  Toto byla chyba diagnostického buildu, nikoli potvrzená příčina původního pádu.
- Skutečné zabalené EXE skončilo při první syntéze hlasu kódem 1 bez Python
  výjimky. Chyběla data piper/espeak-ng-data; stejný nativní exit(1) byl
  reprodukován v samostatném procesu. Spec nyní tato data zahrnuje a TTS
  kontroluje nezbytné soubory dříve, než zavolá nativní fonemizér. I původní
  lokální balíček tato data postrádal. Není doloženo, že to vyvolávalo
  uživatelův okamžitý pád mikrofonu, protože k selhání dochází až při syntéze.

## Opakovatelné příkazy (PowerShell v kořeni projektu)

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pyflakes martin packaging
.\.venv\Scripts\python.exe packaging\build_windows.py --out build_output\repaired-release
$env:MARTIN_DATA_DIR = "$PWD\build_output\audit\vlastni-novy-test"
& .\build_output\repaired-release\Martin\Martin.exe --diagnose-voice "$PWD\build_output\audit\vlastni-report.json" 12
.\.venv\Scripts\python.exe packaging\make_installer.py --build-dir build_output\repaired-release --out build_output\Martin-2.0-repaired-win64.zip
```

Pro normální spuštění odstraň testovací MARTIN_DATA_DIR z aktuálního terminálu
a spusť `build_output\repaired-release\Martin\Martin.exe`. Data běžné instalace jsou
v `%LOCALAPPDATA%\Martin`; diagnostika má používat vlastní nový adresář.
Build i ZIP odmítají přepsání existujícího cíle. ZIP se rozbaluje celý,
včetně `_internal` a `models`. Build-manifest.json obsahuje commit a SHA-256 souborů.

Ctrl+Q aplikaci ukončí včetně úklidu. Křížek standardně schová okno do tray.
Pro záznam zásobníků při zamrznutí nastav před spuštěním `MARTIN_TRACE_HANGS=1`.
Nativní logy mohou obsahovat cesty a rozpoznaný text; před sdílením je zkontroluj.

Diagnostický režim skutečně otevře mikrofon a přehraje dvě testovací věty.
Nahrávku z mikrofonu neukládá ani nepředává modelu či nástrojům. Český přepis
ověřuje odděleně na syntetickém hlasu Piper. Lokálnímu Ollama předává jen pevný
aritmetický dotaz. Ukončení vlastního dekodéru je řízená injekce chyby.

## Dosavadní měření a hranice důkazů

Původní sada: **254 testů prošlo**. Finální rozšířená sada: **270 testů prošlo za
54,05 s, 1 test byl přeskočen**, včetně skutečného Ollama/STT a snímku vlastního
testovacího Qt okna. Přeskočený test vyžaduje cestu k EXE a spouští se zvlášť:

```powershell
$env:MARTIN_TEST_PACKAGED_EXE = "$PWD\build_output\repaired-release\Martin\Martin.exe"
.\.venv\Scripts\python.exe -m pytest tests\integration\test_packaged_voice.py -q
```

Pyflakes prošel bez nálezů. Část testů používá řízené náhrady ovladačů; výsledek
sady sám o sobě není důkazem funkčnosti celé distribuce.

Zdrojová diagnostika na skutečném zařízení: 12 záznamů s nenulovými vzorky,
24 rychlých zrušení, neplatné zařízení, ticho, syntetický šum, přepis syntetické
češtiny, skutečné přehrání, obnova dekodéru a zavření při otevírání mikrofonu:
vše prošlo. Aktivace mikrofonu 0,054–0,282 s, přepis 4,064s syntetické věty
4,330 s, první streamovaný zvuk 0,265 s, největší mezera heartbeat Qt 0,045 s.
Ollama odpověděl „Dva plus dva je čtyři.“ za 7,47 s. Jde o jednotlivá měření.

Dřívější syntetická aritmetická věta byla rozpoznána chybně („Kolejk“).
Použitý model tedy není bezchybný. Přesnost skutečného lidského hlasu, vnímání
kvality hlasu, odpojení fyzického mikrofonu během nahrávání, různé ovladače,
více fyzických monitorů, skutečné spuštění MSFS/Steamu, cloudový failover a
fyzické uvolnění VRAM nejsou tímto protokolem potvrzené. Automatická politika
není úplnou ochranou proti všem prompt injection; autorizace nástrojů zůstává
samostatně v aplikačním kódu. Souvislost opravených závad s původním pádem
musí potvrdit další reprodukce nebo lokální uživatelský test.

## Další hranice auditu

Automatické rozhodnutí SMART podle tlaku na VRAM není úplně propojeno s
chatovou cestou; směrování dnes rozhoduje hlavně podle složitosti dotazu.
Přepnutí profilu nástrojem také není plně synchronizované s uloženým profilem
GUI. Pro nastavení profilu používej stránku Nastavení; skutečný přesun modelu
mezi CPU/GPU ani fyzické uvolnění VRAM v tomto průchodu nebyly potvrzeny.
Tento protokol tedy není potvrzením úplného dokončení všech požadavků auditu.

## Distribuce a GUI

Finální aplikační kód sestavený z commitu `db81584` prošel samostatným testem
EXE (56,70 s). Kontrola porovnávala SHA-256 všech souborů z manifestu,
obsah modelů a data eSpeak, skutečný mikrofon, STT, TTS, lokální Ollama i úklid.
Stejný test čerstvě rozbaleného finálního ZIP také prošel (45,68 s).
Každý běh ověřil 12 nahrávek a 24 rychlých zrušení; žádná kontrola neselhala.
Podrobná měření jsou v přiloženém závěrečném protokolu a JSON.

GUI bylo ovládáno přes Windows UI Automation: zapnutí i vypnutí mikrofonu
tlačítkem a Ctrl+Shift+mezerník, odmítnutí nahrávky bez řeči, dva navazující
české dotazy („Dva plus dva je čtyři.“ a „Třikrát tři je devět.“), oddělené
bubliny a ukončení Ctrl+Q. Proces GUI i jeho STT proces po ukončení zmizely.
Po vizuální kontrole se opravily počáteční modelové/hlasové popisky,
stav panelu po přehrávání a zobrazení českých diagnostických údajů; regresi
pokrývá skutečný Qt test. Poslední EXE bylo navíc spuštěno s chybějícím modelem
Whisper/VAD: zůstalo funkční a zobrazilo českou chybu, potom se normálně zavřelo.

Nejde o dlouhodobý zátěžový test ani ověření všech zařízení a všech ovladačů.
