import io
import subprocess
import sys


def test_cli_survives_legacy_console_encoding():
    """Імітація Windows-консолі з cp1252: українські повідомлення не повинні давати UnicodeEncodeError."""
    code = ("import io,sys; sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding='cp1252'); "
            "from paint_by_numbers.cli import _utf8_console; _utf8_console(); print('шрифт з кирилицею'); "
            "sys.stdout.flush(); print('OK', file=sys.stderr)")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0 and "OK" in r.stderr, r.stderr
