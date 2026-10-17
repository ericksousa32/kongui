# Protótipo visual da interface (PySide6 / Qt Widgets)

Primeira versão da interface gráfica do KonGUI, criada como protótipo visual.
**Atualização:** a interface agora está ligada aos serviços (`kongui/core/`) por
padrão; o modo `--demo` mantém o comportamento original do protótipo, com dados
fictícios. A ligação, os estados de carregamento e as limitações estão em
[`GUI_SERVICES.md`](GUI_SERVICES.md). O motor original (`konsave/`) não foi alterado.

## 1. Como executar

```bash
pip install "PySide6>=6.8"      # ou: pip install -e ".[gui]"
python3 -m kongui.gui           # perfis reais (serviços do KonGUI sobre o Konsave)
python3 -m kongui.gui --demo    # dados fictícios, nada é gravado nem aplicado
```

O programa recusa rodar como root (usa `kongui.core.safety.ensure_not_root`).
As preferências ficam em `<pasta de configuração do usuário>/kongui/kongui-gui.ini`
(via `QStandardPaths`); nada além disso é gravado em disco.

## 2. Páginas

| Página | Chave | Atalho | Ações na barra superior | Conteúdo |
|---|---|---|---|---|
| Dashboard | `dashboard` | `Ctrl+1` | Importar, Salvar perfil atual (`Ctrl+S`) | 4 cartões de resumo, perfil ativo, atividade recente |
| Perfis | `profiles` | `Ctrl+2` | Limpar todos, Novo perfil (`Ctrl+N`) | busca (`Ctrl+F`), ordenação, grade/lista, cartões de perfil |
| Importar / Exportar | `transfer` | `Ctrl+3` | — | formulário de exportação (perfil, pasta, nome; se o arquivo já existir, sempre pergunta), área de soltar `.knsv` com verificação, transferências recentes (ver [`GUI_SERVICES.md`](GUI_SERVICES.md) §4) |
| Configurações | `settings` | `Ctrl+4` | — | tema, exibição, duração dos avisos, dados de demonstração (só no modo `--demo`) |
| Editar .YAML | `config` | `Ctrl+5` | Validar, Backups…, Descartar, Salvar | editor do `conf.yaml`: seções `save` e `export` separadas, texto YAML, painel de problemas com linha/coluna, backups e restauração (ver [`GUI_CONFIG.md`](GUI_CONFIG.md)) |
| Sobre | `about` | `Ctrl+6` | — | versão, ambiente, links, aviso de protótipo |

A navegação lateral é fixa (232 px) com ícone e rótulo. A janela tem tamanho
mínimo de 900 × 600.

## 3. Estrutura do código (`kongui/gui/`)

| Módulo | Responsabilidade |
|---|---|
| `app.py`, `__main__.py` | criação do `QApplication`, recusa de root, escolha do backend (`--demo`), caminho das preferências |
| `main_window.py` | `MainWindow`: barra lateral, barra superior, barra de progresso, pilha de páginas, atalhos |
| `context.py` | `AppContext`: o que cada página recebe (modelo, backend, controller, tema, avisos, navegação) |
| `state.py` | `Profile`, `ProfileStore`, `ActivityLog`, `AppSettings` (modelos em memória, com sinais) |
| `backend.py` | `ProfileBackend`, `ServiceBackend` (serviços reais) e `FakeBackend` (memória); único módulo da GUI que importa o engine e os serviços |
| `controller.py` | `ProfileController`: executa uma operação por vez, estado de carregamento, atualiza o `ProfileStore` |
| `tasks.py` | executores: `ThreadExecutor` (thread de trabalho), `InlineExecutor` (testes) |
| `messages.py` | textos pt-BR de sucesso e de erro |
| `mock_data.py` | **todos** os dados fictícios (sete perfis, seis eventos, lista de seções) |
| `actions.py` | diálogos de confirmação e chamadas ao controller; avisos e atividade de cada resultado |
| `validation.py` | regras de nome (reaproveita `kongui.core.safety.validate_profile_name`) |
| `theme.py` | tokens de cor, paleta Qt, folha de estilo e `ThemeManager` |
| `icons.py` | ícones SVG desenhados no código e coloridos pelo tema |
| `formatting.py` | tamanhos, datas relativas e plurais em pt-BR |
| `widgets/` | peças reutilizáveis: `common` (botão, rótulo, selo, cartão, controle segmentado), `grid` (grade adaptável), `cards`, `shell` (barra lateral e superior), `states` (estado vazio), `search`, `toast`, `dialogs`, `dropzone`, `rows`, `feedback` (barra de ocupado e faixa de erro), `confedit` (editor de seção e lista de problemas do `conf.yaml`) |
| `pages/` | uma classe por página, sobre `pages/base.py` |

Regras seguidas: cores só vêm de `Tokens`; ícones são refeitos quando
`ThemeManager.changed` dispara; só `backend.py` importa `kongui.core.engine`,
`profiles` e `config`; ninguém importa `konsave` nem `subprocess`. Os testes
conferem essas regras.

## 4. Tema

Três modos, escolhidos em Configurações (ou pelo botão sol/lua da barra lateral):

* **Sistema**: usa a paleta da plataforma. No KDE, isso significa o esquema de
  cores do Plasma e a cor de destaque escolhida pelo usuário. Se o contraste do
  texto sobre o destaque for menor que 4,5:1, o texto é trocado por preto ou
  branco.
* **Claro** e **Escuro**: paletas fixas (contraste mínimo de 4,5:1 conferido em
  teste). Também é aplicada uma `QPalette`, para os controles nativos
  acompanharem.

Combos, caixas de seleção e `QSpinBox` ficam com a aparência nativa do estilo
do sistema de propósito, para combinar com o KDE.

## 5. Como validar

```bash
QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -t . -v
```

Os testes da interface não precisam de tela (`offscreen`) e usam `$HOME`
temporário. Se o PySide6 não estiver instalado, eles são pulados.

| Módulo de teste | Cobre |
|---|---|
| `tests.test_gui_startup` | abertura, estrutura fixa, ícones, preferências, entrada `main`, isolamento do Konsave |
| `tests.test_gui_navigation` | barra lateral, barra superior, atalhos, troca de tema |
| `tests.test_gui_widgets` | grade adaptável, avisos, diálogos, área de soltar, tema, formatação |
| `tests.test_gui_interaction` | cada página: busca, ordenação, aplicar, remover, exportar, importar, configurações |
| `tests.test_gui_operations` | as seis operações, uma a uma, na interface (backend em memória): carregamento, sucesso, erro, confirmação |
| `tests.test_gui_real_backend` | as seis operações nos serviços reais, em `$HOME` temporário |
| `tests.test_gui_transfer` | importar e exportar na interface (backend em memória): formulário, conflitos, confirmações, erros |
| `tests.test_gui_transfer_roundtrip` | exportar e importar nos serviços reais, em dois homes temporários; compatibilidade com o `python -m konsave` original |
| `tests.test_gui_config` | editor do `conf.yaml` na interface (memória e serviços reais): validar, salvar, cancelar, backups, conflito, caracteres especiais |
| `tests.test_gui_backups` | cópias de segurança na interface: diálogo, restaurar/apagar com confirmação, travas, erros, mensagens e ponta a ponta com os serviços reais |
| `tests.test_gui_dialogs` | os diálogos acionados de verdade (substituir/nome único, recarregar/gravar, palavra digitada, nome de grupo, prévia e restauração de backup) e os auxiliares de `app.py` |
| `tests.test_gui_audit` | achados da auditoria final: fechar durante operação, aviso de `conf.yaml` diferente, verificação da pasta de exportação fora da thread, versão do Konsave, exportar numa conta nova |
| `tests.test_gui_support` | mensagens, executores, `FakeBackend`, `ProfileStore`, widgets de feedback |

Verificação visual manual: abra o programa, alterne os três temas, redimensione
a janela até o mínimo e use **Configurações → Esvaziar perfis** para ver os
estados vazios. Para o aviso de arquivo existente, exporte o perfil
“Minimalista” sem marcar “Substituir”.

## 6. O que o modo `--demo` simula

* Aplicar, salvar, duplicar, remover, exportar e importar só mudam listas e um
  sistema de arquivos virtual, em memória. Todo aviso diz “Simulação: nada foi
  alterado no sistema.”.
* As regras são as reais: política de conflito, nomes inválidos e confirmações.
  Importar nunca abre o arquivo (só o nome e, se existir, o tamanho).
* O arquivo `~/Downloads/Minimalista.knsv` “já existe”, para exibir o conflito.

## 7. Limitações e próximos passos

* A edição de `conf.yaml` ainda não está ligada à GUI.
* Não testado em Plasma 6 real: cor de destaque, troca de esquema com o app
  aberto, escala fracionária e Wayland precisam de verificação manual.
* Acessibilidade: nomes acessíveis, foco por teclado e contraste foram tratados,
  mas não houve teste com leitor de tela.
* Textos em pt-BR fixos no código; falta internacionalização (`tr`).
* A janela depende do estilo de ícones próprio; ícones do tema do sistema
  (`QIcon.fromTheme`) são uma opção futura.
