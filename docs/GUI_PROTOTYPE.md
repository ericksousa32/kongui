# Protótipo visual da interface (PySide6 / Qt Widgets)

Primeira versão da interface gráfica do KonGUI. **É um protótipo visual:** usa
dados fictícios e **não executa nenhuma operação do Konsave**. O motor original
(`konsave/`) e a camada de integração (`kongui/core/`) não foram alterados e não
são usados por este código.

## 1. Como executar

```bash
pip install "PySide6>=6.8"      # ou: pip install -e ".[gui]"
python3 -m kongui.gui           # também: comando `kongui`, depois de instalar
```

O programa recusa rodar como root (usa `kongui.core.safety.ensure_not_root`).
As preferências ficam em `<pasta de configuração do usuário>/kongui/kongui-gui.ini`
(via `QStandardPaths`); nada além disso é gravado em disco.

## 2. Páginas

| Página | Chave | Atalho | Ações na barra superior | Conteúdo |
|---|---|---|---|---|
| Dashboard | `dashboard` | `Ctrl+1` | Importar, Salvar perfil atual (`Ctrl+S`) | 4 cartões de resumo, perfil ativo, atividade recente |
| Perfis | `profiles` | `Ctrl+2` | Novo perfil (`Ctrl+N`) | busca (`Ctrl+F`), ordenação, grade/lista, cartões de perfil |
| Importar / Exportar | `transfer` | `Ctrl+3` | — | formulário de exportação, área de soltar `.knsv`, transferências recentes |
| Configurações | `settings` | `Ctrl+4` | — | tema, confirmações, exibição, duração dos avisos, dados de demonstração |
| Sobre | `about` | `Ctrl+5` | — | versão, ambiente, links, aviso de protótipo |

A navegação lateral é fixa (232 px) com ícone e rótulo. A janela tem tamanho
mínimo de 900 × 600.

## 3. Estrutura do código (`kongui/gui/`)

| Módulo | Responsabilidade |
|---|---|
| `app.py`, `__main__.py` | criação do `QApplication`, recusa de root, caminho das preferências |
| `main_window.py` | `MainWindow`: barra lateral, barra superior, pilha de páginas, atalhos |
| `context.py` | `AppContext`: o que cada página recebe (modelos, tema, avisos, navegação) |
| `state.py` | `Profile`, `ProfileStore`, `ActivityLog`, `AppSettings` (modelos em memória, com sinais) |
| `mock_data.py` | **todos** os dados fictícios (sete perfis, seis eventos, lista de seções) |
| `actions.py` | criar, aplicar, duplicar e remover perfis no modelo fictício |
| `validation.py` | regras de nome (reaproveita `kongui.core.safety.validate_profile_name`) |
| `theme.py` | tokens de cor, paleta Qt, folha de estilo e `ThemeManager` |
| `icons.py` | ícones SVG desenhados no código e coloridos pelo tema |
| `formatting.py` | tamanhos, datas relativas e plurais em pt-BR |
| `widgets/` | peças reutilizáveis: `common` (botão, rótulo, selo, cartão, controle segmentado), `grid` (grade adaptável), `cards`, `shell` (barra lateral e superior), `states` (estado vazio), `search`, `toast`, `dialogs`, `dropzone`, `progress`, `rows` |
| `pages/` | uma classe por página, sobre `pages/base.py` |

Regras seguidas: cores só vêm de `Tokens`; ícones são refeitos quando
`ThemeManager.changed` dispara; nenhuma página importa `konsave` nem os serviços
de `kongui.core` (só `safety` e `errors`). Os testes conferem essas regras.

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

Verificação visual manual: abra o programa, alterne os três temas, redimensione
a janela até o mínimo e use **Configurações → Esvaziar perfis** para ver os
estados vazios. Para o aviso de arquivo existente, exporte o perfil
“Minimalista” sem marcar “Substituir”.

## 6. O que o protótipo simula

* Aplicar, salvar, duplicar, remover, exportar e importar só mudam as listas em
  memória. Todo aviso diz “Simulação: nada foi alterado no sistema.”.
* Exportar e importar mostram uma barra de progresso falsa
  (`widgets/progress.py`). Importar mostra apenas nome e tamanho do arquivo;
  ele nunca é aberto.
* O arquivo `Minimalista.knsv` “já existe” no destino, para exibir o erro.

## 7. Limitações e próximos passos

* Os modelos de `state.py` ainda não falam com `kongui.core`. A ligação com
  `ProfileService`/`ConfigService` (em thread, com cancelamento e tratamento de
  `OperationResult`) é a próxima fase.
* Sem backup antes de aplicar, sem editor de `conf.yaml` e sem prévia real do
  conteúdo de um `.knsv` (`inspect_archive` não existe ainda; ver
  `INTEGRATION.md` §8).
* Não testado em Plasma 6 real: cor de destaque, troca de esquema com o app
  aberto, escala fracionária e Wayland precisam de verificação manual.
* Acessibilidade: nomes acessíveis, foco por teclado e contraste foram tratados,
  mas não houve teste com leitor de tela.
* Textos em pt-BR fixos no código; falta internacionalização (`tr`).
* A janela depende do estilo de ícones próprio; ícones do tema do sistema
  (`QIcon.fromTheme`) são uma opção futura.
