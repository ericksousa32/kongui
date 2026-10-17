# Alterações no código do Konsave (`konsave/`)

Este é o **único** documento que lista o que o KonGUI mudou dentro do pacote
`konsave/` do projeto original. Existe para que uma nova versão do Konsave possa
ser incorporada sem adivinhação: refaça as alterações abaixo, rode a lista de
verificação (§5) e pronto.

**Base das alterações:** Konsave com `konsave/__main__.py` no estado do commit
`5179e0f` deste repositório (antes de qualquer alteração de trava).
Toda linha alterada em arquivo original traz o marcador `KONGUI-PATCH(lock)`;
para achar tudo: `grep -rn "KONGUI-PATCH" konsave/ setup.py`.

## 1. Resumo

| Arquivo | Tipo | Tamanho | Motivo |
|---|---|---|---|
| `konsave/lock.py` | **novo** (só biblioteca padrão) | ~420 linhas | mecanismo da trava entre processos (`fcntl.flock`) |
| `konsave/__main__.py` | alterado | +56 / −8 linhas | a CLI passa a executar cada comando sob a trava |
| `setup.py` | alterado | 1 linha | `python_requires` de `>=3.6` para `>=3.9` |

Nenhum outro arquivo de `konsave/` foi tocado (`funcs.py`, `consts.py`,
`parse.py`, `conf_*.yaml` e `__init__.py` estão idênticos ao original). O
comportamento dos comandos não muda quando ninguém mais usa o Konsave; as únicas
diferenças visíveis estão em §4.

## 2. `konsave/lock.py` (arquivo novo)

Arquivo independente: não importa nada do Konsave nem do KonGUI. Em uma nova
versão do Konsave basta **copiá-lo de novo**. Interface usada pelo restante:

* `OperationLock(caminho).hold(modo, operation=, timeout=, cancel=, on_wait=)`
  (gerenciador de contexto; `modo` é `SHARED` ou `EXCLUSIVE`);
* `command_lock(konsave_dir, modo, operation)` (versão da linha de comando:
  espera com mensagem e termina com código de saída);
* `default_lock_path`, `timeout_from_environment`, `describe_holder`;
* exceções `LockError` ← `LockBusyError` ← `LockTimeoutError`,
  `LockCancelledError`, `LockUnavailableError`, `LockUsageError`.

Comportamento completo: [`CONCURRENCY.md`](CONCURRENCY.md).

## 3. `konsave/__main__.py`

Quatro mudanças, todas marcadas. O corpo de despacho (`if args.list: … elif …`)
**não foi reescrito**: apenas movido para `_run`, sem alteração além da leitura
da lista de perfis.

### 3.1 Imports

```diff
 from konsave.consts import (
     CONFIG_FILE,
+    KONSAVE_DIR,
+    PROFILES_DIR,
     VERSION,
-    length_of_lop,
-    list_of_profiles,
 )
 ...
+from konsave.lock import EXCLUSIVE, SHARED, command_lock  # KONGUI-PATCH(lock)
```

`list_of_profiles` e `length_of_lop` deixam de ser importados porque
`konsave.consts` os calcula **na importação do módulo**, antes de qualquer espera
pela trava (ficariam velhos). Veja 3.4.

### 3.2 Função nova `_lock_request(args)`

Devolve `(modo, operação)` do comando. Espelha a **mesma ordem** da cadeia
`if/elif` de `_run` (o primeiro que casa executa):

| Comando | Trava | Por quê |
|---|---|---|
| `--list` | compartilhada | só lê |
| `--save`, `--remove`, `--apply`, `--import-profile`, `--wipe` | exclusiva | alteram perfis ou arquivos do usuário |
| `--export-profile` | compartilhada | lê o perfil; grava fora dos dados do Konsave |
| `--version`, `--help`, sem argumentos | nenhuma | não tocam dados compartilhados |

> **Ao adaptar:** se uma versão nova do Konsave acrescentar um comando, inclua-o
> em `_lock_request` na posição equivalente da cadeia de `_run` e decida se ele
> lê (compartilhada) ou altera (exclusiva). Um comando que ficar sem trava
> funciona, mas deixa de ser protegido.

### 3.3 `main()`

* A criação de `conf.yaml` padrão agora acontece sob trava exclusiva, com uma
  segunda verificação `os.path.exists` dentro dela (dois processos na primeira
  execução não copiam o arquivo ao mesmo tempo). O corpo do `if/else` copiado é
  o original.
* Depois do `parse_args()`, o comando roda em
  `with command_lock(KONSAVE_DIR, modo, operação): _run(parser, args)`.

### 3.4 Função `_run(parser, args)`

Contém o que antes vinha depois de `args = parser.parse_args()` em `main()`,
**sem mudanças**, exceto pelas duas primeiras linhas:

```python
list_of_profiles = os.listdir(PROFILES_DIR)
length_of_lop = len(list_of_profiles)
```

Sem isso, um `--save nome` que esperou a trava decidiria "já existe / não existe"
com a lista lida antes da espera. Coberto por
`tests.test_locking.CliTests.test_a_waiting_save_does_not_overwrite_what_the_first_one_created`.

> **Ao adaptar:** se o original passar a calcular a lista de outra forma, mantenha
> a regra: **ler depois de obter a trava**.

## 4. Diferenças de comportamento visíveis na CLI

| Situação | Original | Com o patch |
|---|---|---|
| Nenhuma outra operação em andamento | — | idêntico |
| Outra operação em andamento | os dois rodam ao mesmo tempo | espera até 30 s com a mensagem `Konsave: another Konsave operation is running…; waiting up to 30 s (Ctrl+C to give up)...` (stderr) |
| Esperou e não conseguiu | — | `Konsave: … Nothing was changed.`, **código de saída 75** (o original sempre sai com 0, mesmo em erro) |
| Arquivo de trava inutilizável (pasta sem permissão etc.) | — | `Konsave: cannot open the lock file …`, código 1 |
| Ctrl+C durante a espera | — | código 130, nada alterado |
| Variável `KONSAVE_LOCK_TIMEOUT` | — | segundos de espera (`0` = não esperar; negativo ou `inf` = sem limite; padrão 30) |
| Pasta do Konsave | — | passa a conter `.kongui.lock` (arquivo vazio/pequeno, nunca apagado) |

## 5. Como adaptar a uma nova versão do Konsave

1. Traga o `konsave/` novo para o repositório (substituindo o atual).
2. Copie de volta `konsave/lock.py` (não existe no original).
3. Reaplique as alterações de §3 em `konsave/__main__.py` (`grep` pelo marcador
   mostra onde estavam). Se o `__main__.py` mudou muito, faça pelo conceito:
   *um comando = uma trava; a lista de perfis é lida depois da trava*.
4. Em `setup.py`, mantenha `python_requires=">=3.9"` (ou o que o Konsave novo exigir).
5. Confira se `konsave/funcs.py`/`consts.py` continuam com as mesmas funções que
   `kongui/core/engine.py` usa (`docs/INTEGRATION.md` §2). A trava do KonGUI **não**
   depende do `__main__`: ela envolve as chamadas em `kongui/core/` (ver
   [`CONCURRENCY.md`](CONCURRENCY.md) §3).
6. Rode a verificação:
   * `python -m unittest tests.test_locking tests.test_cli_runner tests.test_profile_service_integration`
     (processos reais; falha se a CLI ou o serviço deixarem de usar a trava);
   * `python -m unittest discover -s tests -t .` (suíte inteira, **como usuário comum**);
   * `git diff <versão-antiga> -- konsave/` deve mostrar só o que está neste documento.

## 6. Histórico

| Versão do KonGUI | Alteração |
|---|---|
| esta etapa | trava entre processos (`lock.py`, `__main__.py`, `setup.py`) |
