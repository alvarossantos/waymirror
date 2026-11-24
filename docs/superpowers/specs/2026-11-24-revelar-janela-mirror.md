# Revelar janela do mirror após Start

## Contexto
Com `Mode=Fullscreen`, `wl-mirror --fullscreen-output <target> <source>` roda
corretamente, mas no niri/umbriel a janela `at.yrlf.wl_mirror` pode abrir em
outro workspace (no caso observado, `HDMI-A-1:5` quando o alvo era `eDP-2`).
`waymirror status` fica ativo, porém nada aparece no monitor alvo.

## Root cause
O Wayland `set_fullscreen(output)` é atendido de forma ambígua pelo compositor:
a janela é criada, marcada como fullscreen, mas em workspace não ativo (e,
em alguns estados, na saída de origem). O app não verifica a posição real da
janela após o spawn.

## Solução
Módulo `waymirror/reveal.py`, não-fatil, chamado por `MirrorManager` logo após
o `Popen` bem-sucedido, somente em `mode=fullscreen`:

1. Consultar janelas do compositor via IPC e localizar a janela do `wl-mirror`
   pelo PID da sessão (fallback: `app_id=at.yrlf.wl_mirror`).
2. Se `output != target`: focar a janela e movê-la para um workspace do alvo.
3. Ativar o workspace final da janela no alvo.
4. Retornar string de aviso em caso de falha; nunca abortar o Start.

Comandos (todos injetáveis para teste):

| Ação | umbriel | niri |
|---|---|---|
| listar janelas | `umbriel windows --json` | `niri msg --json windows` |
| listar workspaces | `umbriel workspaces --json` | `niri msg --json workspaces` |
| focar janela | `umbriel msg window-focus <id>` | `niri msg action focus-window --id <id>` |
| mover p/ workspace | `umbriel msg window-move-to-workspace <ws> --output <out>` | `niri msg action move-column-to-monitor <out>` |
| ativar workspace | `umbriel msg workspace-switch <ws> --output <out>` | `niri msg action focus-workspace <ref>` |

## Fora de escopo
- follow de geometria, portal/pipewire, captura isolada de janela oculta.
- alterar `build_wl_mirror_cmd`: o comando do `wl-mirror` permanece o mesmo.
- matar processos do compositor ou mudar config do usuário.

## Critério de aceite
- [ ] Start em fullscreen revela o mirror no monitor alvo.
- [ ] Start em `Mode=Window` não chama o revelador.
- [ ] Falha de IPC (binário ausente, JSON inválido, janela não encontrada)
      apenas adiciona aviso ao `StartResult`.
- [ ] Testes com runner/injetores falsos; suíte verde.
- [ ] Issue → PR → tag → pacote atualizado.
