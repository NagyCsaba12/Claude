"""TecF Ai parancssor.

  tecf init                      – könyvtárak (D:\\TecFAi), konfiguráció, alap tanterv
  tecf bootstrap                 – ALAPTUDÁS: legjobb hiteles források letöltése (dokumentációk, RFC, Wikipedia)
  tecf  /  tecf gui              – asztali ablak
  tecf chat                      – interaktív beszélgetés a parancssorban (eszközhasználattal)
  tecf ask "kérdés"              – egyszeri kérdés
  tecf learn "téma" [...]        – témák megtanulása a netről
  tecf learn --loop --minutes 60 – TANULÓ ÜZEM: a tanulási sor folyamatos feldolgozása
  tecf learn-ai "téma" -p openai anthropic – tanulás más AI-któl
  tecf ingest <fájl|mappa>       – dokumentumok felvétele a tudásbázisba (alap: inbox)
  tecf providers                 – AI szolgáltatók név szerinti listája és állapota
  tecf keys set <név> <kulcs>    – API kulcs mentése
  tecf teach "tény"              – tény kézi megtanítása
  tecf rate <id> good|bad        – válasz értékelése (ebből tanul)
  tecf reflect                   – rossz válaszok újragondolása
  tecf status                    – tudásbázis statisztika
  tecf export <fájl.jsonl>       – finomhangoló adatok exportja
  tecf serve [--port 8765]       – helyi, OpenAI-kompatibilis API szerver
"""
from __future__ import annotations

import argparse
import sys

from tecf import __version__
from tecf.config import Config


def _confirm(action: str) -> bool:
    try:
        return input(f"\n⚠ Engedélyezed? {action[:300]}\n  [i/N]: ").strip().lower() in ("i", "igen", "y", "yes")
    except EOFError:
        return False


def _brain(cfg: Config):
    from tecf.brain import Brain
    return Brain(cfg, confirm=_confirm)


def cmd_init(cfg: Config, a) -> None:
    from tecf.learning import Learner
    cfg.save()
    n = Learner(_brain(cfg)).seed_curriculum()
    print(f"TecF Ai inicializálva: {cfg.root}\n  konfiguráció: {cfg.config_path}\n  tudásbázis:   {cfg.db_path}\n"
          f"  inbox:        {cfg.inbox_dir}\n  {n} alap téma a tanulási sorban.\n\n"
          "Következő lépések:\n  1) Offline modell: telepítsd az Ollamát, majd: ollama pull " + cfg.local_model +
          "\n  2) tecf bootstrap   (alaptudás letöltése a netről)"
          "\n  3) (opcionális) tecf keys set anthropic <kulcs>\n  4) tecf learn --loop --minutes 60\n  5) tecf chat")


def cmd_gui(cfg: Config, a) -> None:
    from tecf.gui import main as gui_main
    gui_main(cfg)


def cmd_bootstrap(cfg: Config, a) -> None:
    from tecf.bootstrap import Bootstrapper
    from tecf.knowledge import KnowledgeBase
    print("ALAPTUDÁS letöltése a legjobb elérhető forrásokból (ez akár 1-2 óra is lehet)...")
    try:
        n = Bootstrapper(KnowledgeBase(cfg.db_path), delay=a.delay, scale=a.scale).run(a.areas or None)
    except KeyboardInterrupt:
        print("\nMegszakítva – az eddig letöltött tudás megmaradt, újrafuttatáskor a duplikátumokat kihagyja.")
        return
    print(f"\nKész: {n} új hiteles forrás a tudásbázisban.")


def cmd_chat(cfg: Config, a) -> None:
    b = _brain(cfg)
    p = b.provider()
    print(f"TecF Ai {__version__} – modell: {p.label if p else 'nincs (offline tudásbázis mód)'}")
    print("Parancsok: /jo /rossz (előző válasz értékelése), /tanul <téma>, /status, /kilep\n")
    history: list[dict] = []
    last_id = None
    while True:
        try:
            q = input("Te> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q:
            continue
        if q in ("/kilep", "/exit", "/quit"):
            break
        if q in ("/jo", "/rossz") and last_id:
            b.kb.rate(last_id, 1 if q == "/jo" else -1)
            print("Köszönöm, megjegyeztem.\n")
            continue
        if q.startswith("/tanul "):
            from tecf.learning import Learner
            Learner(b).learn_topic(q[7:].strip())
            continue
        if q == "/status":
            cmd_status(cfg, a, b)
            continue
        answer, last_id = b.ask(q, history[-12:])
        history += [{"role": "user", "content": q}, {"role": "assistant", "content": answer}]
        print(f"\nTecF Ai> {answer}\n")


def cmd_ask(cfg: Config, a) -> None:
    answer, cid = _brain(cfg).ask(" ".join(a.question))
    print(answer)
    print(f"\n[#{cid}] értékelés: tecf rate {cid} good|bad", file=sys.stderr)


def cmd_learn(cfg: Config, a) -> None:
    from tecf.learning import Learner
    ln = Learner(_brain(cfg))
    for t in a.topics:
        print(f"→ {ln.learn_topic(t)} új forrás")
    if a.loop:
        print(f"TANULÓ ÜZEM – {a.minutes} percig (Ctrl+C a leállításhoz)")
        try:
            n = ln.learn_loop(a.minutes, a.max_topics)
            print(f"Kész: {n} téma feldolgozva.")
        except KeyboardInterrupt:
            print("\nLeállítva.")
    if not a.topics and not a.loop:
        print("Adj meg témát, vagy használd: tecf learn --loop")


def cmd_learn_ai(cfg: Config, a) -> None:
    from tecf.learning import Learner
    n = Learner(_brain(cfg)).learn_from_ais(" ".join(a.topic), providers=a.providers or None)
    print(f"{n} AI válasz eltárolva.")


def cmd_ingest(cfg: Config, a) -> None:
    from tecf.learning import Learner
    print(f"{Learner(_brain(cfg)).ingest_path(a.path or cfg.inbox_dir)} dokumentum felvéve.")


def cmd_providers(cfg: Config, a) -> None:
    from tecf.providers import PROVIDERS, get_provider
    keys = cfg.load_keys()
    print(f"{'NÉV':<12} {'SZOLGÁLTATÓ':<42} {'ALAP MODELL':<34} ÁLLAPOT")
    for name, spec in PROVIDERS.items():
        p = get_provider(name, keys)
        if spec.local:
            state = "● fut" if p.available() else "○ nem fut"
        else:
            state = "● kulcs megadva" if p.api_key else f"○ kulcs kell ({spec.env_key})"
        print(f"{name:<12} {spec.title[:41]:<42} {p.model[:33]:<34} {state}")


def cmd_keys(cfg: Config, a) -> None:
    from tecf.providers import PROVIDERS
    base = a.name.removesuffix("_url").removesuffix("_model")
    if base not in PROVIDERS:
        sys.exit(f"Ismeretlen szolgáltató: {a.name}")
    cfg.set_key(a.name, a.value)
    print(f"Mentve: {a.name} -> {cfg.keys_path}")


def cmd_teach(cfg: Config, a) -> None:
    from tecf.knowledge import KnowledgeBase
    KnowledgeBase(cfg.db_path).remember(" ".join(a.fact), a.category, confidence=0.9)
    print("Megtanultam.")


def cmd_rate(cfg: Config, a) -> None:
    from tecf.knowledge import KnowledgeBase
    KnowledgeBase(cfg.db_path).rate(a.id, 1 if a.value in ("good", "jo", "jó", "+") else -1)
    print("Értékelés mentve.")


def cmd_reflect(cfg: Config, a) -> None:
    from tecf.learning import Learner
    print(f"{Learner(_brain(cfg)).reflect(a.limit)} válasz újragondolva.")


def cmd_status(cfg: Config, a, brain=None) -> None:
    from tecf.knowledge import KnowledgeBase
    kb = brain.kb if brain else KnowledgeBase(cfg.db_path)
    print(f"TecF Ai {__version__}  –  {cfg.root}")
    for k, v in kb.stats().items():
        print(f"  {k:<16} {v}")


def cmd_export(cfg: Config, a) -> None:
    from tecf.knowledge import KnowledgeBase
    n = KnowledgeBase(cfg.db_path).export_training_data(a.file)
    print(f"{n} példa exportálva: {a.file}")


def cmd_serve(cfg: Config, a) -> None:
    from tecf.server import serve
    serve(cfg, a.host, a.port)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="tecf", description="TecF Ai – saját, offline is működő tanuló AI")
    ap.add_argument("--home", help="Telepítési könyvtár (alap: D:\\TecFAi)")
    ap.add_argument("--offline", action="store_true", help="Csak helyi modell / tudásbázis")
    sp = ap.add_subparsers(dest="cmd")
    sp.add_parser("gui").set_defaults(fn=cmd_gui)
    sp.add_parser("init").set_defaults(fn=cmd_init)
    p = sp.add_parser("bootstrap")
    p.add_argument("-a", "--areas", nargs="*", choices=["programozas", "rendszergazda", "halozat", "dokumentumok"])
    p.add_argument("--scale", type=float, default=1.0, help="0.1–1.0: mennyiség szorzó")
    p.add_argument("--delay", type=float, default=1.0, help="várakozás kérések között (mp)")
    p.set_defaults(fn=cmd_bootstrap)
    sp.add_parser("chat").set_defaults(fn=cmd_chat)
    p = sp.add_parser("ask")
    p.add_argument("question", nargs="+")
    p.set_defaults(fn=cmd_ask)
    p = sp.add_parser("learn")
    p.add_argument("topics", nargs="*")
    p.add_argument("--loop", action="store_true", help="tanuló üzem: sor folyamatos feldolgozása")
    p.add_argument("--minutes", type=float, default=30)
    p.add_argument("--max-topics", type=int, default=50)
    p.set_defaults(fn=cmd_learn)
    p = sp.add_parser("learn-ai")
    p.add_argument("topic", nargs="+")
    p.add_argument("-p", "--providers", nargs="*")
    p.set_defaults(fn=cmd_learn_ai)
    p = sp.add_parser("ingest")
    p.add_argument("path", nargs="?")
    p.set_defaults(fn=cmd_ingest)
    sp.add_parser("providers").set_defaults(fn=cmd_providers)
    p = sp.add_parser("keys")
    p.add_argument("action", choices=["set"])
    p.add_argument("name")
    p.add_argument("value")
    p.set_defaults(fn=cmd_keys)
    p = sp.add_parser("teach")
    p.add_argument("fact", nargs="+")
    p.add_argument("-c", "--category", default="manual")
    p.set_defaults(fn=cmd_teach)
    p = sp.add_parser("rate")
    p.add_argument("id", type=int)
    p.add_argument("value")
    p.set_defaults(fn=cmd_rate)
    p = sp.add_parser("reflect")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(fn=cmd_reflect)
    sp.add_parser("status").set_defaults(fn=cmd_status)
    p = sp.add_parser("export")
    p.add_argument("file")
    p.set_defaults(fn=cmd_export)
    p = sp.add_parser("serve")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(fn=cmd_serve)
    return ap


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = build_parser().parse_args(argv)
    if a.cmd is None:  # paraméter nélkül az asztali ablak indul
        a.fn = cmd_gui
    cfg = Config.load(a.home)
    if a.offline:
        cfg.offline_only = True
    a.fn(cfg, a)
    return 0
