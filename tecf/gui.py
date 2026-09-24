"""TecF Ai asztali ablak (tkinter – a Python része, külön telepítés nem kell).

Indítás: tecf gui   (a telepítő asztali ikont is készít hozzá)
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, simpledialog

from tecf import __version__
from tecf.brain import Brain
from tecf.config import Config
from tecf.knowledge import KnowledgeBase

BG, PANEL, FG, ACCENT, MUTED = "#0f172a", "#1e293b", "#e2e8f0", "#38bdf8", "#94a3b8"


class TecFApp:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.root = tk.Tk()
        self.root.title(f"TecF Ai {__version__}")
        self.root.geometry("980x720")
        self.root.configure(bg=BG)
        self.lock = threading.Lock()   # egyszerre egy háttérfeladat használja a tudásbázist
        self.ui: queue.Queue = queue.Queue()
        self.history: list[dict] = []
        self.last_id: int | None = None
        self.brain = Brain(cfg, KnowledgeBase(cfg.db_path, threaded=True),
                           confirm=self._confirm_from_worker, log=self._log)
        self._build()
        self.root.after(80, self._pump)
        self._run_bg(self._refresh_status)

    # ---------------- felület ----------------
    def _build(self) -> None:
        top = tk.Frame(self.root, bg=PANEL)
        top.pack(fill="x")
        tk.Label(top, text="TecF Ai", fg=ACCENT, bg=PANEL, font=("Segoe UI", 16, "bold")).pack(side="left", padx=12,
                                                                                            pady=8)
        for text, cmd in [("📚 Tanulj témát", self._learn_topic), ("🔁 Tanuló üzem", self._learn_loop),
                          ("🌐 Alaptudás letöltése", self._bootstrap), ("📄 Dokumentum felvétele", self._ingest),
                          ("🧬 Saját modell", self._own_model),
                          ("📊 Állapot", lambda: self._run_bg(self._show_stats))]:
            tk.Button(top, text=text, command=cmd, bg=BG, fg=FG, relief="flat", activebackground=ACCENT,
                      padx=10).pack(side="left", padx=3)

        self.chat = scrolledtext.ScrolledText(self.root, wrap="word", bg=BG, fg=FG, insertbackground=FG,
                                              font=("Consolas", 11), relief="flat", padx=12, pady=8)
        self.chat.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self.chat.tag_config("user", foreground=ACCENT, font=("Consolas", 11, "bold"))
        self.chat.tag_config("ai", foreground=FG)
        self.chat.tag_config("log", foreground=MUTED, font=("Consolas", 9))
        self.chat.configure(state="disabled")

        bottom = tk.Frame(self.root, bg=BG)
        bottom.pack(fill="x", padx=8, pady=8)
        self.entry = tk.Text(bottom, height=3, bg=PANEL, fg=FG, insertbackground=FG, font=("Segoe UI", 11),
                             relief="flat", wrap="word")
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", self._on_enter)
        side = tk.Frame(bottom, bg=BG)
        side.pack(side="left", padx=(6, 0))
        self.send_btn = tk.Button(side, text="Küldés ➤", command=self._send, bg=ACCENT, fg=BG, relief="flat",
                                  font=("Segoe UI", 10, "bold"), width=11)
        self.send_btn.pack(fill="x")
        rate = tk.Frame(side, bg=BG)
        rate.pack(fill="x", pady=(4, 0))
        tk.Button(rate, text="👍 Jó", command=lambda: self._rate(1), bg=PANEL, fg=FG, relief="flat").pack(
            side="left", expand=True, fill="x")
        tk.Button(rate, text="👎 Rossz", command=lambda: self._rate(-1), bg=PANEL, fg=FG, relief="flat").pack(
            side="left", expand=True, fill="x")

        self.status = tk.Label(self.root, text="Indulás...", anchor="w", bg=PANEL, fg=MUTED, padx=10)
        self.status.pack(fill="x", side="bottom")
        self._write("TecF Ai", "Szia! Kérdezz bármit (rendszergazda, programozás, dokumentumok, hálózat). "
                               "Enter: küldés, Shift+Enter: új sor.", "ai")
        self.entry.focus_set()

    def _write(self, who: str, text: str, tag: str) -> None:
        self.chat.configure(state="normal")
        if tag == "log":
            self.chat.insert("end", text + "\n", "log")
        else:
            self.chat.insert("end", f"\n{who}:\n", "user" if tag == "user" else "ai")
            self.chat.insert("end", text.strip() + "\n", tag)
        self.chat.configure(state="disabled")
        self.chat.see("end")

    # ---------------- szálkezelés: a háttérszálak csak a sorba írnak ----------------
    def _pump(self) -> None:
        try:
            while True:
                self.ui.get_nowait()()
        except queue.Empty:
            pass
        self.root.after(80, self._pump)

    def _log(self, msg: str) -> None:
        self.ui.put(lambda: self._write("", msg, "log"))

    def _run_bg(self, fn, *args) -> None:
        def work():
            with self.lock:
                try:
                    fn(*args)
                except Exception as e:  # a hiba az ablakban jelenjen meg, ne álljon le a program
                    self._log(f"Hiba: {type(e).__name__}: {e}")
            self.ui.put(lambda: self.send_btn.configure(state="normal"))
        threading.Thread(target=work, daemon=True).start()

    def _confirm_from_worker(self, action: str) -> bool:
        """Veszélyes művelet jóváhagyása: a háttérszál megvárja a felhasználó döntését."""
        done, answer = threading.Event(), [False]

        def ask():
            answer[0] = messagebox.askyesno("Jóváhagyás szükséges",
                                            f"A TecF Ai ezt szeretné végrehajtani:\n\n{action[:800]}\n\nEngedélyezed?")
            done.set()
        self.ui.put(ask)
        done.wait()
        return answer[0]

    # ---------------- műveletek ----------------
    def _on_enter(self, event):
        if not event.state & 0x1:  # Shift nélkül küld
            self._send()
            return "break"
        return None

    def _send(self) -> None:
        q = self.entry.get("1.0", "end").strip()
        if not q:
            return
        self.entry.delete("1.0", "end")
        self._write("Te", q, "user")
        self.send_btn.configure(state="disabled")
        self._run_bg(self._answer, q)

    def _answer(self, q: str) -> None:
        answer, self.last_id = self.brain.ask(q, self.history[-12:])
        self.history += [{"role": "user", "content": q}, {"role": "assistant", "content": answer}]
        self.ui.put(lambda: self._write("TecF Ai", answer, "ai"))
        self._refresh_status()

    def _rate(self, value: int) -> None:
        if self.last_id is None:
            return
        cid = self.last_id
        self._run_bg(lambda: (self.brain.kb.rate(cid, value),
                              self._log("Köszönöm, megjegyeztem." if value > 0 else
                                        "Rendben, ezt a témát újratanulom.")))

    def _learn_topic(self) -> None:
        topic = simpledialog.askstring("Tanulás", "Milyen témát tanuljak meg a netről?", parent=self.root)
        if topic:
            from tecf.learning import Learner
            self._run_bg(lambda: self._log(f"Kész: {Learner(self.brain).learn_topic(topic)} új forrás."))

    def _learn_loop(self) -> None:
        minutes = simpledialog.askinteger("Tanuló üzem", "Hány percig tanuljak?", initialvalue=30, minvalue=1,
                                          parent=self.root)
        if minutes:
            from tecf.learning import Learner
            self._run_bg(lambda: self._log(f"Tanuló üzem vége: {Learner(self.brain).learn_loop(minutes)} téma."))

    def _bootstrap(self) -> None:
        if messagebox.askyesno("Alaptudás", "Letöltsem az alaptudást a legjobb hiteles forrásokból?\n"
                                            "(hivatalos dokumentációk, RFC-k, Wikipedia – kb. 1-2 óra)"):
            from tecf.bootstrap import Bootstrapper
            self._run_bg(lambda: self._log(
                f"Alaptudás kész: {Bootstrapper(self.brain.kb, log=self._log).run()} új forrás."))

    def _ingest(self) -> None:
        path = filedialog.askdirectory(title="Mappa kiválasztása") or filedialog.askopenfilename(
            title="Vagy egy fájl")
        if path:
            from tecf.learning import Learner
            self._run_bg(lambda: self._log(f"{Learner(self.brain).ingest_path(path)} dokumentum felvéve."))

    def _own_model(self) -> None:
        """Saját nyelvi modell építése / továbbtanítása a háttérben (a beszélgetés közben is mehet)."""
        if getattr(self, "_model_stop", None) is not None:
            if messagebox.askyesno("Saját modell", "A tanítás fut. Leállítsam? (Az eddigi eredmény megmarad.)"):
                self._model_stop.set()
            return
        try:
            from tecf.llm import pipeline
        except ImportError:
            messagebox.showerror("Saját modell", "Hiányzik a PyTorch. Telepítsd újra a TecF Ai-t, "
                                                 "vagy: pip install -r requirements-train.txt")
            return
        mode = messagebox.askyesnocancel(
            "Saját modell",
            "Milyen saját modellt építsek?\n\n"
            "IGEN – alaptudással (AJÁNLOTT): egy kész, magyarul is tudó nyílt modellből (Qwen3) indul, "
            "és azt hangolja a tudásbázisodra és az értékelt beszélgetéseidre. Már az első futás után használható.\n\n"
            "NEM – a nulláról: teljesen saját, üres modell. Kísérleti, sok napnyi tanítás kell, mire értelmes lesz.")
        if mode is None:
            return
        hours = simpledialog.askfloat("Saját modell",
                                      "Hány órát tanuljon?\n(Újra indítva mindig tovább tanul.)",
                                      initialvalue=3 if mode else 8, minvalue=0.05, parent=self.root)
        if not hours:
            return
        self._model_stop = threading.Event()

        def work():
            try:
                if mode:
                    from tecf.llm.base import finetune
                    finetune(self.cfg, hours * 60, log=self._log, stop=self._model_stop)
                else:
                    pipeline.build(self.cfg, hours, log=self._log, stop=self._model_stop)
                pipeline.use(self.cfg, True)
                self.brain.cfg.local_provider = "tecf-sajat"
                self.brain.provider(refresh=True)
                self._log("🧬 A saját modell elkészült, és használatban van.")
                self._run_bg(self._refresh_status)
            except Exception as e:
                self._log(f"Saját modell hiba: {type(e).__name__}: {e}")
            finally:
                self._model_stop = None
        # külön szálon, zárolás nélkül: saját adatbázis-kapcsolatot használ
        threading.Thread(target=work, daemon=True).start()

    def _show_stats(self) -> None:
        stats = self.brain.kb.stats()
        self._log("Tudásbázis: " + ", ".join(f"{k}: {v}" for k, v in stats.items()))

    def _refresh_status(self) -> None:
        p = self.brain.provider()
        s = self.brain.kb.stats()
        text = (f"Modell: {p.label if p else 'nincs – offline tudásbázis mód'}   |   "
                f"Források: {s['források']}   Emlékek: {s['emlékek']}   Tanulandó: {s['tanulandó téma']}")
        self.ui.put(lambda: self.status.configure(text=text))

    def run(self) -> None:
        self.root.mainloop()


def main(cfg: Config | None = None) -> None:
    TecFApp(cfg or Config.load()).run()
