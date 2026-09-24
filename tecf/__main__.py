import sys
import traceback


def _report_crash() -> None:
    """Konzol nélküli indításnál (asztali ikon, pythonw) a hiba különben láthatatlan maradna:
    naplóba írja, és felugró ablakban megmutatja."""
    text = traceback.format_exc()
    log_path = None
    try:
        from tecf.config import default_home
        log_dir = default_home() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "hiba.log"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass
    msg = f"A TecF Ai nem tudott elindulni.\n\n{text[-1500:]}\n\nNapló: {log_path or '-'}"
    if sys.stderr is not None:
        print(msg, file=sys.stderr)
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, msg, "TecF Ai – hiba", 0x10)
        except Exception:
            pass


if __name__ == "__main__":
    try:
        from tecf.cli import main
        raise SystemExit(main())
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception:
        _report_crash()
        raise SystemExit(1)
