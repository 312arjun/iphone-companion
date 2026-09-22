"""
Startup smoke test.

Importing qt_main proves only that its module body parses - it never runs
Application.__init__, where the real wiring lives. A missing import inside
that constructor passed every earlier check and still blew up on launch.
This constructs the thing.

Results go to smoke_out.txt rather than stdout, because qt_main's
_init_logging() redirects stdout to the app log on import.

Run before any release: python smoke.py [dark|light]
"""
import os
import sys
import tempfile
import traceback

os.environ["QT_QPA_PLATFORM"] = "offscreen"
BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)

# Scratch preferences, set before prefs is imported. This script sets
# theme_mode to test both palettes, and without this it would overwrite the
# user's own choice every time it runs.
os.environ["ANCS_PREFS_PATH"] = os.path.join(
    tempfile.gettempdir(), "_ancs_smoke_prefs.json")

REPORT = os.path.join(BASE, "smoke_out.txt")
lines, failures = [], []


def say(text):
    lines.append(text)
    with open(REPORT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


try:
    import prefs
    import qt_main
    say("import qt_main .......... ok")
except Exception:
    say("import qt_main .......... FAILED\n" + traceback.format_exc())
    os._exit(1)

mode = sys.argv[1] if len(sys.argv) > 1 else "dark"
prefs.set("theme_mode", mode)
try:
    application = qt_main.Application()
    say("Application(%s) ........ ok" % mode)
    window = getattr(application, "dashboard", None)
    if window is None:
        failures.append("Application has no dashboard")
    else:
        for page in range(6):
            window.goto(page)
        window.grab()
        say("6 pages render .......... ok")
        import theme
        say("theme.MODE .............. %s" % theme.MODE)
except Exception as exc:
    failures.append("Application(%s): %s" % (mode, exc))
    say("Application(%s) ........ FAILED\n%s" % (mode, traceback.format_exc()))

say("")
say("FAILURES: %d" % len(failures))
for item in failures:
    say("  " + item)
# _exit, not sys.exit: the constructor starts BLE and Spotify threads that
# would otherwise keep the interpreter alive after the checks are done.
os._exit(1 if failures else 0)
