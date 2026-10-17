# Auditoria final do KonGUI

**Veredito: o projeto NÃO está completo.** Há requisitos obrigatórios
pendentes (ver §4: P-2 e P-3). O P-1 (RN-01, cópia de segurança antes de
aplicar/importar) foi implementado e testado depois do primeiro relatório. Tudo o que foi comprovadamente quebrado e
estava ao alcance foi corrigido; o que depende de alterar o Konsave
(`konsave/` não pode ser modificado) ou de uma sessão Plasma real está marcado
como bloqueado.

## 1. Escopo e método

* Base: o CLI original (`konsave/__main__.py`) e os requisitos de cada etapa
  anterior (integração, protótipo, ligação aos serviços, importar/exportar,
  editor do `conf.yaml`).
* **Limitação desta auditoria:** a “matriz de requisitos” da primeira auditoria
  não está no repositório, nos documentos do projeto nem no histórico a que esta
  sessão tem acesso (só resta a referência “RN-01” em `docs/INTEGRATION.md`). A
  lista da §3 foi **reconstruída** a partir do CLI e dos pedidos de cada etapa.
  Se a matriz original tiver itens que não estão aqui, eles precisam ser
  conferidos pelo dono do projeto.
* Para cada achado: sonda reproduzível, correção mínima, teste que falha sem a
  correção. Só foram corrigidos problemas **comprovados**; nada foi reescrito.
* Os testes rodam como usuário sem privilégios, com `$HOME` temporário. Nenhum
  aplica perfil na sessão real (`tests.test_zz_real_home_guard` confere isso).
* Testes desta auditoria: `tests.test_gui_audit`, `tests.test_core_audit`
  (além de `tests.test_safety`, `tests.test_gui_dialogs`, ampliados). O P-1 tem
  os seus: `tests.test_snapshot` e `tests.test_gui_backups`.

## 2. Achados corrigidos

| # | Problema comprovado | Correção | Commit |
|---|---|---|---|
| A-1 | Nome `.kongui-*` era aceito ao salvar, mas nunca listado (perfil “invisível”, impossível de remover) | prefixo reservado recusado pelo core e pela GUI | b05e3db |
| A-2 | Limite de nome em caracteres: nomes com acento/emoji passavam e o sistema de arquivos recusava (255 bytes) | limite de 200 **bytes** (core + mensagem na GUI) | b05e3db |
| A-3 | Fechar a janela durante uma operação congelava, deixava processo órfão e imprimia traceback | janela recusa fechar ocupada; worker ignora `RuntimeError` após o desmonte | 8730a08 |
| A-4 | Exportar com `conf.yaml` global diferente do perfil gerava `.knsv` contraditório sem aviso | aviso ao exportar e ao inspecionar (`+` só no ativo, `-` só no perfil, `~` alterado); mensagem em pt-BR | c6c9a6d |
| A-5 | `probe_export` (acesso a disco) rodava na thread da interface | roda em segundo plano; botão travado enquanto verifica | 969d8d5 |
| A-6 | Versão do Konsave (`-v`) não aparecia na interface | “Versão do Konsave” em Sobre | 969d8d5 |
| A-7 | Mensagem de importação com pasta residual não dizia qual pasta | caminho incluído | 969d8d5 |
| A-8 | Exportar numa conta sem `conf.yaml` falhava com `FileNotFoundError` cru | cria o padrão antes (como o original faz ao iniciar); core exige config ativa | 4d2730f |
| A-9 | Editor do `conf.yaml` podia misturar `\n` e `\r\n` | quebras de linha do original preservadas | 0f268a0 |
| A-10 | `requirements_dev.txt` listava dependências sem uso | só `black` e `pylint` | 0f268a0 |
| A-12 | **P-1 / RN-01:** aplicar e importar sobrescreviam arquivos sem nenhuma volta (os textos de confirmação diziam “sem backup”) | `kongui/core/snapshot.py`: cópia dos arquivos que seriam sobrescritos antes de rodar (falha fechada), restaurar/listar/apagar, diálogo em Configurações → Cópias de segurança (`docs/INTEGRATION.md` §9, `docs/GUI_SERVICES.md` §7) | commit desta etapa |
| A-11 | Diálogos reais (confirmar, escolher, digitar `APAGAR`) sem teste | `tests.test_gui_dialogs`; caminhos de falha do editor em `tests.test_gui_audit` | 0f268a0 + este |

## 3. Matriz final de requisitos

Legenda: **Testado** = implementado e coberto por teste automatizado;
**Implementado** = existe, sem teste automatizado suficiente; **Pendente** =
não existe e é requisito; **Bloqueado** = depende de algo fora do alcance
(motor intocável ou sessão Plasma real).

### 3.1 Opções do CLI original

| Requisito | Equivalente gráfico | Status | Evidência / observação |
|---|---|---|---|
| `-l/--list` | Lista de perfis (página e painel) | Testado | `tests.test_gui_real_backend` (RealListTests), `tests.test_profile_service_integration` |
| `-s/--save` | Diálogo “Salvar perfil” | Testado | SaveIntegrationTests, RealSaveTests; nomes: `tests.test_safety` |
| `-s -f` (sobrescrever) | “Sobrescrever” (`ProfileService.replace`, semântica de **substituição**, não de mescla) | Testado | ReplaceIntegrationTests, RealOverwriteTests; confirmação destrutiva |
| `-a/--apply` | “Aplicar” | Testado | ApplyIntegrationTests, RealApplyTests; confirmação destrutiva; cópia de segurança antes (RN-01). Continua não atômico (o aviso mostra os erros do Konsave; a cópia permite voltar) |
| `-r/--remove` | “Remover” | Testado | RemoveAndWipeIntegrationTests, RealRemoveTests; confirmação |
| `-w/--wipe` | “Limpar todos” | Testado | confirmação **e** digitar `APAGAR` (`tests.test_gui_dialogs`) |
| `-e/--export-profile` | Página Exportar | Testado | `tests.test_gui_transfer_roundtrip` (ExportTests, CliCompatibilityTests) |
| `-d/--export-directory` | “Pasta de destino” + Escolher… | Testado | padrão `~/Downloads` (o original usa a pasta atual); pasta verificada antes (`tests.test_gui_audit`) |
| `-n/--export-name` | “Nome do arquivo” | Testado | regras de nome do core |
| `-f` na exportação | diálogo “O arquivo já existe” (substituir / nome único / cancelar), sempre exibido | Testado | nunca repassa `force` a pastas; nome único `nome-2` em vez de `nome_fData` (diferença conhecida) |
| `-i/--import-profile` | Página Importar (soltar/escolher) | Testado | HostileArchiveIntegrationTests, InspectArchiveIntegrationTests, ImportTests |
| `-v/--version` | Sobre → “Versão do Konsave” | Testado | `tests.test_gui_audit` (EngineVersionTests) |
| `-h/--help` | — | N/A | não faz sentido em GUI |
| `conf.yaml` padrão criado ao iniciar | `ensure_default_config` antes de salvar/exportar | Testado | `conf_kde.yaml` x `conf_other.yaml` conforme o desktop; FreshAccountExportTests |

### 3.2 Editor do `conf.yaml`

| Requisito | Status | Evidência |
|---|---|---|
| Validar antes de gravar; não gravar se falhar | Testado | `tests.test_config_editor`, `tests.test_gui_config` |
| Erros com linha/coluna e caminho; ir ao ponto | Testado | idem |
| Backup antes de cada gravação; restaurar backup | Testado | idem; conflito forçável (`tests.test_gui_audit`) |
| Preservar comentários, chaves desconhecidas, placeholders, BOM, âncoras | Testado | arquivo Plasma 6 real (`tests/profile_test.knsv`) |
| Estilo *flow* ⇒ reescrita sem comentários, só com “sim” explícito | Testado | `tests.test_gui_audit` (ConfigPageFailurePathTests) |
| Gravar ocupado/sem validar não grava nada | Testado | idem |
| Placeholders (`$HOME`, `$XDG_*`…) interpretados como o original | Testado | `tests.test_config_service` (PlaceholderValidationTests) |
| Poda de backups antigos | Pendente (não obrigatório) | os backups crescem sem limite |

### 3.3 Segurança, concorrência e arquivos

| Requisito | Status | Evidência / observação |
|---|---|---|
| Toda operação destrutiva confirmada (aplicar, remover, limpar, importar, substituir arquivo) e recusada sem `confirmed=True` real | Testado | `tests.test_gui_dialogs`, `tests.test_profile_service_mocked` |
| Interface não congela; uma operação por vez; “Aguarde” | Testado | `tests.test_gui_operations`, `tests.test_gui_audit` |
| Fechar janela com operação em curso | Testado | CloseWhileBusyTests |
| Nomes de perfil/arquivo (`/`, `..`, `-` inicial, reservado, bytes) | Testado | `tests.test_safety` |
| Arquivos hostis (`..`, absolutos, links, destino fora da home) | Testado | HostileArchiveIntegrationTests |
| Permissões e pastas ausentes viram mensagem clara | Testado | `tests.test_gui_transfer`, `tests.test_gui_audit` |
| Recusa de execução como root | Testado | `tests.test_engine`, `tests.test_cli_runner` |
| **RN-01 / P-1:** cópia dos arquivos que `apply`/`import` sobrescrevem, antes de gravar; falha da cópia impede a operação | Testado | `tests.test_snapshot` (ApplySnapshotTests, ImportSnapshotTests), `tests.test_gui_backups` (RealSafetyCopyTests) |
| RN-01: restaurar (arquivos, modo, links, arquivos criados), com confirmação, validação do manifesto, caminhos só dentro da home, desfazer da restauração | Testado | RestoreRulesTests, EdgeCaseTests |
| RN-01: listar/apagar cópias na interface; botões travados durante operação; nada é apagado sozinho | Testado | `tests.test_gui_backups` (DemoSafetyCopyTests) |
| Importar → exportar preserva o perfil (Plasma 6 real) | Testado | idêntico, exceto `conf.yaml` (A-4/§5) |
| `.knsv` trocado com o `konsave` original nos dois sentidos | Testado | CliCompatibilityTests |
| Dependências sem uso | Testado | A-10; `setuptools` em runtime ainda declarado (ver §5) |

### 3.4 Pendentes e bloqueados

| Id | Requisito | Status | Motivo |
|---|---|---|---|
| P-2 | Trava entre processos (dois KonGUI ou KonGUI + `konsave`) | **Pendente** | só há exclusão dentro do processo |
| P-3 | Limites de zip-bomb, tamanho total e espaço em disco ao importar/exportar | **Pendente** | não há checagem de tamanho/espaço |
| B-1 | Progresso e cancelamento de operações | Bloqueado | o motor não é interrompível e `konsave/` não pode ser alterado; hoje só “ocupado” |
| B-2 | Descrição e seções do perfil | Bloqueado | o Konsave não armazena esses dados |
| B-3 | Validação numa sessão Plasma real (aplicar de verdade, Wayland/arrastar-e-soltar, SELinux, Flatpak) | Bloqueado | ambiente de teste sem sessão gráfica real |

## 4. Por que não está completo

P-2 (trava entre processos) e P-3 (limites de tamanho, zip-bomb e espaço em
disco) são riscos de perda de dados/disponibilidade que a GUI não mitiga e
seguem pendentes; enquanto existirem, o projeto não é declarado completo. Os
bloqueios B-1 a B-3 não impedem o uso, mas limitam o que pode ser afirmado.

Limites do P-1, já documentados: a cópia de um `import` não desfaz o perfil
importado; a restauração não protege contra programas que alterem os mesmos
arquivos ao mesmo tempo (P-2); a cópia não tem limite de tamanho (P-3).

## 5. Decisões e pontos em aberto para o dono do projeto

1. **`conf.yaml` dentro do `.knsv`**: o Konsave grava o `conf.yaml` global, mas
   monta `save/`/`export/` com o do perfil. A GUI **avisa** (A-4), mas não
   reescreve o do arquivo. Decidir se deve reescrever.
2. **RN-01** (P-1): foi implementado com o escopo “só os arquivos que a operação sobrescreve”, em `~/.config/konsave/kongui-backups/`, sem retenção automática (uma poda apagaria justamente a cópia mais antiga, a que guarda o estado original). Confirmar se é o desejado ou se deve haver limite de quantidade.
3. `setuptools` é declarado como dependência de execução sem necessidade
   comprovada; deixado como está por estar fora da prova desta auditoria.
4. O comando `kongui` sem PySide6 instalado mostra um `ImportError` cru.
5. Backups do `conf.yaml` nunca são podados.
6. `conf.yaml` em estilo *flow* cai em reescrita com perda de comentários (com
   confirmação explícita).

## 6. Resultado dos testes

* 716 testes, todos passando, executados como usuário sem privilégios.
* Cobertura de linhas e ramos de `kongui/`: 96% (`snapshot.py`: 97%).
* `pylint kongui`: 10,00/10; `black --check`: limpo.
