# Revelar janela do mirror após Start — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** fazer o Start em fullscreen ativar o workspace da janela do `wl-mirror` no monitor alvo, com falha de IPC tratada como aviso não-fatal.

**Architecture:** novo módulo puro `waymirror/reveal.py` consulta o IPC do compositor com runner injetável e devolve aviso opcional. `MirrorManager` recebe um `revealer` injetável e o chama após o spawn bem-sucedido, apenas em `mode=fullscreen`.

**Tech Stack:** Python 3.14, pytest, IPC JSON de niri/umbriel.

**Spec:** `docs/superpowers/specs/2026-11-24-revelar-janela-mirror.md`

## Global Constraints
- Não alterar `build_wl_mirror_cmd`.
- Nenhuma falha de revelação pode abortar o Start ou alterar o estado salvo.
- Toda execução de comando passa por runner injetável; sem `subprocess` direto no módulo.
- `mode=window` nunca chama o revelador.
- Aviso é `str | None`; `None` significa sucesso.

## Review Focus
- Janela ainda não mapeada no primeiro instante → aguardar com sleep injetável antes de desistir.
- PID ausente no JSON → fallback por `app_id=at.yrlf.wl_mirror` sem confundir outra janela.
- Janela em saída diferente do alvo → mover antes de ativar workspace.
- JSON inválido / binário ausente → aviso, sem exceção para o chamador.
- `workspace` da janela ausente → escolher workspace ativo do alvo via JSON de workspaces.

---

### Task 1: módulo `reveal`

**Files:**
- Create: `waymirror/reveal.py`
- Test: `tests/test_reveal.py`

**Interfaces:**
- Produces: `find_mirror_window(backend: str, pid: int, run: RunFunc) -> dict[str, Any] | None`, `reveal_mirror_window(backend: str, pid: int, target: str, run: RunFunc | None = None, sleep: SleepFunc | None = None, attempts: int = 10) -> str | None`.
- `dict` da janela contém ao menos `id: str`, `output: str`, `workspace: str`.

- [ ] **Step 1: escrever teste de localização por PID e fallback por app_id**

`tests/test_reveal.py` com fake `run` devolvendo JSON de `umbriel windows --json`: duas janelas, uma com `pid` diferente e `app_id=at.yrlf.wl_mirror`, outra com `pid=4242`, `id=w-1`, `output=eDP-2`, `workspace=eDP-2:11`. Afirmar que `find_mirror_window("umbriel", 4242, run)["id"] == "w-1"`; com `pid=999`, afirmar fallback para a janela `at.yrlf.wl_mirror`.

- [ ] **Step 2: rodar o teste e verificar falha**

Run: `.venv/bin/python -m pytest tests/test_reveal.py -q`
Expected: FAIL (módulo não existe).

- [ ] **Step 3: implementar `find_mirror_window` e `reveal_mirror_window`**

`find_mirror_window` aceita payload lista ou `{"windows": [...]}`. `reveal_mirror_window` tenta `attempts` vezes com `sleep(0.1)`; se `output != target`, emite comandos de focus + move do backend; em seguida emite o comando de ativação do workspace (o da janela, ou o ativo do alvo). Exceções e JSON inválido viram string de aviso.

- [ ] **Step 4: escrever testes de comportamento**

No mesmo arquivo: (a) janela já no alvo → somente comando de ativação do workspace da janela, retorno `None`; (b) janela em outra saída → comandos de focus/move/switch nessa ordem; (c) `run` levantando `OSError` → retorno contém `"warn"`; (d) nenhuma janela após `attempts=2` → retorno contém `"not found"`.

- [ ] **Step 5: rodar testes e verificar verde**

Run: `.venv/bin/python -m pytest tests/test_reveal.py -q`
Expected: PASS.

- [ ] **Step 6: commit**

```bash
git add waymirror/reveal.py tests/test_reveal.py
git commit -m "feat: localiza e revela janela do wl-mirror via IPC"
```

### Task 2: integrar ao `MirrorManager`

**Files:**
- Modify: `waymirror/mirror.py:147-163` (`__init__`), `waymirror/mirror.py:286-320` (`_start_locked`)
- Test: `tests/test_mirror.py`

**Interfaces:**
- Consumes: `reveal_mirror_window` e tipo `Revealer = Callable[[str, int, str], str | None]` de Task 1.
- Produces: `MirrorManager(..., revealer: Revealer | None = None)`; `StartResult.warning` concatena aviso de stale e aviso de revelação.

- [ ] **Step 1: escrever teste de integração**

Em `tests/test_mirror.py`: manager com `runner` falso que devolve pid `4242`, `revealer` falso registrando chamadas. Afirmar que `start(..., mode="fullscreen")` chama `revealer("umbriel", 4242, "eDP-2")` e que o aviso dele aparece em `result.warning`; com `mode="window"`, afirmar que `revealer` não é chamado.

- [ ] **Step 2: rodar o teste e verificar falha**

Run: `.venv/bin/python -m pytest tests/test_mirror.py -q`
Expected: FAIL (`TypeError: unexpected keyword 'revealer'`).

- [ ] **Step 3: implementar a injeção e a chamada pós-spawn**

Adicionar parâmetro `revealer` ao `__init__` com default `lambda backend, pid, target: reveal_mirror_window(backend, pid, target)`. Em `_start_locked`, após `state_store.save(session)`, chamar o revelador somente se `mode == "fullscreen"`; juntar avisos com `"; "`.

- [ ] **Step 4: rodar suíte completa**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (todos os testes existentes + novos).

- [ ] **Step 5: commit**

```bash
git add waymirror/mirror.py tests/test_mirror.py
git commit -m "feat: revela janela do mirror no start fullscreen"
```

### Task 3: validação real e documentação

**Files:**
- Modify: `README.md` (seção de limitações)
- Test: nenhum (validação manual)

**Interfaces:**
- Consumes: `MirrorManager` de Task 2.

- [ ] **Step 1: teste manual na sessão ao vivo**

Com o app instalado via repo (`python3 -m waymirror`), iniciar `Source=HDMI-A-1`, `Mode=Fullscreen`, `Target=eDP-2`. Verificar `umbriel windows --json`: janela `at.yrlf.wl_mirror` em `output=eDP-2`, `visible=true`, workspace ativo.

- [ ] **Step 2: documentar comportamento**

Adicionar parágrafo curto no README: em niri/umbriel o app ativa o workspace da janela do mirror após o Start; se o IPC falhar, o espelhamento continua ativo e um aviso é exibido.

- [ ] **Step 3: commit**

```bash
git add README.md
git commit -m "docs: descreve revelação da janela do mirror"
```
