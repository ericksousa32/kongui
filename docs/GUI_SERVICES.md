# Interface ligada aos serviços

A janela deixa de usar só dados fictícios: as seis operações de perfil passam
pelo `ProfileService` do KonGUI (e, por ele, pelo Konsave original). O código de
`konsave/` **não foi alterado**.

## 1. Como usar

```bash
python3 -m kongui.gui           # perfis reais do usuário atual
python3 -m kongui.gui --demo    # dados fictícios; nada é gravado nem aplicado
```

O programa recusa rodar como root e avisa se o Konsave não puder ser carregado.
Importar e exportar estão descritos na §4.

## 2. Arquitetura

```
Página ──► ProfileActions (diálogos) ──► ProfileController ──► Executor (thread)
   ▲                                          │                     │
   └────────── ProfileStore ◄─────────────────┘            ProfileBackend
                                                  ServiceBackend │ FakeBackend
```

* `ProfileBackend` (`backend.py`) é o que a interface precisa. `ServiceBackend`
  chama `ProfileService`; `FakeBackend` guarda perfis em memória (modo demo e
  testes). Os métodos bloqueiam e nunca tocam em objetos Qt.
* `ProfileController` (`controller.py`) roda **uma operação por vez**. Pedidos
  durante uma operação são recusados (a GUI avisa “Aguarde”). Depois de cada
  operação, mesmo que ela falhe, a lista é lida de novo e publicada no
  `ProfileStore`, e um `Outcome` é emitido.
* `tasks.py`: `ThreadExecutor` executa o trabalho numa thread e devolve o
  resultado à thread da interface por sinal; a interface não congela.
* **Nada que toca o disco roda na thread da interface**: leituras (`conf.yaml`,
  backups, inspeção de `.knsv`) passam por `controller.background`, e a
  verificação da pasta de exportação (`probe_export`) também. A janela **não
  fecha** enquanto uma operação roda (aviso “Operação em andamento”): o Konsave
  não pode ser interrompido e fechar deixaria o processo órfão.
* `OutcomeNotifier` (`actions.py`) mostra o aviso (erros ficam até serem
  fechados) e registra a atividade.
* `messages.py` traduz resultados e exceções para pt-BR. Exceções desconhecidas
  aparecem com o tipo, para que um bug não fique escondido.

## 3. As seis operações

| Operação | Serviço | Carregamento | Confirmação |
|---|---|---|---|
| Listar | `list_profiles` | “Carregando…” na página e no painel; barra fina sob a barra superior | — |
| Salvar | `ConfigService.ensure_default_config` + `save` | botões travados, barra ocupada | — (nome validado antes) |
| Sobrescrever | `ProfileService.replace` | cartão mostra “Sobrescrevendo…” | diálogo destrutivo |
| Aplicar | `apply` | cartão mostra “Aplicando…” | diálogo destrutivo |
| Remover | `remove` | cartão mostra “Removendo…” | diálogo destrutivo |
| Limpar todos | `wipe_all` | botões travados | diálogo destrutivo **e** digitar `APAGAR` |
| Exportar | `ProfileService.export` | barra ocupada, botão travado | só para substituir um arquivo (ver §4) |
| Importar | `ProfileService.import_profile` | verificação em segundo plano, depois barra ocupada | sempre |

Cada erro aparece como aviso persistente com a causa; falha ao listar mostra uma
faixa com “Tentar novamente”. As camadas inferiores também exigem `confirmed=True`
(valores “truthy” como `1` são recusados).

### Por que `replace` existe (única mudança fora da GUI)

`konsave save -f` **mescla** o perfil antigo em vez de substituí-lo: arquivos que
não existem mais continuam no perfil. Para “Sobrescrever” de verdade foi
acrescentado `ProfileService.replace`, sem mexer no Konsave: salva num nome
temporário (`.kongui-…`), confere o resultado e troca por `rename` com
reversão se algo falhar. Entradas com esse prefixo nunca são listadas.

### Operações sobre o `conf.yaml`

`ProfileBackend` também expõe `load_config`, `check_config`, `save_config`,
`list_config_backups`, `read_config_backup` e `restore_config` (ver
[`GUI_CONFIG.md`](GUI_CONFIG.md)). As leituras rodam em segundo plano sem contar
como operação; `save_config` e `restore_config` usam o mesmo ciclo das outras
(barra ocupada, aviso de sucesso ou erro) e não recarregam a lista de perfis.

## 4. Importar e exportar

Formato: o `.knsv` **original** do Konsave (um zip com `conf.yaml`, `save/` e
`export/`). A GUI não cria nenhum formato novo; os testes trocam arquivos com o
`python -m konsave` original nos dois sentidos.

### Opções do CLI e como aparecem

| CLI original | Na interface | Comportamento real |
|---|---|---|
| `-e PERFIL` | lista “Perfil” | o perfil precisa existir e ter `conf.yaml` válido |
| `-d PASTA` | “Pasta de destino” + **Escolher…** | o original usa a pasta atual; aqui o padrão é `~/Downloads`. A pasta precisa existir e aceitar escrita (checado antes, com mensagem clara). `~` vale a home do motor |
| `-n NOME` | “Nome do arquivo (sem extensão)” | começa igual ao perfil; mesmas regras de nome do core (sem `/`, `.`/`..`, `-` inicial, `.knsv`/`.zip`) |
| `-f` | “Se o arquivo já existir” | ver abaixo |
| `-i ARQUIVO` | área de soltar / **Escolher arquivo** | só `.knsv`; o arquivo é verificado (somente leitura) assim que é escolhido |
| (nenhuma) | “Nome do perfil importado” | o original usa o nome do arquivo; ver “Renomear” |
| (nenhuma) | “Aplicar o perfil depois de importar” | segundo passo separado: se falhar, o perfil continua importado e um aviso explica |

### Conflito ao exportar (semântica do `-f`)

Sem `-f` o original **não pergunta**: acrescenta data e hora ao nome. Com `-f`
substitui. O `force` do original também apaga uma pasta com o nome do arquivo,
por isso a GUI nunca o repassa para pastas. Escolha “Se o arquivo já existir”:

| Opção | Se existir um `.knsv` | Se existir pasta, `.zip` ou link com esse nome |
|---|---|---|
| Perguntar (padrão) | diálogo: **Substituir**, **Usar nome único** ou Cancelar | diálogo só com **Usar nome único** |
| Criar um nome único | `nome-2.knsv`, `nome-3.knsv`… (sem perguntar; nada é perdido) | idem |
| Substituir | confirmação destrutiva; só substitui um arquivo regular | **recusa** (o original apagaria a pasta) |

Quando nada existe, a exportação vai com a política `error`: se alguém criar o
arquivo no meio do caminho, ele **não** é sobrescrito. Diferença conhecida: o
nome único do original é `nome_fDD-MM-AAAA:HH-MM-SS`; o do core é `nome-2`.

### Importar

* **Sempre confirma**: o original grava a seção `export` do arquivo direto no
  sistema (por exemplo, `~/.local/share/icons`), sobrescrevendo (antes, os arquivos
  que seriam sobrescritos são copiados: ver §7). O
  diálogo lista as seções que serão gravadas.
* Nunca substitui um perfil: se o nome já existe, o formulário recusa (o
  original também recusa).
* `ProfileService.inspect_archive` (novo, somente leitura) faz as mesmas
  verificações da importação — zip legível, nomes de membros seguros, `conf.yaml`
  e `save/` presentes, configuração válida e destinos dentro da home — e mostra
  nome, tamanho e seções antes de qualquer gravação. Arquivo ausente, não-zip,
  sem `conf.yaml`, com caminhos inseguros ou sem permissão de leitura aparecem
  como erro no formulário.
* Destinos **fora da home** continuam recusados (`allow_outside_home` não é
  exposto na interface).
* **Renomear**: o original nomeia o perfil pelo arquivo. Para usar outro nome,
  o *mesmo* arquivo é copiado para uma pasta temporária privada com o nome
  novo e importado de lá; a cópia é apagada no fim, mesmo em erro, e o original
  não é tocado. Não é um formato novo.

### Erros

Permissão negada, arquivo ou pasta ausente e demais `OSError` viram mensagens em
pt-BR (e não são registrados como bug). Falhas de exportação ficam na tela até
serem fechadas e o formulário continua preenchido.

## 5. Testes

Nenhum teste aplica perfil na sessão real: usam `FakeBackend` ou `$HOME`
temporário, e os testes com arquivos recusam rodar como root.

```bash
QT_QPA_PLATFORM=offscreen python3 -m unittest tests.test_gui_operations tests.test_gui_real_backend tests.test_gui_support tests.test_gui_transfer tests.test_gui_transfer_roundtrip tests.test_gui_config tests.test_config_editor -v
```

`tests.test_gui_transfer_roundtrip` exporta num home e importa em outro com o
Konsave real, compara o perfil byte a byte e repete com o CLI original.

## 6. Limitações conhecidas

* Aplicar não é atômico: se falhar no
  meio, parte dos arquivos já foi trocada (o aviso mostra os erros do Konsave).
* Importar grava a seção `export` do arquivo **antes** de qualquer outra coisa;
  se o Konsave falhar depois, o perfil é desfeito, mas esses arquivos já escritos
  não voltam sozinhos: restaure a cópia de segurança (§7).
* “Ativo” é apenas o último perfil aplicado por esta interface
  (`last_applied`); o Konsave não registra isso.
* O Konsave não guarda descrição nem seções: no modo real, o diálogo de salvar
  pede só o nome e os cartões não mostram descrição.
* Sem cancelamento nem progresso parcial; só “ocupado”. Exportar ou importar um
  perfil grande pode demorar e bloqueia outras operações.
* O `.knsv` não é assinado nem cifrado e o `conf.yaml` dele decide para onde os
  arquivos vão: a GUI só aceita destinos dentro da home, mas importe apenas
  arquivos de fontes confiáveis.
* Exportar copia o `conf.yaml` **global** atual para dentro do `.knsv`, mas
  monta `save/` e `export/` com os grupos do `conf.yaml` **do perfil**
  (limitação do Konsave). Se eles diferirem, o arquivo se contradiz: grupo novo
  impede aplicar o perfil importado; grupo removido é ignorado sem aviso. A GUI
  avisa ao exportar e ao inspecionar o arquivo, mas **não reescreve** o
  `conf.yaml` do arquivo (isso mudaria a saída do Konsave; decisão do projeto).
* O bit executável e metadados de arquivos não sobrevivem ao ciclo exportar →
  importar (limitação do Konsave).
* `replace` usa `rename` (mesmo sistema de arquivos) e só deixa resíduo `.kongui-*`
  se o processo morrer no meio.
* Não há trava entre processos: dois KonGUI (ou o `konsave` na linha de comando)
  ao mesmo tempo podem se atropelar.
* O motor redireciona `stdout` de forma global durante cada chamada.
* A edição do `conf.yaml` está descrita em [`GUI_CONFIG.md`](GUI_CONFIG.md).
* Não testado em uma sessão Plasma real.

## 7. Cópias de segurança (RN-01)

Antes de **aplicar** ou **importar**, o serviço copia os arquivos que seriam
sobrescritos (detalhes em [`INTEGRATION.md`](INTEGRATION.md) §9). Na interface:

* os avisos de aplicar/importar dizem o identificador da cópia (“Cópia de
  segurança guardada…”), e os textos de confirmação deixaram de dizer “sem backup”;
* **Configurações → Cópias de segurança → Gerenciar…** abre a lista (data,
  operação, perfil, arquivos substituídos/criados, tamanho, mais nova primeiro);
* **Restaurar** pede confirmação (destrutivo), guarda o estado atual como nova
  cópia e devolve os arquivos; **Apagar** pede confirmação. Os botões ficam
  travados enquanto outra operação roda, a lista é lida em segundo plano e é
  relida após cada restauração ou exclusão;
* se a cópia não puder ser feita, aparece o erro e **nada é aplicado ou importado**;
* nenhuma cópia é apagada automaticamente; a cópia de um `import` não desfaz o
  perfil importado;
* modo demonstração: cópias fictícias, nada é gravado.

Testes: `tests.test_snapshot` (núcleo, Konsave real num `$HOME` temporário) e
`tests.test_gui_backups` (diálogo, controller, mensagens e ponta a ponta).

