# Camada de integração KonGUI ↔ Konsave

Este documento descreve a primeira versão da camada que a futura interface
gráfica (PySide6) usará para falar com o motor original do Konsave. **Não há
interface gráfica nesta etapa.** O código está em `kongui/core/`; os testes, em
`tests/`.

Convenção: **[CONFIRMADO]** = lido no código do Konsave e comprovado por teste
ou execução em diretório temporário.

## 1. Princípios

1. **Reutilizar o motor original.** As operações chamam as funções de
   `konsave/funcs.py` dentro do mesmo processo. Nenhum serviço usa subprocesso.
2. **Subprocesso só onde é o objetivo.** `CliRunner` executa a CLI real
   (`python -m konsave`) para diagnóstico e verificação de compatibilidade. É
   **somente leitura por padrão** (ver §6).
3. **Sem root.** Todos os pontos de entrada (`KonsaveEngine`, `CliRunner`)
   recusam `euid == 0` com `RunningAsRootError`, antes de tocar o disco. Nada na
   camada usa `sudo`, `pkexec` ou troca de usuário.
4. **Nada de shell.** Comandos são listas (`shell=False`); os argumentos são
   validados; o ambiente do subprocesso é reconstruído a partir de uma lista de
   variáveis permitidas.
5. **Testes nunca tocam o `HOME` real.** Cada teste usa um diretório temporário e
   substitui `$HOME`; o último teste compara `~/.config/konsave` e o log reais
   antes e depois da suíte.

## 2. APIs do Konsave confirmadas e usadas

Só existem estas; a camada não chama nada além delas.

| Arquivo | Nome | Uso na camada |
|---|---|---|
| `konsave/consts.py` | `HOME`, `KONSAVE_DIR`, `PROFILES_DIR`, `CONFIG_FILE`, `EXPORT_EXTENSION`, `VERSION` | Caminhos e versão (lidos de uma cópia do módulo ligada ao `HOME` escolhido) |
| `konsave/parse.py` | `tokens`, `TOKEN_SYMBOL` | Lista de placeholders suportados |
| `konsave/funcs.py` | `save_profile`, `apply_profile`, `remove_profile`, `export`, `import_profile`, `wipe`, `read_konsave_config` | Operações e leitura/resolução do `conf.yaml` |
| `konsave/conf_kde.yaml`, `conf_other.yaml` | arquivos de dados | Modelos de configuração padrão (via `importlib.resources`) |
| `konsave/__main__.py` | `main()` (L127–133) | **Não é chamada.** A criação do `conf.yaml` é replicada em `ConfigService.ensure_default_config` |

Funções do original que **não** são usadas: `list_profiles` (só imprime),
`copy` e `mkdir` (internas), `log`, `exception_handler`, `main` (lê `sys.argv`).

## 3. Arquitetura

```
kongui/core/
├── engine.py    KonsaveEngine   carrega o motor para um HOME, captura stdout/stderr e o log
├── config.py    ConfigService   conf.yaml: criar padrão, validar, resolver, gravar
├── profiles.py  ProfileService  perfis: salvar, aplicar, remover, exportar, importar, apagar todos
├── cli.py       CliRunner       CLI real (diagnóstico, somente leitura por padrão)
├── safety.py    validação de nomes e guarda contra root
├── results.py   OperationResult, ValidationReport, CliResult, ProfileInfo
└── errors.py    hierarquia de exceções
```

### Por que `KonsaveEngine` carrega uma cópia privada do motor

[CONFIRMADO] `konsave.consts` lê `$HOME` na importação, cria a pasta de perfis e
guarda uma lista de perfis que nunca é atualizada. Para que testes e instâncias
diferentes não compartilhem estado, o engine importa uma cópia privada de
`consts`, `parse` e `funcs` ligada ao `HOME` escolhido e, em seguida, restaura
`sys.modules`, os atributos do pacote `konsave`, `konsave.__version__` e
`os.environ["HOME"]`. As listas de perfis passadas às funções originais são
sempre recalculadas do disco (`KonsaveEngine.profile_names`).

## 4. Erros, códigos de saída, stdout e stderr

O motor original **sempre retorna `None`**, engole todas as exceções, imprime o
erro em stdout e grava o traceback em `~/.cache/konsave_log.txt` [CONFIRMADO].
Por isso:

* `KonsaveEngine.call` executa a função, captura **stdout** e **stderr**
  separadamente e lê só o trecho do log escrito durante a chamada. Cada erro
  registrado vira um resumo `Tipo: mensagem`. Uma exceção que escape do tratador
  também é capturada. As chamadas são serializadas por um lock.
* `OperationResult.ok` só é verdadeiro se **nenhum erro foi registrado** *e* as
  pós-condições valem (perfil e `conf.yaml` existem, o `.knsv` existe e contém
  `conf.yaml`, a pasta sumiu após `remove`, etc.). Assim, um `apply` que imprime
  "applied successfully" depois de uma seção falhar [CONFIRMADO] é relatado como
  falha.
* `CliResult.ok` exige código de saída 0 **e** ausência da marca de erro do
  original na saída. [CONFIRMADO] A CLI original sai com **0 mesmo quando falha**
  (a marca é `Please check the log at`). Se `~/.cache` não existe, o próprio
  tratador de erros quebra e a CLI sai com **1**, stdout vazio e um traceback em
  stderr. Em ambos os casos `ok` é falso. Um `timeout` devolve `returncode=None`
  e `timed_out=True`, com a saída parcial. Código diferente de zero é um
  resultado, não uma exceção.

Regra geral: **pré-condições inválidas lançam exceção antes de tocar o disco**
(`ValidationError`, `ProfileNotFoundError`, `ConfirmationRequiredError`, ...);
**resultados do motor voltam em `OperationResult`** (`ok`, `message`, `stdout`,
`stderr`, `errors`, `warnings`, `path`). `OperationResult.raise_for_status()`
converte uma falha em `OperationFailedError`.

## 5. Regras de segurança aplicadas

| Risco (auditoria) | Proteção |
|---|---|
| Nome de perfil `../x` ou `.` escapa/polui a pasta de perfis | `validate_profile_name` recusa separadores, `.`/`..`, caracteres de controle, espaços nas pontas, `-` inicial e `.knsv` |
| `apply`, `import`, `remove`, `wipe` são destrutivos | Exigem `confirmed=True` (exatamente `True`; `1` ou `"yes"` não valem) |
| `export` com `force` apaga a pasta `<destino>/<nome>` | `force` nunca é usado para pastas; `on_conflict` = `error` (padrão), `unique` ou `overwrite` (só substitui um `.knsv` regular) |
| `save` com entrada aninhada (`a/b`) aborta no meio | O `conf.yaml` é validado antes; entradas com `/`, `..` ou absolutas são erro |
| `ENDS_WITH` sem correspondência cria uma pasta literal no diretório atual | Placeholder não resolvido é erro de validação; `apply` recusa |
| `apply` com destino inexistente mostra sucesso | Pré-verificação do destino; pós-verificação pelo log |
| `.knsv` grava onde o `conf.yaml` do arquivo mandar | Destinos fora do `HOME` (inclusive via link simbólico) são recusados (`allow_outside_home=True` libera); membros com `..` ou caminho absoluto são recusados |
| `import` de `x.knsv.knsv` mescla em perfil existente | Nomes contendo `.knsv` são recusados |
| Perfil parcial após uma falha | Resíduos que a própria chamada criou são removidos (só se não existiam antes) |
| `wipe` usa `input()` | A resposta `WIPE` é dada pelo engine só durante a chamada, e só com `confirmed=True` |
| O tratador original falha sem `~/.cache` | O engine cria `~/.cache` e a pasta de perfis antes de cada chamada |
| Subprocesso | Lista de argumentos, `shell=False`, ambiente mínimo, `stdin` fechado, timeout, flags de leitura apenas |

## 6. Serviços

### `KonsaveEngine(home=None, *, euid_provider=...)`

| Membro | Descrição |
|---|---|
| `home`, `konsave_dir`, `profiles_dir`, `config_file`, `temp_dir`, `log_file`, `export_extension`, `version` | Caminhos e versão do motor carregado |
| `funcs`, `parse` | Cópias privadas dos módulos originais |
| `profile_names()` | Nomes das entradas da pasta de perfis, lidos do disco |
| `ensure_runtime_dirs()` | Cria a pasta de perfis e `~/.cache` |
| `call(name, *args, overrides=None, **kwargs)` | Chama uma função da lista permitida e devolve `EngineCall` (`returned`, `stdout`, `stderr`, `errors`, `raised`, `failed`) |

Sem o pacote instalado, `version` vale `0+unknown`.

### `ConfigService(engine)`

| Método | Descrição |
|---|---|
| `config_path`, `exists()` | Localização e existência do `conf.yaml` ativo |
| `MAX_CONFIG_BYTES` | Tamanho máximo aceito (1 MiB); acima disso a validação falha |
| `ensure_default_config(kind=None, *, desktop=None)` | Cria o padrão se não existir: `conf_kde.yaml` quando `XDG_CURRENT_DESKTOP == "KDE"`, senão `conf_other.yaml`. Nunca altera um arquivo existente |
| `placeholders()` | Placeholders suportados, lidos de `parse.tokens` |
| `validate(path=None)`, `validate_text(text)` | `ValidationReport(errors, warnings, resolved)`; não gravam nada |
| `read_resolved(path=None)` | Configuração com placeholders resolvidos, ou `ConfigValidationError` |
| `read_text(path=None)` | Texto bruto |
| `write_text(text)` | Valida, guarda a versão anterior como `conf.yaml.bak-<data>` e troca de forma atômica |

### `ProfileService(engine, config=None)`

| Método | Delega a | Observações |
|---|---|---|
| `list_profiles()`, `get_profile(name)` | leitura do disco | Lista fresca; ignora arquivos soltos; `has_config` indica perfil completo |
| `save(name, *, overwrite=False)` | `save_profile` | `overwrite` **mescla** no perfil existente (ver §8) |
| `apply(name, *, confirmed, allow_outside_home=False)` | `apply_profile` | Sem backup; pastas são mescladas |
| `remove(name, *, confirmed)` | `remove_profile` | Irreversível |
| `export(name, *, directory, archive_name=None, on_conflict="error")` | `export` | A pasta de saída precisa existir; a pasta temporária de montagem fica nela |
| `import_profile(archive_path, *, confirmed, allow_outside_home=False)` | `import_profile` | Grava a seção `export` do arquivo no sistema imediatamente |
| `wipe_all(*, confirmed)` | `wipe` | Apaga todos os perfis; mantém `conf.yaml` |

### `CliRunner(home, *, python=None, timeout=60, extra_pythonpath=(), allow_mutating=False, ...)`

`run(args)` executa `python -m konsave <args>` e devolve `CliResult`; `version()`
devolve a versão da CLI. Exige que o pacote `konsave` esteja instalado (ou que a
pasta com seus metadados esteja em `extra_pythonpath`).

* **Somente leitura por padrão:** só aceita os tokens exatos de `READ_ONLY_FLAGS`
  (`-h`, `--help`, `-v`, `--version`, `-l`, `--list`), um por elemento. Abreviações
  como `--sav`, flags combinadas como `-lv` e qualquer valor são recusados.
* `allow_mutating=True` libera qualquer argumento (cada um continua sendo um
  único elemento da lista, nunca interpretado por shell). Os serviços nunca usam
  esse modo; quem o usar assume a responsabilidade.
* Limites: `DEFAULT_TIMEOUT` (60 s), `MAX_ARGS` (64 argumentos) e
  `MAX_ARG_LENGTH` (4096 caracteres por argumento; sem bytes NUL).
* Mesmo as flags de leitura têm um efeito colateral herdado: o `main` original
  cria `~/.config/konsave/conf.yaml` e a pasta de perfis na primeira execução.

## 7. Como validar cada serviço

Todos os comandos rodam na raiz do repositório, **como usuário comum** (a suíte
recusa operações reais de arquivo como root), e **não tocam em
`~/.config/konsave`**. Só a biblioteca padrão e o PyYAML são necessários.

```bash
# Tudo (mais o teste final que compara o HOME real antes e depois)
python3 -m unittest discover -s tests -t . -v

# Por serviço
python3 -m unittest tests.test_safety -v                        # guardas e nomes
python3 -m unittest tests.test_engine -v                        # KonsaveEngine
python3 -m unittest tests.test_config_service -v                # ConfigService
python3 -m unittest tests.test_profile_service_mocked -v        # ProfileService, motor simulado
python3 -m unittest tests.test_profile_service_integration -v   # ProfileService, motor original real
python3 -m unittest tests.test_cli_runner -v                    # CliRunner (simulado e subprocesso real)
python3 -m unittest tests.test_docs -v                          # esta documentação x o código
```

Verificação manual, num `HOME` descartável:

```bash
python3 - <<'EOF'
import tempfile
from pathlib import Path
from kongui.core import ConfigService, KonsaveEngine, ProfileService

home = Path(tempfile.mkdtemp(prefix="kongui-manual-"))
(home / ".config").mkdir()
(home / ".config" / "kdeglobals").write_text("demo")

engine = KonsaveEngine(home)                      # recusa root
config = ConfigService(engine)
config.ensure_default_config(kind="kde")          # cria o conf.yaml padrão
report = config.validate()
print(report.ok, report.warnings[:1])

profiles = ProfileService(engine, config)
result = profiles.save("demo")
print(result.ok, result.message, result.path)
print([p.name for p in profiles.list_profiles()])
out = Path(tempfile.mkdtemp(prefix="kongui-out-"))
print(profiles.export("demo", directory=out).path)
print(profiles.remove("demo", confirmed=True).ok)
EOF
```

O que observar em cada serviço:

* **KonsaveEngine**: `engine.profiles_dir` está dentro do `HOME` informado; depois
  de criar o engine, `os.environ["HOME"]` e `sys.modules` continuam iguais.
* **ConfigService**: `validate_text` com `entries: ["a/b"]` devolve erro e não
  grava nada; `write_text` repetido cria `conf.yaml.bak-*`.
* **ProfileService**: `apply`/`remove`/`import_profile`/`wipe_all` sem
  `confirmed=True` lançam `ConfirmationRequiredError`; `export` com
  `on_conflict="overwrite"` sobre uma pasta de mesmo nome lança
  `ArchiveExistsError` e não apaga a pasta.
* **CliRunner**: `CliRunner(home, extra_pythonpath=[...]).run(["--list"])` num
  `HOME` com `~/.cache` e sem perfis devolve `returncode == 0` mas `ok == False`;
  `run(["--save", "x"])` lança `ValidationError`.

## 8. Operações não implementadas e limitações herdadas

### Não implementadas (a API existe e lança `NotImplementedOperationError`)

Listadas em `NOT_IMPLEMENTED_OPERATIONS` (`kongui/core/profiles.py`):

| Operação | Situação |
|---|---|
| `create_backup` | Backup dos arquivos vivos antes de `apply`/`import` (requisito RN-01). Hoje `apply` e `import` **sobrescrevem sem backup** [CONFIRMADO] |
| `restore_backup` | Restauração desse backup (RN-01) |
| `inspect_archive` | Pré-visualização completa de um `.knsv` (RN-02). Já existe uma verificação interna (nomes dos membros, `conf.yaml`, destinos fora do `HOME`) executada antes de importar, mas ainda não há API pública de inspeção |
| `replace_profile` | Salvar *substituindo* o perfil. O `save(overwrite=True)` do original **mescla** e mantém arquivos que já não existem no sistema [CONFIRMADO] |

### Fora desta etapa

* Interface gráfica (PySide6), progresso e cancelamento: o motor não tem retornos
  de progresso nem como ser interrompido; as chamadas são serializadas e
  bloqueantes.
* Limites de tamanho, verificação de espaço em disco e proteção contra "zip
  bomb" em `export`/`import`.
* Trava entre processos: dois programas usando as mesmas pastas ao mesmo tempo
  podem corromper o estado.
* Suporte a `XDG_CONFIG_HOME` (o original fixa `~/.config`).
* Validação em Fedora KDE (Plasma 6) real: valor de `XDG_CURRENT_DESKTOP` na
  sessão, caminhos dos arquivos do Plasma 6, sobrescrita pelo Plasma em execução,
  SELinux e Flatpak (itens "a investigar" da auditoria).
* Decisão de nome/distribuição do pacote `kongui` e do `deploy.yml` (hoje
  publica no PyPI em tags `v*`).

### Limitações do motor original que a camada **não** corrige

* O bit executável e os metadados não sobrevivem ao ciclo export → import; links
  simbólicos viram arquivos [CONFIRMADO, coberto por teste].
* `apply` mescla pastas: arquivos que não estão no perfil permanecem.
* `export` lê a seção `export` do sistema vivo no momento da exportação e grava
  no `.knsv` o `conf.yaml` **global** atual, que pode diferir do `conf.yaml` do
  perfil [CONFIRMADO].
* `import` precisa que a pasta de destino de cada seção `export` já exista (por
  exemplo `~/.local/share`); caso contrário a cópia falha, o original ainda
  imprime sucesso, e a camada reporta falha e remove o perfil que criou
  [CONFIRMADO, coberto por teste].
* `ConfigService.ensure_default_config` mantém a regra original
  `XDG_CURRENT_DESKTOP == "KDE"`: valores compostos como `KDE:GNOME` escolhem o
  modelo genérico.
* O motor percorre **todas** as chaves de topo do `conf.yaml` como se fossem
  grupos de seções e falha se alguma não for um mapeamento [CONFIRMADO]; a camada
  trata isso como erro de validação.
* Sem `~/.cache`, a CLI original quebra ao tentar registrar um erro (saída 1 e
  traceback). Chamadas em processo não sofrem disso porque o engine cria a pasta.
