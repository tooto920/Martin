# Martin 2.1 Cloud Edition

Český asistent pro Windows 11. Text zpracovává `nemotron-3-nano:30b-cloud`,
obraz `gemma4:cloud`. Whisper a Piper pracují místně. Model `qwen3.5:4b`
je volitelný pouze pro výslovně zvolený režim Offline.

## Spuštění

1. Rozbal celý ZIP. Spusť `Martin/Martin.exe` nebo `Spustit_Martin.bat`.
2. Musí běžet [Ollama](https://ollama.com) na `http://127.0.0.1:11434`.
   Pro cloud použij své přihlášení v oficiální aplikaci Ollama. Martin
   neukládá klíče ani nekupuje kredity. Cloudové váhy se nestahují do PC.
3. V Nastavení zkontroluj režim **Cloud** a názvy modelů. Tlačítko
   **Test cloud spojení** provede jednu skutečnou inferenci, která může
   spotřebovat kredit. Potom napiš do chatu „Ahoj“.

Nový EXE vzniká v `build_output/cloud-release/Martin/Martin.exe`.
Distribuce 2.0 zůstává samostatně v `build_output/repaired-release`.
EXE nevyžaduje systémový Python. Ze zdroje použij Python 3.12+,
`pip install -e ".[speech,dev]"` a `python run_martin.py`.

## Režimy a hlas

- **Cloud / Automatic:** cloud je první volba; neprobíhá lokální klasifikace
  ani automatický fallback do Qwenu. Chyba nevyvolá další placený požadavek.
- **Offline:** text a případný obraz používají zvolený lokální model. Ten
  musí být předem dostupný v Ollamě. Jeho instalace je dobrovolná:
  `ollama pull qwen3.5:4b`. V ZIPu nejsou jeho váhy.
- Mikrofon: tlačítko **Mikrofon** nebo `Ctrl+Shift+Space`; druhý stisk ukončí
  nahrávání a odešle přepis. Tichá nahrávka se neposílá. Nejvýše 60 sekund.
- **Stop** nebo `Ctrl+Shift+C` zruší generování, hlas a hlasový vstup.
  Načítání nativní syntézy nemusí skončit okamžitě; síťový požadavek je
  přerušitelný i před prvním tokenem. Nový dotaz se přijme po úklidu workeru.
- Whisper **small** zůstává výchozí: v českém syntetickém srovnání byl
  přesnější než tiny/base. Všechny tři varianty jsou přiložené. Menší model
  zvol vědomě, pokud upřednostňuješ rychlost před přesností.
- Modely řeči se nenačítají při startu. Izolovaný STT proces se v Cloud
  režimu po rozpoznání ukončí. První hlas má navíc dobu načtení Piperu.
- Diagnostika zobrazuje mikrofon, RMS vstupu, přepis, STT, cloudové TTFT,
  syntézu, přehrávání a poslední chybu. Žádný záznam mikrofonu se standardně
  neukládá. Syntéza používá dočasné WAV soubory a po přehrání je odstraňuje.

Okno zavřené křížkem zůstává v tray. `Ctrl+Q` aplikaci úplně ukončí.
Enter odešle zprávu, Shift+Enter vloží nový řádek.

## Snímky a soukromí

V Nastavení zadej název konkrétního okna a povol cloudové snímky. Tlačítko
oka v chatu vyvolá jednorázové potvrzení s názvem okna i cílového modelu.
Teprve po schválení se pořídí snímek a odešle do Gemmy. Celá plocha se
automaticky neposílá. V Offline režimu se použije místní vizuální model.
Snímek je nedůvěryhodný podklad a nemůže schválit další nástroj.

Cloud dostává textový požadavek a posledních nejvýše osm zpráv, každou
omezenou na 6000 znaků. Relevantní dlouhodobá paměť je pro cloud výchozím
nastavením vypnutá a po povolení je omezená na 4000 znaků. Dokumenty,
přihlašovací soubory ani celá databáze se automaticky neodesílají.
Zprávy jsou uloženy v místní historii. Do historie ani promptu nevkládej
údaje, které nechceš zvolenému poskytovateli poslat.

## Cloud Usage a rozpočty

Panel **Model Management / Cloud Usage** ukazuje skutečné počty tokenů
vrácené API a místní odhad nákladů pro den a měsíc v UTC. Sazby jsou
editovatelný JSON: `[vstup, výstup, cached vstup]` v USD za milion tokenů.
Výchozí sazby byly ověřeny 2026-10-21 na [oficiálním ceníku](https://ollama.com/pricing).
Odhad není faktura a neříká, kolik kreditu zbývá na účtu. To ověř na
[oficiální stránce spotřeby](https://ollama.com/settings/usage).

Nula u rozpočtu nebo limitu znamená vypnuto. Denní požadavky, tokeny a
odhadovaný denní/měsíční rozpočet se kontrolují před novým požadavkem.
Přerušený požadavek může být účtován i bez finálních tokenových metadat;
jeho cena zůstává označená jako neznámá a rezervace se konzervativně
započítává do limitu. U obrazu s peněžním limitem se žádost odmítne,
protože nelze spolehlivě předem odhadnout obrazové tokeny. Rozpočet je
místní ochrana; neomezuje jiné aplikace ani negarantuje fakturu Ollamy.

Při omezení 429 se použije čekací interval 2–60 sekund a další pokus
vyžaduje tvou akci. Žádné automatické opakování nebo dražší změny modelu.
Chyby přihlášení, kreditu, chybějícího modelu, výpadku a časového limitu
jsou viditelné. Test hlasu a mikrofonu nic neposílá do cloudu.

## Výkon a hranice

Monitor rozlišuje systémové GPU/RAM a RAM Martina s jeho potomky.
Systémovou VRAM nelze přičítat pouze Martinovi. Herní režim pozná běžící
proces MSFS a zpomalí monitoring z 10 na 20 sekund; cloud již běží bez
lokálního LLM. V Offline herním profilu používá LLM CPU. Tlačítko uvolnění
pracuje pouze s lokálním modelem, který byl před Martinovým vlastním
požadavkem pozorován jako nenačtený. Již běžící cizí model neodpojuje.
Sdílená Ollama neumožňuje zaručit výhradní vlastnictví modelu v dalších
aplikacích; tlačítko používej po dokončení jejich práce.

Nemotron je požadovaný výchozí model, ale testy odhalily i chybnou českou
odpověď na jednoduchý počet a nepoužití nástroje. V Nastavení lze textový
model změnit například na `gemma4:cloud`, která byla ve srovnání rychlejší.
Ani ta nezaručuje pravdivost všech odpovědí. Bezpečnost akcí proto nadále
vynucuje nezávislá politika: validované nástroje, potvrzení citlivých akcí,
blokování destruktivních akcí a žádný libovolný shell.

## Data, obnova a diagnostika

Zabalená aplikace používá `%LOCALAPPDATA%\Martin`, zdrojová `data/`.
`settings.json`, `martin.db` a `konverzace.db` se zachovávají. Před migrací
starých nastavení vzniká `settings.pre-2.1.json`. Dřívější výslovné Local
Only se zachová jako Offline; režim Cloud můžeš zvolit v nastavení.
Metadata spotřeby jsou oddělená v `cloud-usage.db`, bez promptů a obrázků.
Logy mají ID požadavků, model, stav a časy. Logy přepisů mohou obsahovat
osobní obsah; neposílej je veřejně bez kontroly.

Výslovné diagnostické příkazy (používají skutečný cloud; hlasová diagnostika
také reálný mikrofon a reproduktor, rozpoznání syntetické české řeči):

```
Martin.exe --diagnose-cloud C:\cesta\cloud-report.json
Martin.exe --diagnose-voice C:\cesta\voice-report.json 12
```

Lidská řeč uživatele, jeho přízvuk a chování během běžícího MSFS vyžadují
samostatné praktické ověření. Nejsou nahrazené syntetickým testem.

Sestavení: `python packaging/build_windows.py --out build_output/cloud-release`.
Složka musí být nová. ZIP: `python packaging/make_installer.py --build-dir
build_output/cloud-release --out build_output/Martin-2.1-Cloud-win64.zip`.
Build obsahuje manifest SHA-256 souborů a zdrojového commitu.
