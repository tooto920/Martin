# Martin 2.1 Cloud Edition — protokol opravy a ověření

Práce a měření: 21.–22. 10. 2026. Projekt: `C:\Users\lukas\Downloads\Martin`.

**Výsledek: cloudová zdrojová aplikace je implementovaná a skutečně testovaná. Nový EXE byl sestaven, ale místní Windows jej blokuje před spuštěním. Kompletní akceptace vydání tedy NENÍ splněná.**

## Nalezené příčiny a opravy

| Problém | Zjištěná příčina a výsledná změna |
|---|---|
| Cloudový asistent neodpovídal spolehlivě | Původní automatické směrování používalo lokální model pro krátké dotazy. Cloud/Automatic nyní přímo volí požadovaný Nemotron, bez lokální klasifikace nebo automatického fallbacku. |
| Další dotaz mohl zmizet po dokončení odpovědi | UI se přepnulo na Připraven dřív než skončil worker. Dokončení se oznamuje až po úklidu; rozepsaný vstup při obsazení zůstává zachován. |
| Stop nerušil generování | Ovládání zastavovalo především řeč. Nyní ruší orchestrátor, aktivní HTTP úlohu, TTS a vstup; funguje i před hlavičkami/1. tokenem a před startem workeru. |
| Chyby byly nejasné nebo přepsané stavem Připraven | Samostatné chyby připojení, timeoutu, autentizace, kreditu, limitu a modelu, včetně ID a doby požadavku. Prázdný či neúplný stream je chyba. |
| Vysoká klidová RAM | Starý start přednačítal Whisper/Piper. Nově se načítají až při použití; STT se po cloudovém hlasovém vstupu ukončí. |
| Zůstávající potomci STT | Python ve venv je na Windows také launcher s potomkem. Úklid sleduje a ukončuje výhradně vlastní procesový strom. |
| Neprovedený snímek po textové žádosti | Skutečný Nemotron někdy nástroj vůbec nezavolal. Tlačítko oka nyní přímo spouští schválený nástroj a Gemmu, při zachování nezávislého potvrzení. |
| Nastavení vypnuté cloudové paměti šlo obejít nástrojem | Adaptér paměti kontroluje přístup i při modelovém tool callu; vypnutá cloudová paměť se nečte. |
| Výběr zařízení a změna profilu se nepromítaly spolehlivě | Opravené ukládání indexu/názvu zařízení, propojení profilu a asynchronní diagnostická tlačítka. |

Původně hlášený pád 2.0 ihned při zapnutí mikrofonu nemá potvrzenou jedinou příčinu. Dříve doložená chybějící data Piper/eSpeak byla jiná chyba při inicializaci TTS. Nové testy nesmějí být vydávány za zpětný důkaz původního pádu.

## Implementovaná verze

- Výchozí text `nemotron-3-nano:30b-cloud`; obraz `gemma4:cloud`; `qwen3.5:4b` pouze po výslovné volbě Offline. Cloud nestahuje ani nenačítá jeho váhy.
- Streamované odpovědi, rušení, celkový časový limit, historie s omezením délky, české stavy a metadata požadavků. Po chybě se automaticky neposílá druhý placený požadavek. 429 má interval 2–60 s; další pokus je ruční.
- Lazy Whisper/Piper, oddělený STT proces, omezená fronta řeči a délka hlasové odpovědi. Profil Gaming zpomaluje monitoring, pro Offline volí CPU a po odpovědi uvolňuje hlas.
- Diagnostika modelu, spojení, mikrofonu, hlasu, uvolnění modelů, Stop a opakování dotazu; panel RMS, přepisu, poslední chyby a časů.
- Cloud Usage: skutečná API metadata tokenů, místní odhad ceny, editovatelné datované sazby a místní denní/měsíční limity. Zůstatek účtu je výslovně neznámý.
- Paměť pro cloud výchozím stavem vypnutá. Snímek pouze konkrétního okna, jednorázově po potvrzení s názvem modelu. Rozpoznané tajné údaje v textovém cloudovém payloadu se maskují; nejde o záruku rozpoznání všech citlivých údajů.
- Staré nastavení se migruje se zálohou `settings.pre-2.1.json`; výslovné Local Only zůstává Offline. Staré databáze a 2.0 build nebyly nahrazeny. Stávající vzhled byl zachován.

Sdílená Ollama neumožňuje dokázat výhradní vlastnictví modelu napříč jinými aplikacemi. Uvolňování je omezené na model pozorovaný před Martinovým vlastním požadavkem jako nenačtený; již běžící cizí model se neodpojuje.

## Co bylo skutečně provedeno

| Zkouška | Výsledek a hranice |
|---|---|
| Celá sada ze zdrojů | **290 passed, 1 skipped, 33.84 s.** Přeskočený test byl opt-in hardware test EXE, nikoli úspěšný EXE test. |
| Statická kontrola | Ruff F a `git diff --check` prošly. |
| Živá cloudová sada přes Qt | 7 pokusů, kontext historie, skutečné zrušení aktivního požadavku a úspěšný další dotaz. Bez zbylých HTTP úloh, maximální mezera Qt 0,032 s. Ollama `/api/ps` před i po prázdné. |
| Aktuální GUI — text | Skutečný klik Odeslat: Nemotron odpověděl „Čtyři.“, stav Připraven; ID `d25029db6615`, TTFT 0,392 s, API celkem 0,557 s. |
| Aktuální GUI — obraz | Uživatel klikl Povolit; skutečná Gemma přečetla 7319, červený čtverec a nadpis. ID `c03cd838559e`, TTFT 0,448 s, API 1,143 s. Potom Připraven. Původní starý dialog vypršel a nic neodeslal; nový test prošel. |
| Obrazová komponenta | Jiný skutečný snímek vlastního testovacího okna: správný kód 9486 a červený obdélník; API 0,561 s. |
| Skutečný Realtek mikrofon | Nejnovější sada: **12 aktivací/záznamů + 24 rychlých rušení**, invalid-device a obnovení decoderu; všech 22 kontrol prošlo, errors prázdné. Aktuální source GUI také zaznamenalo listening true/false bez okamžitého pádu. |
| STT → cloud → Piper | Syntetická česká řeč přes skutečný Whisper, Qt, Nemotron a skutečný výstup Realtek. Přepis „Ahoj Martin, jak se dnes máš.“; žádný záznam uživatelovy řeči nebyl vydáván za ověřený. |
| Ukončení | Zdrojové diagnostiky skončily, GUI se ukončilo přes Ctrl+Q a jeho pythonw procesy zmizely. Skutečný Stop přes cloud veřejným API a Qt kliknutí na tlačítko byly testovány odděleně; ruční Sky klik na Stop během živého cloudu zůstal neověřený, protože odpověď skončila příliš rychle. |
| Výpadky | Skutečný neodpovídající místní endpoint vyústil v zachycený timeout, bez workeru. Výpadek internetu byl simulován transportem. HTTP 401/403/402/429/404/503, timeout, neplatný stream a obnova jsou řízené testy; přihlášení účtu ani síť Windows se záměrně nevypínaly. Chybějící STT a eSpeak data se testují fixtures před nativním voláním. |
| Nový EXE | **FAIL/BLOCKED:** explicitně spuštěný packaged hardware pytest skončil `WinError 4551` před vytvořením procesu. 1 failed v 12,40 s. Žádný nový packaged hlas/cloud test neprošel. |
| ZIP | CRC, skutečné rozbalení, SHA-256 všech **675** souborů a **56** aktuálních zdrojů souhlasí s manifestem. Databáze, soukromá data ani Qwen váhy nejsou v archivu. Extrahovaný EXE se neopakovaným přesunem nepoužíval k obcházení stejné zásady. |

Pět až sedm chatů a opakované hlasové operace jsou omezený test stability, nikoli několikahodinový či několikadenní soak test. Nezaručují absenci všech úniků paměti.

## Naměřený výkon

Stejný source AppContext harness, čekání na start/warmup, 15 s klid, agregace vlastního procesu a potomků. Jde o jádro aplikace bez celého hlavního okna, nikoli přímé srovnání dvou EXE. Zátěž dalších aplikací nebyla řízena.

| Metrika | 2.0 před | 2.1 po |
|---|---:|---:|
| Klidová RAM jádra + potomci | 824,10 MB | 92,01 MB |
| Klidové CPU, procenta jednoho logického jádra | 0,2 % | 0,0 % v tomto krátkém vzorku |
| Potomci | 3 | 0 |
| Vlákna | 51 | 31 |

Pokles RAM **88,8 %**. Údaj 0,0 % není slib nulové spotřeby. Současné plné source GUI mělo při pozorování asi 168–176 MB; je to jiná měřicí cesta.

Starý skutečný 2.0 EXE ve stejném externím GUI harnessu: po 25 s warmup a 15 s klidu 893,34 MB, CPU 0,83 % jednoho jádra. Nový EXE nelze porovnat, protože jej blokuje Windows. Úklid tohoto měření ukončil jen jeho vlastní procesový strom; není důkazem řádného ukončení GUI.

V raném source srovnání již Qwen před testem zabíral **3 364 911 840 B VRAM** a zůstal načtený — jeho původ není přičítán 2.1. Pozdější cloudová sada měla před i po žádné lokální modely v Ollamě. Systémová VRAM zahrnuje i další aplikace a z těchto měření nelze poctivě vyčíslit celkovou GPU úsporu Martina. 28 logických CPU, RTX 5070 Laptop 8151 MB VRAM, 31,71 GB RAM. Běh MSFS a dopad na FPS **UNVERIFIED**.

Nejnovější hlasová cesta se syntetickou vstupní větou: STT **3,798 s**, cloud TTFT **0,346 s**, cloud **0,475 s**, syntéza **0,114 s**, zahájení přehrávání **0,440 s** od začátku práce streameru; celý cyklus **9,261 s** včetně celé odpovědi a jejího přehrání. Starší obdobný test byl 21,091 s; délka odpovědi, síť a zahřátí se liší, proto to není přímý důkaz další optimalizace. Největší mezera Qt poslední hlasové sady 0,062 s.

### České STT: skutečné měření pěti syntetických vět na model

| Model | Průměr rozpoznání | Raw WER | Maximum RSS workeru a jeho potomků | CPU jednoho jádra / celého PC s 28 CPU |
|---|---:|---:|---:|---:|
| tiny | 0.447 s | 63.3 % | 225.1 MB | 384 % / 13.7 % |
| base | 0.958 s | 43.3 % | 317.7 MB | 385 % / 13.8 % |
| small | 3.470 s | 26.7 % | 712.4 MB | 393 % / 14.0 % |

Raw WER nerozlišuje ekvivalentní číselné zápisy typu „30 %“ a „třicet procent“, takže není čistým sémantickým skóre. Vzorek je malý a syntetický. Small zůstal výchozí kvůli lepšímu přepisu; tiny/base jsou dostupné pro vědomou volbu rychlosti.

Samostatný Piper benchmark 5 vět: první studená syntéza 4.246 s, z toho načtení 3.955 s; další průměr 0.165 s na cca 5,2 s audia. Zahřátá syntéza spotřebovala v průměru 1933 % jednoho jádra, tj. 69.0 % z 28 logických CPU, ve velmi krátkém úseku. RSS samostatného TTS procesu přibližně 247–254 MB. TTS používá více CPU vláken a krátké špičky zůstávají; skutečný souběh s hrou není změřený.

## Kvalita a cena cloudu

Oba přesné názvy modelů skutečně odpovídaly přes existující přihlášení lokální Ollamy 0.40.7. Ve 12 srovnávacích dotazech (6/model) se lišila kvalita češtiny a rady k VRAM nebyly vždy dobré. V jiném skutečném GUI testu Nemotron na 7 × 8 odpověděl chybně „Čtyřicet dva.“ a neprovedl nástroj. Požadovaný default byl zachován; uživatel může textový model změnit na Gemmu. Ani Gemma není záruka pravdivosti.

Agregace jedinečných ID z uložených živých testů a izolovaných ledgerů:

- **31 pokusů:** 23 Nemotron, 8 Gemma; 18278 známých vstupních a 1232 výstupních tokenů, cached 1920.
- Známá část místního odhadu **0.00157988 USD**; **1 zrušený požadavek s neznámou cenou** není započten jako nula. Dva úvodní přímé probe požadavky nejsou v této agregaci, nejde tedy o celkovou fakturu ani kompletní spotřebu účtu.
- Medián zachyceného TTFT: Nemotron 0,577 s; Gemma 0,359 s. Modely nedostávaly totožné všechny požadavky, nejde o kontrolovaný velký benchmark.
- Použité sazby ověřené **2026-10-21**: Nemotron vstup/výstup 0,06/0,24 USD za milion; Gemma 0,14/0,40, cached vstup 0,05. Zdroj: [oficiální ceník](https://ollama.com/pricing); [API usage metadata](https://docs.ollama.com/api/usage).
- Skutečný zůstatek a účtovaná částka **UNKNOWN**. Účet se ověřuje na [oficiální stránce spotřeby](https://ollama.com/settings/usage). Žádný kredit nebyl nakoupen.

## Build, Git a distribuce

- Větev `codex/martin-2.1-cloud`, předchozí 2.0 základ `71e9df5041a3d90c56f70c9cff1c261f752e3b26`.
- **Zdrojový commit EXE: `283be3368fd2e12a47613e4e31ba7b7bc780955e`.** Následné dokumentační commity nemění zdroje uvnitř EXE. Odeslání větve `codex/martin-2.1-cloud` bylo ověřeno proti vzdálenému repozitáři; doprovodné soubory s měřeními jsou v lokální předané složce outputs.
- EXE `C:\Users\lukas\Downloads\Martin\build_output\cloud-release\Martin\Martin.exe` — sestaven, zde **BLOCKED**, nikoli runtime ověřen.
- ZIP `Martin-2.1-Cloud-win64.zip`, **895970959 B**, SHA-256 `ee0114651605745258a59ca3566238e3dbf79eab0680d6337178e3ccc1a7a010`.
- Původní `build_output\repaired-release` i dřívější 2.0 ZIP jsou zachované. Manifest obsahuje identitu zdrojů a kontrolní součty distribuovaných souborů.
- Archiv obsahuje tiny/base/small, VAD a Piper; neobsahuje lokální váhy Qwen. Přiložený český README také upozorňuje na aktuální blokaci EXE.

Windows pro nový nepodepsaný EXE zaznamenal Code Integrity **3077**, zásadu **VerifiedAndReputableDesktop**, status **0xc0e90002**, `WinError 4551`. To je potvrzená blokace před procesem, ne prokázaný pád Martina. Uživatel potvrdil, že nemá důvěryhodný podpisový certifikát ani schválený postup. Bezpečnostní zásady nebyly vypínány ani měněny. Microsoft popisuje požadavek reputace/důvěryhodného podepsání v [dokumentaci Smart App Control](https://learn.microsoft.com/windows/apps/develop/smart-app-control/overview). Průchod nového EXE na tomto PC vyžaduje schválené řešení podepsání; další komponenty by po něm stále vyžadovaly skutečný packaged test.

Zdrojová cesta je funkční v existujícím prostředí: v projektové složce spustit `.venv\Scripts\pythonw.exe run_martin.py`. Tato cesta byla otestována a nenahrazuje ověření EXE.

## Zbývající hranice

**BLOCKED:** skutečný start/cloud/hlas/čisté ukončení nového EXE a jeho extrahované ZIP kopie. **UNVERIFIED:** lidská česká řeč uživatele, Niceboy jako funkční zařízení, skutečně běžící MSFS/FPS, hodinový soak test a přesná celosystémová úspora GPU. Niceboy byl vypsán jako WDM-KS zařízení, ale reálné otevření vracelo Invalid device (-9996); testy byly dle odpovědi uživatele dokončeny na Realteku. Kvalita odpovědí modelů zůstává omezená.

Úloha má reálnou implementaci, cloudový GUI test včetně uživatelského souhlasu a doložený hlasový test ze zdrojů. Kvůli blokovanému EXE ji nelze označit za kompletně úspěšné vydání pro tento počítač.

Surové kontrolované testy, build manifest a měření jsou ve složce `Martin-2.1-evidence`. Nejsou přiložené soukromé databáze, audionahrávky ani snímky uživatelovy plochy.
