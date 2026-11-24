# Waymirror — ciclo 2: PKGBUILD + espelhamento de janela

Status: proposto (aguarda aprovação)

## Contexto
v0.1.0 publicado em `alvarossantos/waymirror` (MIT, release `v0.1.0`, 104 testes).
Objetivo do usuário: (1) ver o app funcionando como pacote instalado, (2) evoluir
para espelhamento de janelas. Sessão atual: umbriel (`wayland-0`); `wl-mirror
0.18.5` e `grim 1.5.0` instalados. `wl-mirror` não tem `-w/--window` — apenas
`<output>` e `-r/--region` (formato slurp `'x,y WxH [output]'`).

## Decisões aprovadas no brainstorming
- PKGBUILD: build via `python -m pip install --root` (pip 26.2.2 já presente; zero
  makedepends novos). Validado em root temporário: gera `/usr/bin/waymirror` e
  `site-packages/waymirror/`.
- Janela: **região + tracking no start**. Sem portal/pipewire. Oclusão é
  limitação documentada, não bug a corrigir neste ciclo.

## Frente 1 — PKGBUILD e verificação (faz primeiro)
- Novo pacote em `~/pkgbuilds/waymirror/`: `PKGBUILD` + `.SRCINFO`.
- `source`: tarball do tag `v0.1.0`; sha256 `492cfa0a5ddf01daf9176193e8ddb8b92277555159cfb885eaffce556c70d78c`.
- `pkgname=waymirror`, `pkgver=0.1.0`, `pkgrel=1`, `arch=('any')`, `license=('MIT')`.
- `depends`: `python gtk4 libadwaita python-gobject grim wl-mirror`.
  `optdepends`: `niri` e `umbriel` (detecção session-aware já existe).
- `package()`: pip com `--root="$pkgdir" --prefix=/usr --no-deps --no-compile
  --break-system-packages`; `install -Dm644` do `.desktop` do tarball.
- Sem `check()`: `pytest` não existe no Python de sistema. Suíte continua rodando
  no `.venv` do repo (104 testes, como já feito).
- Build: `makepkg -s` (sem sudo). Instalação: `sudo pacman -U <pkg>.pkg.tar.zst`
  — **requer aprovação explícita**.
- Smoke obrigatório: `waymirror --help`, `list`, `list --json`, `status`,
  `start`/`stop`/`toggle` com saída real, abrir GUI e capturar tela com `grim`
  para conferir visualmente.
- Após smoke: corrigir apenas o que o pacote revelar (ex.: entry point, paths).

## Frente 2 — janela como região (feature, branch própria)
### Modelo e estado
- `SourceKind = Literal["output", "window"]` em `models.py`.
- `MirrorSession.source_kind: SourceKind = "output"` **depois** de `started_at`
  para não quebrar construtores posicionais existentes; `region: str | None = None`
  logo depois, guardando a região resolvida no start (diagnóstico em `status` e
  detecção de janela movida no restart).
- `from_dict` usa `_get(..., "output")`: estado antigo sem a chave continua válido.
- `same_config(..., source_kind="output")` compara o novo campo; `to_dict()`
  passa a emiti-lo. `source` continua sendo o **ID canônico da janela**, nunca a
  região formatada.

### Backends
- `Backend` (Protocol) ganha `list_windows() -> list[Window]`; `Window` com
  `id, app_id, title, x, y, w, h, output, visible, minimized`.
- Umbriel: parser defensivo de `umbriel windows --json` (campos confirmados:
  `id/x/y/w/h/output/visible/minimized/app_id/title`).
- Niri: parser defensivo de `niri msg --json windows` (formato **não verificado**
  nesta máquina); se o shape não casar, lista vazia + aviso não fatal — nunca
  derrubar a detecção de backend.
- `detect_backend()` continua sondando só `list_outputs()`; regra "backend
  sinalizado inutilizável = hard fail" permanece.

### CLI (adições, sem quebrar o atual)
- `list windows [--json]` → `{"backend": ..., "windows": [...]}`; payload atual
  de `list` inalterado.
- `start`/`toggle`: `--window <id>` mutuamente exclusivo com `--source`;
  nenhum dos dois → erro de uso (exit 2). `--mode` inalterado
  (`window`/`fullscreen` = como apresentar).
- Janela não encontrada → exit 4 (reusa `OutputNotFoundError` ou subclasse).

### Execução e preview
- `build_wl_mirror_cmd(..., source_kind, region)`:
  - janela + modo window: `wl-mirror -r 'x,y WxH <output>'`
  - janela + fullscreen: `wl-mirror --fullscreen-output <target> -r 'x,y WxH <output>'`
  - output: comandos atuais, byte a byte.
- Região é **um único argumento argv**; `Popen` sem shell.
- Validação: `source` de janela não é validado contra outputs; `target` é
  comparado ao **output da janela**, não ao ID.
- Preview: `grim -g 'x,y WxH'` com chave `window:<id>` (evita colisão com nomes
  de conector). Região resolvida no start; **sem follow automático** neste ciclo:
  mover/redimensionar a janela exige `stop` + `start`. Documentar no README.

### GUI
- Seletor "Fonte: Saída | Janela" junto aos dropdowns atuais.
- Lista de janelas com `app_id`/`title` quando Janela selecionado; cards e
  preview usam o namespace `window:<id>`.
- Falha ao listar janelas é não fatal (banner inline), como já é no app.

### Testes
- `tests/test_backends.py`: fixtures de janelas umbriel/niri + parser defensivo.
- `tests/test_models_state.py`: roundtrip com `source_kind` e estado legado.
- `tests/test_mirror.py` / `test_mirror_concurrency.py`: builder com `-r`,
  validação de target por output da janela, chamadas posicionais antigas.
- `tests/test_cli_commands.py`: `--window`, `list windows`, exits 2/4.
- `tests/test_preview.py`: `grim -g` e chave `window:<id>`.
- `tests/test_app_banner.py`: troca de kind e fallback de janelas.
- README atualizado (limites de oclusão/drift); ajustar asserções de
  `tests/test_desktop_and_readme.py`.

## Fora de escopo deste ciclo
- Portal screencast/pipewire, captura isolada de janela, follow automático de
  geometria, Hyprland, múltiplas sessões simultâneas.

## Riscos conhecidos
- Oclusão: `-r` captura pixels da tela; janela coberta/minimizada produz o que
  estiver por cima. `visible/minimized` filtram apenas a lista.
- Coordenadas negativas (output à esquerda/acima da origem) devem ser
  preservadas — `_as_int` com default 0 corrompe geometry ausente.
- README e spec v1 dizem explicitamente "sem janelas"; ambos precisam mudar.
- niri: `niri msg --json windows` ainda não foi observado nesta máquina.
