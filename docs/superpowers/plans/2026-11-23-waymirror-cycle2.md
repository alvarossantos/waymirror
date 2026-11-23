# Waymirror Cycle 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validar o v0.1.0 como pacote Arch instalado e adicionar espelhamento de janela por região `wl-mirror -r`, mantendo compatibilidade com CLI/estado atuais.

**Architecture:** Task 1 é um gate de verificação fora do repo (PKGBUILD em `~/pkgbuilds/waymirror`, smoke na sessão umbriel ao vivo). Tasks 2-7 adicionam um segundo `SourceKind` (`window`) sem overloading de `MirrorMode`: backends descobrem janelas, CLI resolve ID→região, MirrorManager passa `-r` ao wl-mirror, GUI oferece seletor de kind e previews `grim -g`. Todo estado antigo continua carregando com defaults.

**Tech Stack:** Python 3.11+, GTK4/libadwaita via PyGObject, wl-mirror 0.18.5 (`-r` em formato slurp), grim 1.5.0 (`-g`), pytest, makepkg/pip.

**Spec:** `docs/superpowers/specs/2026-11-23-cycle2-design.md`

## Global Constraints

- v1.1 cobre **niri e umbriel**; sem portal/pipewire, sem Hyprland, sem múltiplas sessões.
- IDs canônicos de janela = `Window.id` do compositor (string); `source` no estado é esse ID, nunca a região.
- Formato de região do wl-mirror: exatamente `"x,y WxH output"` (um argv element); grim: `"x,y WxH"`.
- Exit codes inalterados: `0` sucesso, `2` uso, `3` backend, `4` saída/janela não encontrada, `5` execução.
- Uma sessão ativa; `stop` sinaliza apenas o PID registrado; sem `pkill`, sem `--force`, sem sudo no app.
- `detect_backend()` continua sondando só `list_outputs()`; backend sinalizado e inutilizável = `NoBackendError`, sem cross-fallback.
- `MirrorMode = Literal["window","fullscreen"]` significa **apresentação**, não tipo de fonte.
- Comando de output existente não muda: `wl-mirror <source>` / `wl-mirror --fullscreen-output <target> <source>`.
- Sem follow automático de geometria: mover/redimensionar janela exige `stop` + `start`.

## Review Focus

- Estado antigo sem `source_kind`/`region` → continua válido; teste `test_session_from_dict_legacy_keys` (Task 2).
- ID de janela não pode ser validado como output → `OutputNotFoundError` (exit 4) quando inexistente; teste `test_window_source_not_validated_as_output` (Task 4).
- Coordenadas negativas e `WxH` preservadas byte a byte na região; teste `test_window_region_helpers` (Task 2).
- Janela minimizada/invisível recusada no start (exit 2) e sinalizada na lista; teste `test_start_rejects_hidden_window` (Task 4).
- `niri msg --json windows` com shape desconhecido não derruba detecção; teste `test_parse_niri_windows_unknown_shape` (Task 3).
- Falha em `list_windows()` na GUI é não fatal (banner inline); teste `test_gui_window_discovery_failure_nonfatal` (Task 6).

---

### Task 1: PKGBUILD + smoke no sistema vivo

**Files:**
- Create: `~/pkgbuilds/waymirror/PKGBUILD`
- Create: `~/pkgbuilds/waymirror/.SRCINFO`
- Test: verificação manual (sem pytest; sistema não tem `python-pytest`)

**Interfaces:**
- Consumes: release `v0.1.0` (tarball GitHub, sha256 `492cfa0a5ddf01daf9176193e8ddb8b92277555159cfb885eaffce556c70d78c`).
- Produces: pacote `waymirror-0.1.0-1-any.pkg.tar.zst` instalado; evidência de GUI funcionando.

- [ ] **Step 1: Escrever `PKGBUILD`**

`pkgname=waymirror`, `pkgver=0.1.0`, `pkgrel=1`, `pkgdesc`, `arch=('any')`, `url=https://github.com/alvarossantos/waymirror`, `license=('MIT')`, `depends=('python' 'gtk4' 'libadwaita' 'python-gobject' 'grim' 'wl-mirror')`, `optdepends=('niri: backend niri' 'umbriel: backend umbriel')`, `makedepends=('python-pip')`, `source=("waymirror-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")`, `sha256sums=(...)`.
`package()`: `python -m pip install --root="$pkgdir" --prefix=/usr --no-deps --no-compile --break-system-packages "$srcdir/waymirror-$pkgver"`; `install -Dm644 "$srcdir/waymirror-$pkgver/resources/io.github.alvaro.waymirror.desktop" "$pkgdir/usr/share/applications/io.github.alvaro.waymirror.desktop"`.

- [ ] **Step 2: Gerar `.SRCINFO` e validar**

Run: `cd ~/pkgbuilds/waymirror && makepkg --printsrcinfo > .SRCINFO && makepkg -s`
Expected: `.pkg.tar.zst` gerado; sem erros de dependência, sem sudo.

- [ ] **Step 3: Instalar (aprovação explícita)**

Propor ao usuário: `sudo pacman -U ~/pkgbuilds/waymirror/waymirror-0.1.0-1-any.pkg.tar.zst`
Expected: pacote instalado; `waymirror --version` → `waymirror 0.1.0`.

- [ ] **Step 4: Smoke CLI e GUI na sessão viva**

Run (um por bloco): `waymirror --help`; `waymirror list`; `waymirror list --json`; `waymirror status`; `waymirror start --source eDP-2 --mode fullscreen --target HDMI-A-1`; `waymirror status`; `waymirror stop`; `waymirror toggle ...`; abrir GUI (`waymirror &`) e capturar tela com `grim -o eDP-2 /tmp/opencode/waymirror-gui.png`.
Expected: exit 0 em todos; GUI visível com cards e previews; nenhum `wl-mirror` órfão após `stop` (`pgrep -a wl-mirror` vazio).
Nota: se `start` falhar por WL backend, registrar erro exato e ajustar **somente** o pacote, não o código v1.1.

- [ ] **Step 5: Registrar evidência**

Escrever `~/pkgbuilds/waymirror/SMOKE.md` com comandos, exit codes e caminho do screenshot. Sem commit (artefato fora do repo).

### Task 2: Window model + source_kind compatível

**Files:**
- Modify: `waymirror/models.py:8,15-116`
- Test: `tests/test_models_state.py`

**Interfaces:**
- Consumes: nada (base).
- Produces: `SourceKind`, `Window`, `MirrorSession.source_kind`, `MirrorSession.region`, `Window.wl_mirror_region()`, `Window.grim_region()`, `Window.is_capturable()`.

- [ ] **Step 1: Testes falhando em `tests/test_models_state.py`**

`test_window_region_helpers`: `Window(id="abc", x=-1903, y=59, w=1689, h=1004, output="HDMI-A-1")` → `wl_mirror_region() == "-1903,59 1689x1004 HDMI-A-1"`, `grim_region() == "-1903,59 1689x1004"`.
`test_window_is_capturable`: `visible=True, minimized=False, w>0,h>0` → True; `minimized=True` → False; `w=0` → False.
`test_session_from_dict_legacy_keys`: dict v1 sem `source_kind`/`region` → `session.source_kind == "output"`, `session.region is None`.
`test_session_roundtrip_window_kind`: `to_dict()`/`from_dict()` preservam `source_kind="window"` e `region="10,20 300x200 HDMI-A-1"`.
`test_same_config_window_kind`: IDs iguais, kinds diferentes → False; mesmo ID/kind mas `region` diferente → False; `region=None` nos dois → compara só kind.

- [ ] **Step 2: Rodar e confirmar FAIL**

Run: `.venv/bin/python -m pytest tests/test_models_state.py -q`
Expected: FAIL (símbolos ausentes).

- [ ] **Step 3: Implementar em `waymirror/models.py`**

Adicionar `SourceKind = Literal["output","window"]`; dataclass `Window` com `id: str`, defaults `app_id/title/output=""`, `x/y/w/h: int=0`, `visible: bool=True`, `minimized: bool=False`, `to_dict`/`from_dict` (campos desconhecidos ignorados), e os três helpers acima.
Em `MirrorSession`, adicionar **após** `started_at`: `source_kind: SourceKind = "output"`, `region: str | None = None`. `to_dict()` emite as duas chaves; `from_dict()` usa `_get(data, "source_kind", "output")` (validar contra `("output","window")`) e `_get(data, "region", None)` convertendo para `str` quando não nulo; `same_config(..., source_kind: SourceKind="output", region: str|None=None)` compara `self.source_kind == source_kind` e, quando `self.source_kind == "window"` e ambos `region` não nulos, também `self.region == region`.

- [ ] **Step 4: Testes passando + suíte**

Run: `.venv/bin/python -m pytest tests/test_models_state.py -q && .venv/bin/python -m pytest -q`
Expected: PASS; 104 testes antigos intactos.

- [ ] **Step 5: Commit**

`git commit -am "feat(models): add window source kind with legacy state defaults"`

### Task 3: Backend window discovery

**Files:**
- Modify: `waymirror/backends/base.py:24-27`, `waymirror/backends/umbriel.py`, `waymirror/backends/niri.py`, `waymirror/backends/__init__.py`
- Create: `tests/fixtures/umbriel_windows.json`, `tests/fixtures/niri_windows.json`
- Test: `tests/test_backends.py`

**Interfaces:**
- Consumes: `Window.from_dict` (Task 2); `_as_int`/`_as_float` helpers existentes nos parsers.
- Produces: `Backend.list_windows() -> list[Window]`; `parse_umbriel_windows(payload) -> list[Window]`; `parse_niri_windows(payload) -> list[Window]`.

- [ ] **Step 1: Fixtures e testes falhando**

Fixture umbriel: lista com 2 janelas, uma com `x=-1903`, `minimized=false`, `visible=true`, `app_id="firefox"`, `output="HDMI-A-1"`. Fixture niri: wrapper `{"windows": [...]}` com `id`, `geometry` aninhada (`x,y,width,height`) — formato **hipotético**, o parser deve tolerar chaves alternativas.
Testes: `test_parse_umbriel_windows_fixture`; `test_parse_niri_windows_nested_geometry`; `test_parse_niri_windows_unknown_shape` (payload `{"unexpected": 1}` → `[]`, sem exceção); `test_list_windows_implemented_by_backends` (ambos os backends expõem método e chamam o runner certo: `umbriel windows --json`, `niri msg --json windows`).

- [ ] **Step 2: Rodar e confirmar FAIL**

Run: `.venv/bin/python -m pytest tests/test_backends.py -q`

- [ ] **Step 3: Implementar parsers e método**

`Backend` Protocol ganha `list_windows()`. Em cada backend: `list_windows()` executa o comando via runner existente (mesma estratégia de `list_outputs`), tolera stdout vazio/JSON inválido devolvendo `[]` e registrando warning não fatal; conversão de `id` para `str`, `x/y/w/h` via `_as_int` **sem default 0 quando a chave existe mas é inválida** (descartar janela com geometry incompleta). Aceitar `w/h` ou `width/height`, `app_id`/`app-id`, `output` no topo ou dentro de `geometry`. Reexportar `Window` em `backends/__init__.py`.

- [ ] **Step 4: Testes passando + suíte** (como Task 2)

- [ ] **Step 5: Commit**

`git commit -am "feat(backends): discover windows from umbriel and niri"`

### Task 4: MirrorManager + CLI com janela

**Files:**
- Modify: `waymirror/mirror.py:77-84,161-306`, `waymirror/cli.py:50-76,115-136,153-224,275-278`
- Test: `tests/test_mirror.py`, `tests/test_cli_commands.py`

**Interfaces:**
- Consumes: `Window`, `SourceKind` (Task 2); `Backend.list_windows()` (Task 3).
- Produces: `build_wl_mirror_cmd(..., source_kind="output", region=None)`; `MirrorManager.start/toggle(..., source_kind=..., available_windows=...)`; CLI `--window <id>`, `list windows`.

- [ ] **Step 1: Testes falhando**

`test_build_cmd_window_region`: `source_kind="window", region="10,20 300x200 HDMI-A-1", mode="window"` → `["wl-mirror","-r","10,20 300x200 HDMI-A-1"]`; `mode="fullscreen", target="eDP-2"` → `["wl-mirror","--fullscreen-output","eDP-2","-r","10,20 300x200 HDMI-A-1"]`.
`test_build_cmd_output_unchanged`: chamada antiga produz exatamente os comandos atuais.
`test_window_source_not_validated_as_output`: `start(..., source="abc", source_kind="window", available_windows=[Window(id="abc",...)], available_outputs=["eDP-2","HDMI-A-1"])` → `action="started"`, runner recebe `-r`.
`test_window_missing_exit_4`: ID inexistente → `OutputNotFoundError`; via CLI → exit `4`.
`test_start_rejects_hidden_window`: `minimized=True` → `MirrorValidationError` (CLI `2`).
`test_fullscreen_window_target`: `target == window.output` → `MirrorValidationError`.
`test_cli_list_windows_json`: `list windows --json` → `{"backend": ..., "windows": [...]}`; `list --json` permanece com chave `outputs`.
`test_cli_window_flag_xor`: `start --source x --window abc` e nenhum dos dois → exit `2`.
`test_status_json_window_session`: sessão com `source_kind="window"` aparece no JSON.

- [ ] **Step 2: Rodar e confirmar FAIL**

Run: `.venv/bin/python -m pytest tests/test_mirror.py tests/test_cli_commands.py -q`

- [ ] **Step 3: Implementar executor**

`build_wl_mirror_cmd(source, mode, target, *, source_kind="output", region=None)`: para `source_kind=="window"`, exigir `region` não vazio (`MirrorValidationError`); montar argv com `-r` **antes** do source ausente (janela não tem positional output). Para `source_kind=="output"`, manter os dois retornos atuais byte a byte.
`MirrorManager.start/toggle` ganham keyword-only `source_kind: SourceKind="output"`, `available_windows: list[Window] | None=None`; passar adiante para `_start_locked`/`_toggle_locked` (sem nested lock). Novo `_validate_request(...)`: se `source_kind=="window"`, procurar ID em `available_windows`; inexistente → `OutputNotFoundError`; `not is_capturable()` → `MirrorValidationError`; resolver `region = window.wl_mirror_region()`; em fullscreen validar `target` contra `available_outputs` e contra `window.output` (igual → erro); caso contrário delegar ao `_validate_outputs` atual. `MirrorSession` criado com `source_kind` e `region`; `same_config` recebe ambos.

- [ ] **Step 4: Implementar CLI**

`p_list.add_argument("kind", nargs="?", choices=["outputs","windows"], default="outputs")`; `_cmd_list` faz branch para `windows` com `_emit(_json_dump({"backend": ..., "windows": [w.to_dict() ...]}))` e texto `id\tapp_id\ttitle\tWxH+x,y\t[output]`. Em `start`/`toggle`: trocar `--source` por opcional, adicionar `--window` (dest `window_id`), validar XOR em `main()` → `_usage_error`. `_resolve_start_args(args, backend)` devolve `(source, source_kind, available_windows)`: se `--window`, usa `backend.list_windows()` e o ID; senão mantém `args.source`/`available_outputs`. Passar `source_kind` e `available_windows` ao manager; `--mode` e `--target` intactos. `_format_session` já serialize o novo campo via `to_dict()`.

- [ ] **Step 5: Testes passando + suíte + commit**

Run: `.venv/bin/python -m pytest -q`
`git commit -am "feat(cli): window source via --window and list windows"`

### Task 5: Preview de janela

**Files:**
- Modify: `waymirror/preview.py:29-31,59-100`
- Test: `tests/test_preview.py`

**Interfaces:**
- Consumes: `Window.grim_region()` (Task 2).
- Produces: `capture_grim_region_cmd(region: str, path: str) -> list[str]`; `PreviewManager.capture(key, *, region: str | None = None)`.

- [ ] **Step 1: Testes falhando**

`test_capture_grim_region_cmd`: `["grim","-g","10,20 300x200","/tmp/p.png"]`.
`test_capture_window_key`: `preview.capture("window:abc", region="10,20 300x200")` chama runner com o cmd `-g`, grava `previews/window_abc.png` (via `_safe_name`) e limpa erro; sem `region`, chama `capture_grim_cmd` normal.
`test_capture_region_failure_is_nonfatal`: runner retorna `returncode=1` → `None`, `errors["window:abc"]` preenchido, nenhuma exceção.

- [ ] **Step 2: Rodar e confirmar FAIL** — `.venv/bin/python -m pytest tests/test_preview.py -q`

- [ ] **Step 3: Implementar**

Adicionar `capture_grim_region_cmd`. Em `capture(key, *, region=None)`: escolher cmd; quando `region` é dado, usar `grim -g`; todo o restante (tmp atômico, `os.replace`, limpeza, `errors`) permanece idêntico e indexado por `key`. `preview_path("window:abc")` continua funcionando via `_safe_name`.

- [ ] **Step 4: Testes passando + suíte + commit**

`git commit -am "feat(preview): capture window region with grim -g"`

### Task 6: GUI — seletor de fonte e cards de janela

**Files:**
- Modify: `waymirror/app.py:12-16,65-124,127-230,251-307,325-434`
- Test: `tests/test_app_banner.py`

**Interfaces:**
- Consumes: `Backend.list_windows()` (Task 3), `SourceKind`/`Window` (Task 2), `PreviewManager.capture(..., region=...)` (Task 5), `MirrorManager.start(..., source_kind=..., available_windows=...)` (Task 4).
- Produces: `WaymirrorWindow._selected_kind()`, `_selected_window()`, `_load_sources()`, `_window_region_for_preview()`.

- [ ] **Step 1: Testes falhando (fake widgets do harness existente)**

`test_kind_dropdown_switches_source_list`: selecionar "Window" popula `source_model` com `app_id — title` e `flow` com cards de janela; voltar a "Output" restaura cards de saída.
`test_gui_window_discovery_failure_nonfatal`: backend fake cujo `list_windows()` lança → `outputs` e cards intactos, banner mostra mensagem, nenhuma exceção.
`test_start_passes_window_source`: kind=Window, janela selecionada, mode=window → `mirror_manager.start` chamado com `source_kind="window"`, `available_windows=[...]`; region do manager no session.
`test_preview_uses_region_for_window`: com sessão ativa `source_kind="window", region=...`, worker chama `preview_manager.capture("window:<id>", region="...")`.

- [ ] **Step 2: Rodar e confirmar FAIL** — `.venv/bin/python -m pytest tests/test_app_banner.py -q`

- [ ] **Step 3: Implementar GUI**

Importar `SourceKind`/`Window`. Adicionar `self.kind_dropdown` (`["Output","Window"]`) ao `controls` antes de Source; `self.windows: list[Window]=[]`, `self.window_error: str|None=None`. `_load_outputs()` passa a chamar `self._load_sources()`: outputs como hoje (fatal → banner), janelas em `try/except` separado (não fatal). `_rebuild_outputs_ui()` escolhe a lista ativa pelo kind: source/target models e cards (janelas mostram `app_id`/`title`/`WxH`); target dropdown continua sempre com outputs. `_selected_kind()`, `_selected_window()` e `_selected_source()` indexam a lista ativa. `_on_start_stop()`: para kind=window, checar seleção e capturabilidade, pasar `source_kind`/`available_windows`; para kind=output, manter fluxo atual. `_schedule_preview_refresh()`: capturar outputs e, se houver janela ativa/selecionada, `preview_manager.capture("window:"+id, region=<region da sessão ativa ou da janela>)`; `_apply_preview_results` usa `self.cards` com o mesmo namespace.

- [ ] **Step 4: Testes passando + suíte + commit**

`git commit -am "feat(gui): window source selector and region previews"`

### Task 7: Documentação, limitações e fechamento

**Files:**
- Modify: `README.md`, `docs/superpowers/specs/2026-11-22-waymirror-design.md` (marcar janela como entregue via `-r`, com limitações), `tests/test_desktop_and_readme.py`
- Test: suíte completa + revisão de branch

**Interfaces:**
- Consumes: Tasks 1-6.
- Produces: branch pronta para PR; ledger de decisões.

- [ ] **Step 1: Atualizar README**

Documentar `waymirror list windows`, `start --window <id> --mode window|fullscreen`, oclusão (região captura pixels da tela, janela coberta/minimizada não é isolada), drift (mover/redimensionar exige restart), `--target` não pode ser o output da janela em fullscreen. Ajustar a seção de limites que hoje diz "sem janelas".

- [ ] **Step 2: Atualizar asserções de docs nos testes**

`tests/test_desktop_and_readme.py` deve verificar os novos snippets sem perder os antigos.

- [ ] **Step 3: Verificação final**

Run: `.venv/bin/python -m pytest -q` (esperado: todos passam), `.venv/bin/python -m waymirror --help`, `desktop-file-validate resources/io.github.alvaro.waymirror.desktop`.
Se a sessão ainda estiver viva, repetir smoke de `list windows --json` e `start --window <id>` com captura de tela.

- [ ] **Step 4: Commit + revisão de branch**

`git commit -am "docs: document window mirroring limits"`; gerar pacote de review da base da branch e despachar revisão final. Corrigir findings em uma única fix wave; adjudicar residuais com `Ruling:` no ledger.

- [ ] **Step 5: Handoff**

Registrar no ledger: abordagem região+tracking, limitações aceitas, decisões de compatibilidade de estado. Apresentar opções de merge/PR — **sem push automático**.
