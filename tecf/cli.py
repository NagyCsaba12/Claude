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
  tecf update                     – frissítés GitHubról (a tudás és a beállítások megmaradnak)

  SAJÁT NYELVI MODELL:
  tecf model info                 – hardver, ajánlott modellméret, állapot
  tecf model base --hours 3       – AJÁNLOTT: kész alapmodellből (Qwen3) saját modell a te tudásodra hangolva
  tecf model ollama               – a saját modell átadása az Ollamának (gyorsabb, eszközhasználat)
  NULLÁRÓL TANÍTOTT MODELL (kísérleti, a gép kapacitásához méretezve):
  tecf model build --hours 8      – mindent egyben: szöveggyűjtés, tokenizáló, tanítás
  tecf model corpus | prepare | train --minutes 60 [--stage sft]   – lépésenként
  tecf model test "szöveg"        – kipróbálás
  tecf model use [--off]          – beállítás a TecF Ai modelljeként
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
    print("Parancsok: /jo /rossz (előző válasz értékelése), /tanul <téma>, /status, /kilep"
          "  –  Ctrl+C: válasz leállítása\n")
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
        import threading
        cancel, streamed = threading.Event(), []

        def on_token(t: str) -> None:
            if not streamed:
                print("\nTecF Ai> ", end="", flush=True)
            streamed.append(t)
            print(t, end="", flush=True)

        result: list = []
        worker = threading.Thread(target=lambda: result.append(b.ask(q, history[-12:], cancel=cancel,
                                                                      on_token=on_token)), daemon=True)
        worker.start()
        try:
            while worker.is_alive():
                worker.join(0.2)
        except KeyboardInterrupt:  # Ctrl+C: a válasz leáll, a beszélgetés folytatódik
            cancel.set()
            worker.join()
        if not result:
            continue
        answer, last_id = result[0]
        history += [{"role": "user", "content": q}, {"role": "assistant", "content": answer}]
        print(f"\n\n" if streamed and not cancel.is_set() else "", end="")
        if not streamed:
            print(f"\nTecF Ai> {answer}\n")
        elif cancel.is_set():
            print("\n⏹ (Leállítva)\n")


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


def _mix(items: list[str] | None) -> dict[str, int] | None:
    """'wiki-hu=500 code=100' -> {'wiki-hu': 500, 'code': 100}"""
    if not items:
        return None
    from tecf.llm.corpus import DEFAULT_MIX
    return {k: int(v) if v else DEFAULT_MIX.get(k, 200) for k, _, v in (i.partition("=") for i in items)}


def cmd_model(cfg: Config, a) -> None:
    try:
        from tecf.llm import pipeline
    except ImportError as e:
        sys.exit(f"Hiányzó csomag ({e.name}). Telepítsd: pip install -r requirements-train.txt")
    from tecf.llm import model_dir
    act = a.action
    if act == "info":
        print(pipeline.status(cfg))
        from tecf.llm.corpus import SOURCES
        print("\nLetölthető szöveggyűjtemények (tecf model corpus -s név=MB ...):")
        for n, src in SOURCES.items():
            print(f"  {n:<12} {src[5]}")
    elif act == "corpus":
        pipeline.collect(cfg, _mix(a.sources))
    elif act == "prepare":
        pipeline.prepare(cfg)
    elif act == "train":
        from tecf.llm.train import train
        if a.fresh:
            pipeline.reset(cfg)
            pipeline.prepare(cfg)
        train(model_dir(cfg.root), a.stage, a.minutes or 60, a.size)
    elif act == "build":
        pipeline.build(cfg, a.hours, _mix(a.sources), download=not a.no_download, fresh=a.fresh)
        print("\nKipróbálás: tecf model test \"Mi az a VLAN?\"   Beállítás: tecf model use")
    elif act == "base":
        from tecf.llm.base import finetune
        finetune(cfg, a.minutes or a.hours * 60, a.base)
        pipeline.use(cfg, True)
        print("\nA TecF Ai mostantól a saját modellt használja. Kipróbálás: tecf model test \"Mi az a VLAN?\"")
    elif act == "ollama":
        from tecf.llm.base import export_to_ollama
        if export_to_ollama(cfg):
            cfg.local_provider, cfg.local_model = "ollama", "tecf-agy"
            cfg.save()
            print("Kész: a TecF Ai az Ollamán keresztül a saját modelljét (tecf-agy) használja.")
        else:
            print("Az Ollama import nem sikerült; a saját modell továbbra is közvetlenül használható (tecf model use).")
    elif act == "test":
        prompt = " ".join(a.text) or "Mi az a VLAN?"
        base_dir = model_dir(cfg.root) / "alap" / "modell"
        if (base_dir / "config.json").exists() and not a.scratch:
            from tecf.llm.base import BaseModelRunner
            print(BaseModelRunner.get(base_dir).chat([{"role": "user", "content": prompt}]))
            return
        from tecf.llm.infer import OwnModel
        m = OwnModel.get(model_dir(cfg.root))
        print(f"[{m.info}]\n")
        print(m.chat([{"role": "user", "content": prompt}]) if a.chat else prompt + " " + m.complete(prompt))
    elif act == "use":
        pipeline.use(cfg, not a.off)
        print("A TecF Ai mostantól a saját modellt használja." if not a.off else "Visszaállítva az Ollama modellre.")


def cmd_update(cfg: Config, a) -> None:
    from tecf import updater
    if a.mark:
        updater.mark_current()
    else:
        updater.update(force=a.force)


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
    p = sp.add_parser("model", help="saját nyelvi modell")
    p.add_argument("action", choices=["info", "base", "ollama", "corpus", "prepare", "train", "build", "test", "use"])
    p.add_argument("text", nargs="*", help="test: kiinduló szöveg")
    p.add_argument("-s", "--sources", nargs="*", help="forrás=MB, pl. wiki-hu=500 code=100")
    p.add_argument("--hours", type=float, default=4, help="base/build: teljes tanítási idő")
    p.add_argument("--base", help="base: alapmodell (pl. Qwen/Qwen3-4B), alap: a géphez illő")
    p.add_argument("--scratch", action="store_true", help="test: a nulláról tanított modellt próbálja")
    p.add_argument("--minutes", type=float, help="train (alap 60) / base: tanítási idő percben")
    p.add_argument("--stage", choices=["pretrain", "sft"], default="pretrain")
    p.add_argument("--size", default="auto", help="auto | mini | kicsi | kozepes | nagy | xl")
    p.add_argument("--fresh", action="store_true", help="új modell a nulláról")
    p.add_argument("--no-download", action="store_true", help="csak a saját tudásbázisból tanul")
    p.add_argument("--chat", action="store_true", help="test: beszélgetés formátumban")
    p.add_argument("--off", action="store_true", help="use: vissza az Ollamára")
    p.set_defaults(fn=cmd_model)
    p = sp.add_parser("update", help="frissítés GitHubról")
    p.add_argument("--force", action="store_true", help="akkor is letölti, ha naprakész")
    p.add_argument("--mark", action="store_true", help="telepítéskor: a jelenlegi változat rögzítése")
    p.set_defaults(fn=cmd_update)
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
