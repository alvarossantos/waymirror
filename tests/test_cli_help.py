import subprocess, sys

def test_help_exits_zero():
    r = subprocess.run([sys.executable, "-m", "waymirror", "--help"], capture_output=True, text=True)
    assert r.returncode == 0
    assert "start" in r.stdout and "stop" in r.stdout and "list" in r.stdout
