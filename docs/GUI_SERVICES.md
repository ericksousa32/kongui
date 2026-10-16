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

Cada erro aparece como aviso persistente com a causa; falha ao listar mostra uma
faixa com “Tentar novamente”. As camadas inferiores também exigem `confirmed=True`
(valores “truthy” como `1` são recusados).

### Por que `replace` existe (única mudança fora da GUI)

`konsave save -f` **mescla** o perfil antigo em vez de substituí-lo: arquivos que
não existem mais continuam no perfil. Para “Sobrescrever” de verdade foi
acrescentado `ProfileService.replace`, sem mexer no Konsave: salva num nome
temporário (`.kongui-…`), confere o resultado e troca por `rename` com
reversão se algo falhar. Entradas com esse prefixo nunca são listadas.

## 4. Testes

Nenhum teste aplica perfis na sessão real: usam `FakeBackend` ou um `$HOME`
temporário, e os testes com arquivos recusam rodar como root.

```bash
QT_QPA_PLATFORM=offscreen python3 -m unittest tests.test_gui_operations tests.test_gui_real_backend tests.test_gui_support -v
```

## 5. Limitações conhecidas

* Aplicar **não faz backup** e não é atômico: se falhar no meio, parte dos
  arquivos já foi trocada (o aviso mostra os erros do Konsave).
* “Ativo” é apenas o último perfil aplicado por esta interface
  (`last_applied`); o Konsave não registra isso.
* O Konsave não guarda descrição nem seções: no modo real, o diálogo pede só o
  nome e os cartões não mostram descrição.
* Sem cancelamento nem progresso parcial; só “ocupado”.
* `replace` usa `rename` (mesmo sistema de arquivos) e só deixa resíduo `.kongui-*`
  se o processo morrer no meio.
* Não há trava entre processos: dois KonGUI (ou o `konsave` na linha de comando)
  ao mesmo tempo podem se atropelar.
* O motor redireciona `stdout` de forma global durante cada chamada.
* Importar/exportar e editar `conf.yaml` seguem fora desta etapa (aba Transferir
  desativada no modo real).
* Não testado em uma sessão Plasma real.
