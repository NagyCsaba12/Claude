# NEXUS AI – saját, offline is működő, önállóan tanuló mesterséges intelligencia

A NEXUS a saját gépeden, a **D:\NexusAI** mappában fut. Saját tudásbázisa van, internet nélkül is
működik, és folyamatosan tanul a netről, a dokumentumaidból, más AI-któl és a te értékeléseidből.

## Fő képességek

| Terület | Mit tud |
|---|---|
| 🖥️ **Rendszergazda** | PowerShell/Bash parancsok futtatása (jóváhagyással), rendszerinfó, folyamatok, AD/GPO/Linux tudás |
| 💻 **Programozó** | minden nyelven kódot ír, fájlba ment, Python kódot futtat és tesztel |
| 📄 **Dokumentumok** | olvas: PDF, Word, Excel, PowerPoint, HTML, szöveg, forráskód · készít: Markdown, HTML, Word |
| 🌐 **Internetes kutatás** | keresés (API kulcs nélkül), oldalak letöltése, a `robots.txt` szabályait betartja |
| 🔌 **Hálózati eszközök** | ping, portellenőrzés, helyi hálózat felderítése, DNS; Cisco, MikroTik, Juniper, Aruba, HP, Huawei, Fortinet, Palo Alto eszközök SSH programozása (show / configure / backup) |
| 🧠 **Önálló tanulás** | tanuló üzem, tudáshiány felismerése, tényeket von ki, altémákat keres, tanul a rossz válaszaiból |
| 🤖 **Más AI-k** | 26 szolgáltató név szerint (helyi és felhős), ezektől is tud tanulni |
| 🔗 **Saját API** | OpenAI-kompatibilis helyi szerver, így más programok is használhatják |

## Telepítés (Windows, D: meghajtó)

Rendszergazdai PowerShellben, a letöltött projekt mappájában:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install_windows.ps1 -NightlyLearning
```

A telepítő a következőket végzi el:
1. telepíti a Pythont, ha még nincs fent
2. a programot a `D:\NexusAI\app` mappába másolja, és saját Python környezetet hoz létre (`D:\NexusAI\venv`)
3. telepíti az **Ollamát**, és a gép RAM-jához illő legjobb nyílt modellt tölti le (a modellek is a D:-re kerülnek):
   - ≥48 GB: `qwen3:32b` · ≥24 GB: `qwen3:14b` · ≥12 GB: `qwen3:8b` · egyébként: `qwen3:4b`
4. `nexus init`: létrehozza a mappákat és feltölti a tanulási sort az alap tantervvel
5. **`nexus bootstrap`: letölti az alaptudást a legjobb elérhető hiteles forrásokból** (lásd lent)
6. `-NightlyLearning` kapcsolóval minden éjjel 02:00-kor 90 percig tanul
7. asztali ikont hoz létre („NEXUS AI”)

Kapcsolók: `-Target E:\NexusAI` (más meghajtó), `-NoOllama`, `-NoBootstrap`.

## Alaptudás: a legjobb elérhető források

A `nexus bootstrap` parancs a netről a legmegbízhatóbb, elsődleges forrásokat tölti le. Ezek magas
megbízhatósági pontszámot kapnak, így a keresésnél előnyt élveznek a sima weboldalakkal szemben:

| Terület | Források |
|---|---|
| Programozás | Python tutorial és HOWTO-k, MDN JavaScript Guide, TypeScript Handbook, Microsoft C# tour, The Rust Book, Effective Go, dev.java, cppreference, PostgreSQL tutorial, Pro Git könyv, GNU Bash kézikönyv, PowerShell dokumentáció, OWASP Top 10 |
| Rendszergazda | Microsoft Learn: AD DS, Windows Server hibaelhárítás, hálózati szolgáltatások · Arch Wiki · Ubuntu Server docs · systemd |
| Hálózat | **25 RFC szabvány** (IPv4/IPv6, TCP, UDP, DNS, DHCP, OSPF, BGP, NAT, IPsec, IKEv2, TLS 1.3, SNMP, NTP, SSH, RADIUS, VXLAN…) · gyártói dokumentáció (Cisco, MikroTik, Juniper, Aruba, Fortinet) |
| Fogalmak | kb. 70 Wikipedia szócikk (angol és magyar) |
| Dokumentumok | Google developer documentation style guide, Write the Docs |

```
nexus bootstrap                          # minden terület (kb. 1–2 óra)
nexus bootstrap -a halozat programozas   # csak ezek a területek
nexus bootstrap --scale 0.3              # gyorsabb, kisebb alaptudás
```

Ha a futást megszakítod, az addig letöltött tudás megmarad. Újrafuttatáskor a már meglévő tartalmat
kihagyja (tartalom-hash alapján), így a paranccsal frissíteni is lehet.

**Még nagyobb offline tudásért (opcionális):** a [Kiwix](https://kiwix.org) teljes offline Wikipédiát,
Stack Overflow-t és DevDocs-ot kínál ZIM fájlokban. Ezekből HTML-t exportálva a
`nexus ingest <mappa>` paranccsal felveheted őket a tudásbázisba.

## Használat

```
nexus chat                              # beszélgetés (/jo /rossz /tanul <téma> /status /kilep)
nexus ask "Írj PowerShell szkriptet, ami listázza a 90 napja inaktív AD felhasználókat"
nexus learn "Cisco IOS port security"   # téma megtanulása a netről
nexus learn --loop --minutes 60         # TANULÓ ÜZEM: a tanulási sor feldolgozása
nexus learn-ai "BGP route reflector" -p anthropic openai gemini   # tanulás más AI-któl
nexus ingest D:\Dokumentumok\IT         # saját dokumentumok felvétele (alap: D:\NexusAI\inbox)
nexus teach "A DC01 a tartományvezérlő, IP 192.168.1.10"
nexus rate 42 good                      # válasz értékelése -> ebből tanul
nexus reflect                           # rossz válaszok újratanulása és újragondolása
nexus status                            # tudásbázis statisztika
nexus serve                             # helyi API: http://127.0.0.1:8765/v1/chat/completions
```

## AI szolgáltatók (név szerint)

`nexus providers` kilistázza az összeset az állapotukkal együtt. Kulcs megadása:
`nexus keys set <név> <kulcs>` (a kulcs a `D:\NexusAI\config\api_keys.json` fájlba kerül), vagy
környezeti változóval.

**Helyi (offline):** Ollama, LM Studio, llama.cpp, LocalAI, Jan
**Felhő:** Anthropic Claude, OpenAI GPT, Google Gemini, Mistral, Cohere, xAI Grok, DeepSeek, Groq,
Perplexity, Together AI, OpenRouter, Fireworks, Cerebras, Hugging Face, NVIDIA NIM, Alibaba Qwen,
Moonshot Kimi, Zhipu GLM, AI21, SambaNova, Azure OpenAI

Modell cseréje: `nexus keys set openai_model gpt-4o`, vagy egyszeri használatnál `openai:gpt-4o`.
Egyéni cím: `nexus keys set azure_url https://...`.

A `config.json` fájlban:
- `fallback_providers`: melyik felhős AI-t használja, ha a helyi modell nem fut
- `learn_from_ai_providers`: tanuló üzemben mely AI-któl kérdezzen

## Hogyan lesz egyre okosabb?

```
 kérdés ──► tudásbázis + emlékek (offline keresés) ──► modell (helyi → felhő → csak tudásbázis)
               ▲                                            │  eszközök (parancs, fájl, web, hálózat)
               │                                            ▼
   ┌───────────┴──────────────┐                        válasz ──► naplózás ──► értékelés (/jo /rossz)
   │ tanuló üzem (learn)      │◄── tudáshiány ─────────────┘                    │
   │ web · dokumentumok · AI-k│◄── rossz válasz ◄────────────────────────────────┤
   └──────────────────────────┘    jó válasz ──► tudásbázisba kerül ◄──────────┘
                                   jó válaszok ──► export (finomhangolás)
```

1. **Tudáshiány felismerése:** ha egy kérdésre nincs releváns tudása, a téma bekerül a tanulási sorba.
2. **Tanuló üzem:** keres a neten, letölti és feldarabolja az oldalakat, a modellel kivonja a
   legfontosabb tényeket, és kapcsolódó altémákat is sorba állít, így a tudása magától bővül.
3. **Visszajelzés:** a jónak értékelt válasz megbízható tudássá válik, a rossz válasz témáját pedig
   újratanulja (`nexus reflect`).
4. **Megerősítés:** az ismételten megtanult tények megbízhatósága nő, és a keresésnél előrébb kerülnek.
5. **Finomhangolás (haladó):** `nexus export tanito.jsonl` exportálja a jó válaszokat, amelyekkel
   a helyi modell LoRA-val továbbtanítható (pl. Unsloth vagy LLaMA-Factory segítségével), majd Ollamába importálható.

## Biztonság

- Parancsfuttatás, fájlírás és hálózati eszköz konfigurálása előtt **mindig jóváhagyást kér**
  (`confirm_system_commands`, `confirm_network_changes`).
- API szerver módban ezek a műveletek tiltva vannak, és a szerver csak a saját gépről érhető el (127.0.0.1).
- Hálózatszkennelés csak privát (saját) alhálózaton engedélyezett.
- Az API kulcsok helyben maradnak (`config\api_keys.json`), a git ezt a fájlt figyelmen kívül hagyja.
- Más AI-któl tanulásnál vedd figyelembe a szolgáltatók felhasználási feltételeit: több szolgáltató
  tiltja, hogy a kimenetükkel versenytárs modellt tanítsanak. A tudásbázisba forrásmegjelöléssel
  eltárolt referencia más kategória, mint a finomhangolás.

## Mappaszerkezet

```
D:\NexusAI\
  app\nexus\        program
  venv\             saját Python környezet
  models\           Ollama modellek (offline)
  data\knowledge.db tudásbázis (SQLite + FTS5)
  inbox\            ide másolt dokumentumokat az `ingest` feldolgozza
  output\           elkészült dokumentumok
  config\           config.json, api_keys.json
  nexus.bat         indító
```

Részletes felépítés: [docs/ARCHITEKTURA.md](docs/ARCHITEKTURA.md)

## Fejlesztés

Az alapműködéshez nincs szükség külső csomagra (csak Python 3.10+). Tesztek futtatása:

```
python -m unittest discover -s tests -v
```
