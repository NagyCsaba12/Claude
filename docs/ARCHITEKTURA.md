# TecF Ai – architektúra

## Modulok

| Fájl | Feladat |
|---|---|
| `tecf/config.py` | Konfiguráció, útvonalak (`D:\TecFAi`, felülírható: `TECF_HOME`), API kulcsok |
| `tecf/knowledge.py` | Tudásbázis: SQLite + FTS5 (BM25), források, szövegrészek, emlékek, beszélgetések, tanulási sor |
| `tecf/brain.py` | Agy: modellválasztás, kontextus-összeállítás (RAG), eszközhasználati ciklus, naplózás |
| `tecf/learning.py` | Tanuló üzem, tanulás más AI-któl, fájlfeldolgozás, tény kivonás, önreflexió, tanterv |
| `tecf/bootstrap.py` | Alaptudás: hivatalos dokumentációk bejárása, RFC-k, Wikipedia, gyártói dokumentáció |
| `tecf/providers/` | 26 AI szolgáltató név szerint, egységes kliens (OpenAI, Anthropic, Gemini, Cohere formátum) |
| `tecf/tools/` | Eszközök: `system`, `files`, `documents`, `web`, `network` |
| `tecf/server.py` | Helyi, OpenAI-kompatibilis HTTP API |
| `tecf/cli.py` | Parancssori felület |

## Modellválasztás

1. `local_provider` / `local_model` (alapból Ollama `qwen3:8b`) – ha fut, ezt használja (offline)
2. `fallback_providers` sorrendben az első, amelyhez van API kulcs (`--offline` kikapcsolja)
3. Ha egyik sem elérhető: **offline tudásbázis mód** – a legrelevánsabb tárolt ismereteket adja vissza

Ha hívás közben hiba történik, automatikusan a következő elérhető modellre vált.

## Eszközhívási protokoll

Modellfüggetlen, így kis helyi modellekkel is működik. A modell a válaszában ilyen blokkot ír:

````
```tool
{"tool": "port_check", "args": {"host": "192.168.1.1", "ports": "22,80,443"}}
```
````

A TecF Ai lefuttatja az eszközt (a veszélyes eszközöknél előtte jóváhagyást kér), és az eredményt
`ESZKÖZ EREDMÉNYEK:` üzenetként visszaküldi. Legfeljebb 8 lépés fér bele egy kérdésbe.

## Tudásbázis rangsorolás

`pontszám = BM25 × (0.5 + megbízhatóság)`

| Forrás | Megbízhatóság |
|---|---|
| RFC | 0.95 |
| Hivatalos dokumentáció (bootstrap) | 0.90 |
| Gyártói dokumentáció | 0.85 |
| Jónak értékelt saját válasz | 0.80 |
| Wikipedia | 0.80 |
| Saját fájlok (`ingest`) | 0.70 |
| Más AI válasza | 0.60 |
| Általános weboldal (`learn`) | 0.50 |

A keresés ékezetfüggetlen (`remove_diacritics`), és prefix egyezést használ, így a magyar ragozott
szóalakokat is megtalálja. Az emlékek megbízhatósága minden megerősítésnél nő:
`c ← c + (1 − c) × 0.3`.

## Bővítés

- **Új eszköz:** függvény a `tecf/tools/` alatt a `@tool("leírás", dangerous=...)` dekorátorral.
- **Új AI szolgáltató:** egy `ProviderSpec` sor a `tecf/providers/__init__.py` fájlban.
- **Új alaptudás forrás:** `Crawl(...)` sor a `CRAWLS` listában, vagy RFC / Wikipedia cím a `bootstrap.py` fájlban.
- **Szemantikus keresés (tervezett):** helyi embedding modell (pl. `ollama pull nomic-embed-text`)
  vektorai egy külön táblában, hibrid (BM25 + vektor) rangsorolással.
