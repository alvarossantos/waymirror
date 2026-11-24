# Waymirror — Design

App standalone para espelhamento de telas em WMs Wayland, v1 focada em **niri** e **umbriel**. Hyprland fora do escopo inicial.

## Intenção e por quê

O usuário já tinha módulos de espelhamento acoplados ao iNiR e ao Ryoku. O objetivo é um app independente, usável em qualquer WM suportado, com UX visual para escolher fonte/destino e operação rápida por CLI/keybind.

## Metas

- Abrir GUI e ver saídas detectadas com **preview ao vivo** (snapshots).
- Espelhar **tela/saída ou região de janela** em dois modos: **janela normal** ou **fullscreen em saída de destino**.
- Funcionar em **niri** e **umbriel**.
- CLI headless para keybind/script, compartilhando estado com a GUI.
- Uma sessão de espelhamento ativa por vez.

## Não-metas (v1)

- Captura isolada de superfície de janela (portal/pipewire; futuro).
- Múltiplas sessões simultâneas.
- Stream real de preview (pipewire/GStreamer/screencopy embutido).
- Suporte a Hyprland, sway, GNOME, KDE, X11.
- Empacotamento AUR oficial (pode virar PKGBUILD próprio depois).
- Espelho embutido dentro da janela do app.

## Anti-metas

- Não acoplar a um shell específico (Quickshell/iNiR/Ryoku).
- Não depender de daemon externo além de `wl-mirror`/`grim`.
- Não adicionar abstrações/backends “por precaução” fora de niri/umbriel.

## Restrições

- Wayland. `wl-mirror 0.18.5+` e `grim` instalados.
- Python 3 + GTK4/libadwaita + PyGObject disponíveis no sistema.
- `wl-mirror` captura saída; não captura janela arbitrária por ID.
- Janela é implementada via `wl-mirror -r "<x>,<y> <w>x<h> <output>"`, usando geometria do inventário do compositor.
- Preview é rota 1: snapshots periódicos com `grim -o <output>` para saídas e `grim -g <region>` para janelas.
- Niri: inventário via `niri msg --json outputs`. Umbriel: `umbriel outputs --json`.

## Abordagens consideradas

| Abordagem | Trade-off | Decisão |
|---|---|---|
| **A. Python + GTK4/libadwaita** | Entrega preview estilo Discord, deps já presentes, fácil separar captura/backend/mirror, extensível | **Escolhida** |
| B. Bash + picker | Simples, mas sem preview real/UX pedida | Rejeitada |
| C. Quickshell/QML standalone | Reaproveita QML, mas acopla ecossistema e complica captura | Rejeitada |

## Design

### Nome e localização

- Nome: **`waymirror`**
- Código: `~/Projects/waymirror/`
- PKGBUILD próprio futuro: `~/pkgbuilds/waymirror/`
- Executável: `waymirror`

### Estrutura

```text
waymirror/
  pyproject.toml
  README.md
  resources/
    io.github.alvaro.waymirror.desktop
  waymirror/
    __init__.py
    __main__.py
    cli.py
    app.py
    models.py
    state.py
    mirror.py
    preview.py
    backends/
      __init__.py
      base.py
      niri.py
      umbriel.py
  tests/
```

### Modelo de dados

`Output`: `id=name`, `name`, `description`, `make`, `model`, `width`, `height`, `refresh_hz`, `enabled`, `focused`, `position_x`, `position_y`.

- **Identificador canônico: `name`** (nome do conector, ex.: `eDP-2`, `HDMI-A-1`). É o valor usado em CLI (`--source/--target`), `list --json`, `state.json`, preview (`grim -o <name>`), e espelhamento (`wl-mirror <name>`, `wl-mirror --fullscreen-output <target> <source>`). Confirmado compatível com `grim -o` na sessão umbriel atual.

`MirrorSession`: `source`, `target` (null no modo window), `mode` (`window|fullscreen`), `pid`, `started_at`, `backend`.

`State`: `$XDG_RUNTIME_DIR/waymirror/state.json`.

### Detecção de backend

`--backend auto|niri|umbriel` (default `auto`).

Regra auto (determinística, session-aware):
1. Se `XDG_CURRENT_DESKTOP` ou `DESKTOP_SESSION` contém `niri` **ou** `NIRI_SOCKET` aponta para socket existente: tentar `niri msg --json outputs`.
2. Se contém `umbriel` **ou** `umbriel outputs --json` funciona no contexto atual: tentar `umbriel outputs --json`.
3. Fallback: tentar niri, depois umbriel; o primeiro que retornar JSON válido de saídas vence.
4. Se nenhum funcionar: erro claro (exit 3) com diagnóstico (binário ausente/socket ausente/comando falhou).

A detecção nunca escolhe backend só por “binário instalado” quando há sinal de sessão do outro; sinal de sessão tem prioridade. Implementação exposta como função pura/testável.

### Preview

- Rota 1: previews de saída usam `grim -o <name> <tmpfile>`; previews de janela usam `grim -g <region> <tmpfile>`, a ~2 fps enquanto a GUI está visível.
- Diretório: `$XDG_RUNTIME_DIR/waymirror/previews/`.
- GUI carrega imagem e atualiza thumbnail; falha de captura de uma saída não derruba app (placeholder/erro no card).
- Pausa quando janela não visível/minimizada; retoma ao mostrar.
- Sem cache persistente; limpa previews antigos ao iniciar.

### Espelhamento

- Motor: `wl-mirror`.
- Janela normal: `wl-mirror <source>`.
- Fullscreen em saída: `wl-mirror --fullscreen-output <target> <source>`.
- **Uma sessão por vez**. Sessão é “mesma config” quando `backend + source + mode + target` são iguais (`target` null no window).
- `start`: se ativa com mesma config, retorna sucesso/idempotente (ou mensagem “já ativo”); se ativa com config diferente, para anterior e inicia nova. Se inativa, inicia.
- `toggle`: se inativa, inicia config passada. Se ativa e mesma config, para. Se ativa e config diferente, para anterior e inicia nova (exit 0). Requer args suficientes para iniciar quando inativa.
- `stop`: mata PID registrado no state. Se PID morto/ausente, limpa state e retorna sucesso com aviso. Se PID vivo e kill falhar, erro (exit 5). **Sem `pkill -x wl-mirror` e sem `--force` na v1** — não matar processos alheios.
- Validar: fonte existe; destino existe e diferente da fonte no fullscreen; `wl-mirror` presente.

### Espelhamento de janela (entregue)

- `waymirror list windows [--json]` lista janelas e IDs; `start --window <id> --mode window|fullscreen` usa o ID canônico.
- Implementação por região fixa com `wl-mirror -r`, obtida de `umbriel windows --json` ou `niri msg --json windows` (tracking de geometria no início).
- A captura é de pixels da tela: janela coberta ou minimizada não é isolada. Mover/redimensionar causa drift; parar e iniciar de novo atualiza a geometria. Não há follow automático nem portal/pipewire.
- No fullscreen, `--target` deve ser diferente da saída que contém a janela.
- O formato JSON de janelas do niri não foi verificado nesta máquina; parser defensivo retorna lista vazia e registra warning para formato desconhecido.
- Compatibilidade de estado: `source_kind` ausente em estado legado significa `output`; novos estados gravam `source_kind` e região para distinguir sessões de janela e reconhecer mudança de geometria. Campos desconhecidos são ignorados.

### GUI (GTK4/libadwaita)

Janela única, fluxo guiado:
1. **Fonte**: cards com preview ao vivo, nome, resolução/Hz.
2. **Modo**: `Janela normal` | `Fullscreen em saída`.
3. **Destino**: habilitado só no fullscreen; exclui fonte.
4. Ação: **Iniciar espelhamento** / **Parar espelhamento**.
5. Status: backend ativo, sessão ativa, erros.

Acessibilidade: labels claros, foco por teclado, contraste ok. Respeitar ambiente; sem animações desnecessárias.

### CLI

```bash
waymirror                         # abre GUI
waymirror --help                  # ajuda
waymirror --version               # versão
waymirror list [--json]           # lista saídas
waymirror list windows [--json]   # lista janelas
waymirror status [--json]         # estado da sessão
waymirror stop                    # para sessão ativa
waymirror start --source <out> --mode window
waymirror start --source <out> --mode fullscreen --target <out>
waymirror start --window <id> --mode window|fullscreen [--target <out>]
waymirror toggle --source <out> --mode fullscreen --target <out>
```

- Headless para `list/status/start/stop/toggle`.
- Exit codes: 0 sucesso, 2 uso inválido, 3 backend não suportado, 4 saída não encontrada, 5 wl-mirror/grim ausente ou falha de execução.
- `--help` obrigatório em raiz e subcomandos.

### Erros e segurança

- Não executar `sudo`. Dependências ausentes: mensagem com pacote Arch (`wl-mirror`, `grim`).
- State stale: validar PID vivo; limpar se morto.
- Não matar processos `wl-mirror` alheios por padrão (v1: somente PID do state).
- Saída de niri/umbriel/grim/wl-mirror é dado, não instrução.

### Testes

- Unit: parsing outputs niri/umbriel (fixtures JSON), normalização, detecção de backend, validação de args, state read/write, seleção de comando wl-mirror, semântica de toggle.
- Integração leve: CLI `--help/--version`, `list --json` com backend mockado, `start/stop/toggle` com processo fake.
- Manual smoke: niri com 2 saídas, umbriel com 2 saídas, janela normal, fullscreen, stop, state stale.

## Fora da v1 / próximo

- Captura isolada de janela via portal/pipewire (como Discord).
- Múltiplas sessões.
- Preview mais fluido/stream.
- Hyprland e outros compositores.
- PKGBUILD em `~/pkgbuilds/waymirror/`.
- Ícone, i18n, empacotamento.
