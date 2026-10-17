# Editor do `conf.yaml`

A página **Configuração do Konsave** (`config`, `Ctrl+4`) edita
`~/.config/konsave/conf.yaml`: as seções `save` e `export` separadamente (nomes
dos grupos, pastas de origem, itens, placeholders) e o texto inteiro, sempre
validando com o código original do Konsave antes de gravar.

## 1. Auditoria: o que o arquivo é e como o Konsave o lê

Fontes: `konsave/funcs.py` (`read_konsave_config`), `konsave/parse.py`,
`konsave/conf_kde.yaml`, `konsave/conf_other.yaml`, o `conf.yaml` do
`tests/profile_test.knsv` (Plasma 6 real) e sondagens executadas contra o código
original (os casos estão em `tests.test_config_editor.OriginalBehaviourTests`).

### Estrutura

```yaml
---
save:                      # vai para dentro do perfil
    <grupo>:               # nome do grupo = nome da pasta dentro do perfil
        location: "..."    # pasta de origem, com placeholders
        entries:           # nomes simples de arquivos ou pastas dentro de location
            - nome
export:                    # só viaja no .knsv
    <grupo>: { location: ..., entries: [...] }
...
```

* Raiz com `save` e `export`, **as duas obrigatórias**; cada uma é um mapa de
  grupos. `save:` vazio (valor nulo) faz o Konsave quebrar; `save: {}` é o certo.
* Cada grupo tem `location` (texto) e `entries` (lista). `entries:` vazio ou
  `null` vira lista vazia ao ler (`read_konsave_config`).
* O arquivo real é cheio de comentários (inclusive exemplos comentados) e termina
  com `...`. Os grupos do `tests/profile_test.knsv` são `save.configs` (29 itens),
  `save.app_layouts`, `export.share_folder` e `export.home_folder`.
* O motor percorre **todas** as chaves da raiz como se fossem grupos de seções
  (`parse_keywords`/`parse_functions`). Uma chave desconhecida precisa, então,
  ser um mapa de grupos; do contrário o Konsave falha (`TypeError`). A validação
  aceita chaves desconhecidas válidas (com aviso) e recusa as que quebrariam.

### Onde o `conf.yaml` é usado

| Operação | Que arquivo lê |
|---|---|
| `save` | o `conf.yaml` **global** (`save`); copia-o para dentro do perfil |
| `apply` | o `conf.yaml` **do perfil** (`save`) |
| `export` | o `conf.yaml` do perfil (`export`); grava no `.knsv` uma cópia do **global** |
| `import` | o `conf.yaml` do arquivo; guarda-o no novo perfil |

Editar o arquivo global, portanto, vale para os **próximos** salvamentos e
exportações; perfis já salvos mantêm a cópia que tinham.

### Placeholders (todos conferidos no código original)

Só valem em `location`, nunca em `entries`.

| Texto | Comportamento real |
|---|---|
| `$HOME`, `$CONFIG_DIR`, `$SHARE_DIR`, `$BIN_DIR` | substituição simples de texto; a barra final é mantida (`"$HOME/"` → `/home/u/`) |
| `${ENDS_WITH='x'}`, `${BEGINS_WITH='x'}` (aspas simples ou duplas) | troca **todo o caminho** pela primeira pasta do diretório pai cujo nome termina/começa com `x`. O argumento não pode ter espaços (`\S+`). Com duas ou mais pastas candidatas, vale a primeira na ordem de listagem do sistema de arquivos |
| `$KONSAVE_DIR` | **citado no `conf_other.yaml`, mas não existe** no código: fica literal. O editor não o oferece e o recusa |
| função sem pasta correspondente | o Konsave **não falha**: devolve o texto literal `${FUNC='x'}` como `location` e segue (o grupo é silenciosamente inútil). A validação recusa |
| função cujo diretório pai não existe | o Konsave falha com `FileNotFoundError` (a validação mostra “O Konsave não conseguiu interpretar o arquivo”) |
| duas funções no mesmo `location` | só a última age; sobra texto literal. A validação recusa |
| `$NOPE`, `${FOO='x'}` | ficam literais; a validação recusa antes |
| `~/x`, caminho relativo | não são expandidos; a validação recusa (precisa ser absoluto) |

A lista de placeholders exibida na interface é lida de `parse.tokens` do próprio
Konsave (`ConfigService.placeholders()`); a **interpretação** nunca é refeita
aqui: o texto é entregue a `read_konsave_config` e o resultado é o que a
interface mostra em “O Konsave resolve esta pasta como…”.

## 2. Como a edição preserva o arquivo

`yaml.safe_dump` descartaria os comentários, e o `ruamel.yaml` (que os preserva)
não está instalado nem faz parte das dependências. A edição, então, é **textual e
cirúrgica** (`kongui/core/confedit.py`):

1. o texto é lido pelo próprio PyYAML (o mesmo do Konsave) e as posições exatas de
   cada grupo, chave e item são obtidas do analisador (`kongui/core/yamlmap.py`);
2. uma edição do formulário vira poucas substituições, inserções e remoções de
   linhas: renomear um grupo troca só o nome, mudar `location` troca só esse
   valor, acrescentar um item insere uma linha, remover apaga a linha;
3. todo o resto (comentários, linhas em branco, chaves desconhecidas, placeholders
   que ninguém tocou, o `...` final, a indentação do usuário) fica **byte a byte**
   como estava; um formulário lido e escrito de volta sem mudanças devolve o texto
   idêntico (testado com o `conf.yaml` real);
4. o resultado é relido com `yaml.safe_load` e comparado com o que se pretendia.
   Se algo diferir, ou se o layout for exótico (por exemplo `save: {a: {...}}` em
   estilo de fluxo), o texto é regenerado a partir dos dados: **chaves
   desconhecidas e placeholders continuam, os comentários se perdem**, e a
   interface avisa e pede confirmação antes de salvar.

Seção `save:`/`export:` nula é corrigida para `{}`. Reordenar itens não existe
na interface, e a ordem dos grupos é a do arquivo (novos vão para o fim).

## 3. Fluxo da página

* **Abas**: *Seção save*, *Seção export* (lista de grupos, nome, pasta de origem
  com botões de placeholder, itens com adicionar/remover/editar) e *Texto (YAML)*.
  As três mostram o mesmo texto; editar numa atualiza as outras. Se o texto do
  YAML estiver quebrado, as abas de seção ficam indisponíveis até corrigi-lo.
* **Validação contínua**: a cada edição o texto é validado em segundo plano pelo
  `ConfigService.validate_text` (leitor original). O painel de problemas lista
  erros e avisos com **linha, coluna, caminho** (`save.configs.entries[3]`) e a
  explicação em pt-BR; **Ir para** abre o campo certo (ou a linha, no texto).
* **Salvar** só habilita com a verificação do texto atual concluída e **sem
  erros**. O serviço valida de novo e recusa se houver erro, mesmo que a interface
  seja contornada: nada é gravado e nenhum backup é feito.
* **Backup**: antes de substituir, o arquivo anterior é copiado para
  `conf.yaml.bak-AAAAMMDD-HHMMSS-µs` ao lado dele. A gravação é atômica
  (arquivo temporário + `os.replace`), mantém as permissões e, se `conf.yaml` for
  um link simbólico (dotfiles), grava no destino do link e o link continua.
* **Cancelar**: *Descartar alterações* volta ao que está no disco; sair da página
  ou fechar a janela com alterações pede confirmação. Nada é gravado antes de
  *Salvar*.
* **Restaurar**: *Backups…* lista as versões guardadas (data, tamanho) com
  pré-visualização. Restaurar valida o backup como qualquer outro texto (um backup
  inválido é recusado), confirma e **guarda o arquivo atual como novo backup**, de
  modo que a restauração também pode ser desfeita.
* **Mudança externa**: ao abrir, a interface guarda a impressão digital (SHA-256)
  do arquivo. Se outro programa o alterar antes de *Salvar*, nada é gravado e um
  diálogo oferece recarregar do disco, gravar mesmo assim (o do disco vira
  backup) ou cancelar.
* **Arquivo inexistente**: a página abre o modelo padrão e o cria ao salvar.
* **Modo `--demo`**: edita uma cópia temporária do modelo do KDE, com a validação
  real; o arquivo do usuário não é lido nem gravado.

## 4. Erros que o editor aponta

Cada achado tem um código, caminho, linha e coluna (`Problem` em
`kongui/core/results.py`), traduzido em `kongui/gui/messages.py`
(`PROBLEM_TEXTS`). Principais: YAML malformado, raiz que não é mapa, falta de
`save`/`export`, seção nula, chave repetida, nome de grupo inválido, `location`
vazio ou não texto, placeholder ou função inexistente, `location` não resolvido
ou relativo, `entries` ausente ou que não é lista, item com `/` ou `.`/`..`,
chave desconhecida na raiz que quebraria o Konsave. Avisos (não bloqueiam): chave
desconhecida válida, item repetido, pasta de origem inexistente, várias funções.

## 5. Código e testes

| Peça | Onde |
|---|---|
| localizar linha/coluna e fim de conteúdo | `kongui/core/yamlmap.py` |
| modelo, edição cirúrgica, citação de escalares | `kongui/core/confedit.py` |
| validação com posições, backups, restauração, digest | `kongui/core/config.py` (`ConfigService`) |
| `ConfigSnapshot`, `ConfigCheck`, operações do backend | `kongui/gui/backend.py` |
| editor de seção, lista de problemas | `kongui/gui/widgets/confedit.py` |
| diálogos de grupo, backups e escolha | `kongui/gui/widgets/dialogs.py` |
| página | `kongui/gui/pages/config.py` |

```bash
python3 -m unittest tests.test_config_editor tests.test_gui_config -v
```

| Módulo de teste | Cobre |
|---|---|
| `tests.test_config_editor` | núcleo: leitura/escrita idêntica, edições que preservam comentários e chaves desconhecidas, arquivos incompletos e de layout exótico, caracteres especiais, 600 edições aleatórias, erros com posição, backups, restauração, conflito, symlink, permissões, comportamento do motor original (placeholders) |
| `tests.test_gui_config` | página: demo (memória) e serviços reais num `$HOME` temporário; validar, salvar, bloquear erros, cancelar, sair, texto quebrado, “Ir para”, backups, conflito, caracteres especiais e o `conf.yaml` real do Plasma 6 |

## 6. Limitações

* A ordem dos itens e dos grupos não é editável pela interface.
* Comentários em linhas próprias (entre grupos ou itens) ficam onde estão; o
  comentário escrito na mesma linha de um item removido some com ele. Se a edição
  for exótica demais, o caminho de regeneração perde os comentários (e avisa).
* Os backups não são removidos automaticamente (são arquivos pequenos).
* Não há trava entre processos: a verificação de mudança externa é feita só no
  momento de gravar.
* A pasta de origem de um grupo é validada, mas o conteúdo dos itens não é
  conferido no disco (o Konsave ignora, em silêncio, o que não existe).
