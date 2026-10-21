# Martin 2.1 Cloud Edition — návrh a rozhodnutí

Základ: opravená verze 71e9df5, samostatná větev codex/martin-2.1-cloud.
Stávající data a distribuce 2.0 zůstávají zachovány. Rozhraní se rozšiřuje,
nepřestavuje. Výchozí text: nemotron-3-nano:30b-cloud; obraz: gemma4:cloud;
volitelný lokální model: qwen3.5:4b. Cloudové inference byly přes místní
Ollama 0.40.7 a současné přihlášení ověřeny 2026-10-21.

## Závazné chování

- Cloud i Automatic začínají cloudem. Automatic nikdy automaticky nenačte
  lokální model. Offline je výslovná volba uživatele. Migrace zachová dřívější
  výslovné Local Only; ostatní stará nastavení přejdou do Cloud.
- Bez síťového klasifikátoru. Textový model zpracuje i požadavek na nástroj;
  obraz vzniká teprve po jednorázovém potvrzení s konkrétním oknem a cílovým
  modelem. Snímek nemá oprávnění měnit bezpečnostní politiku.
- Chyba, prázdný stream, nedokončený stream a Stop musí ukončit chatový cyklus
  a obnovit vstup. Žádná automatická opakovaná placená inference ani změna modelu.
- Každá HTTP inference má vlastní ID, celkový deadline a přerušitelnou async
  síťovou úlohu. Žádné prompty, obrázky, audio nebo klíče v měřicím protokolu.
- Samostatná SQLite evidence spotřeby ukládá pouze metadata. Tokeny jsou
  skutečné API hodnoty; chybějící metadata a náklady přerušeného požadavku
  zůstávají neznámé. Ceny jsou nastavitelný datovaný odhad, účetní zůstatek
  ukazuje pouze oficiální web účtu. Lokální limity jsou předběžné ochranné
  kontroly, nikoli garance přesného účtu poskytovatele.
- STT a Piper se načítají až při použití. Izolace whisper.cpp zůstává.
  Monitoring má pomalý interval a herní režim detekuje proces MSFS bez zásahů
  do hry. Odpojit lze pouze model prokazatelně nově načtený Martinem.
- Soukromí: cloudový text obsahuje omezenou historii a volitelnou relevantní
  paměť; nikdy automatické dokumenty, celou databázi nebo autentizační soubory.

## Ověření a hranice

Před/po: stejný samostatný AppContext, 15 s klidu po startu, součet RSS a CPU
vlastního procesu a potomků, samostatně systémová GPU a Ollama /api/ps.
Živý cloud, Qt zprávy, Stop před hlavičkami i během streamu, chybové scénáře,
regresní sada, skutečné zařízení, kontrolované okno, čerstvý EXE a ZIP.
Syntetická česká řeč neprokazuje rozpoznání lidské řeči uživatele. Nelze
předstírat skutečně vyčerpaný účet nebo odpojený internet: tyto chyby se
ověří řízeným HTTP serverem a budou tak označeny.

## Ověřené zdroje (2026-10-21)

- https://docs.ollama.com/cloud — přihlášení a cloud přes místní Ollama.
- https://docs.ollama.com/api/usage — tokeny v posledním stream chunku.
- https://ollama.com/pricing — Nemotron vstup 0.06 / výstup 0.24 USD za 1M;
  Gemma vstup 0.14 / cache 0.05 / výstup 0.40 USD za 1M tokenů.
  Skutečná fakturace a kredit nejsou z těchto čísel odvozovány.
