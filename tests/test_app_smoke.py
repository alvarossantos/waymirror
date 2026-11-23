import importlib, os, pytest

@pytest.mark.skipif(not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY'), reason='no display')
def test_app_module_imports():
    m = importlib.import_module('waymirror.app')
    assert hasattr(m, 'main_gui')


def test_cli_root_launches_gui_lazily(monkeypatch):
    import waymirror.cli as cli
    import waymirror.app as app

    calls = {}

    def fake_main_gui(argv=None):
        calls['argv'] = argv
        return 7

    monkeypatch.setattr(app, 'main_gui', fake_main_gui)
    rc = cli.main(['--backend', 'niri'])
    assert rc == 7
    assert calls['argv'] == ['--backend', 'niri']
