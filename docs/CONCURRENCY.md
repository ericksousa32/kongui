# Trava entre processos

Dois programas mexendo nos mesmos arquivos ao mesmo tempo (dois KonGUI, ou o
KonGUI e o comando `konsave`) podiam corromper perfis, sobrescrever `conf.yaml` ou
misturar cópias de segurança. Desde esta etapa todas as operações que usam os dados
do Konsave passam por uma trava do próprio sistema operacional. As alterações no
código original estão em [`KONSAVE_PATCHES.md`](KONSAVE_PATCHES.md).

## 1. Como funciona

* Mecanismo: `fcntl.flock()` do Linux em um arquivo fixo,
  **`~/.config/konsave/.kongui.lock`** (dentro da pasta de dados do Konsave, para
  que todo programa que enxergue os mesmos perfis enxergue a mesma trava; não fica
  em `XDG_RUNTIME_DIR`, que muda entre sessões, `su` e `ssh`).
* **Não** usa arquivo de PID, arquivo temporário ou detecção de janela. O sistema
  libera a trava sozinho quando o processo termina, mesmo morto por `kill -9`.
* O arquivo de trava **nunca é apagado nem recriado** (apagar permitiria dois donos).
  Fica com permissão `0600`, é aberto sem seguir links simbólicos e precisa ser um
  arquivo comum do próprio usuário; caso contrário a operação falha com erro claro.
* Dois modos: **exclusiva** (altera dados) e **compartilhada** (só lê; vários
  leitores ao mesmo tempo, mas nunca junto de uma escrita).
* O descritor fica aberto durante toda a operação protegida e é fechado ao fim,
  também em exceção. Ele não é herdado por processos filhos.
* A espera é feita por tentativas sem bloqueio (10 ms crescendo até 100 ms), o que
  permite **tempo limite** e **cancelamento cooperativo** (`threading.Event`).
* Dentro do mesmo processo a trava é **reentrante por thread** (uma função de
  alto nível pode chamar outra). Pedir exclusiva estando com compartilhada é erro
  (`LockUsageError`), pois travaria a si mesmo. A ordem é sempre: trava de arquivo
  primeiro, depois `ENGINE_LOCK` (o `RLock` do processo); não há ordem inversa.
* O arquivo guarda, só para mensagens, `{pid, operação, desde}` de quem tem a trava
  exclusiva. É **informação**, não prova de posse: se o PID não existe mais ele é
  ignorado, e quem decide é sempre o sistema (`flock`).

## 2. O que é protegido

| Operação | Trava |
|---|---|
| salvar, substituir, aplicar, remover, importar, limpar tudo | exclusiva |
| restaurar e apagar cópia de segurança | exclusiva |
| gravar `conf.yaml` (comparação de resumo + escrita) e criar o padrão | exclusiva |
| listar perfis, ler um perfil, exportar, listar cópias | compartilhada |
| ler `conf.yaml` para exibir | sem trava (a escrita é atômica por `os.replace`) |
| `konsave --version`, `--help` | sem trava |

A trava **não** é mantida enquanto o usuário decide em um diálogo: ela só existe
dentro da chamada que executa a operação.

## 3. Onde está no código

| Parte | Local |
|---|---|
| Mecanismo (sem dependências) | `konsave/lock.py` |
| Linha de comando original | `konsave/__main__.py` (`command_lock`) |
| Camada do KonGUI | `kongui/core/lock.py` (`EngineLock`, `LockPolicy`, `guarded`) |
| Serviços | `@guarded(...)` em `ProfileService` e `ConfigService`; `KonsaveEngine.call` trava as funções originais que alteram dados (`CALL_LOCK_MODES`) |
| Mensagens da interface | `kongui/gui/messages.py` (`describe_error`) |

A interface **não usa subprocesso** para falar com o Konsave, então não há dupla
aquisição; o `CliRunner` só faz diagnósticos e nada que altere dados.

## 4. Como o conflito aparece

**Linha de comando**

```
Konsave: another Konsave operation is running (apply, pid 1234); waiting up to 30 s (Ctrl+C to give up)...
```

Se acabar o tempo: `Konsave: … Nothing was changed.` e código de saída **75**
(`EX_TEMPFAIL`). Trava inutilizável: código 1. Ctrl+C: 130. Tempo de espera por
`KONSAVE_LOCK_TIMEOUT` (segundos; `0` = não esperar; negativo ou `inf` = sem limite).

**Interface gráfica**

A operação roda em segundo plano (a janela não congela) e, se outro processo
estiver com a trava, **espera** em vez de falhar:

* aparece uma faixa abaixo da barra superior: “Aguardando outra operação do
  Konsave…”, com a explicação e, quando conhecida, a dica (não verificada) de qual
  operação/processo está com a trava;
* o botão **Cancelar espera** da faixa interrompe só a espera: nada é alterado, a
  outra operação não é tocada e aparece o aviso “Espera cancelada”. Depois disso a
  janela volta ao normal e a mesma ação pode ser repetida;
* enquanto espera, a operação conta como “em andamento”: todos os botões que
  alteram dados ficam desabilitados (como em qualquer operação), o cartão do perfil
  envolvido mostra “Aguardando outra operação…”, e fechar a janela é recusado com
  o aviso “Cancele a espera ou aguarde…”;
* se a outra operação terminar, a nossa começa sozinha, a faixa some e o resultado
  aparece como de costume;
* se a espera passar do limite (`LockPolicy.timeout`, 30 s), a operação termina
  com “A outra operação do Konsave … não terminou a tempo. Nada foi alterado”;
* arquivo de trava inutilizável (pasta sem permissão etc.) não é espera: aparece
  logo o erro com o nome do arquivo.

Como funciona por dentro: o controller (`ProfileController`) entrega ao backend um
`threading.Event` de cancelamento e um callback `on_wait` (`configure_lock_wait`);
o callback roda na thread de trabalho e chega à janela por sinal Qt; `cancel_wait()`
só levanta o evento. Quando a operação falha por causa da trava, a lista de perfis
**não** é relida (nada rodou, e releria esperaria pela mesma trava).
A confirmação do usuário (diálogo) acontece **antes** da operação, então a trava
nunca fica segurada enquanto ele decide. O modo demonstração simula outro processo
com `FakeBackend.start_other()` / `finish_other()`.

Limitações da interface: a janela não monitora a trava sozinha, só descobre o
conflito quando o usuário dispara uma ação; leituras em segundo plano
(`inspect_archive`, `probe_export`, que usam o mesmo thread de trabalho) ficam na
fila atrás de uma operação que espera.

## 5. Limitações

* Só programas que usam a trava são protegidos. **Ferramentas externas** (o próprio
  Plasma, editores, outro gerenciador de configurações) ignoram a trava.
* Quem chama `konsave.funcs` diretamente como biblioteca, sem passar pelo
  `__main__` ou pelo KonGUI, não é protegido.
* Não há fila justa (FIFO): quando a trava é liberada, quem tentar primeiro leva.
* Em NFS o `flock` é emulado; não é suportado como configuração de produção.
* Falha fechada: se o arquivo de trava não puder ser aberto, os comandos que usam
  trava (inclusive `--list`) recusam em vez de rodar sem proteção.
* A CLI sai com 75 em conflito, enquanto o Konsave original sai sempre com 0.
* Leitura de `conf.yaml` sem trava pode ver o arquivo anterior à gravação em curso
  (nunca um arquivo pela metade).

## 6. Testes

`tests.test_locking` usa **processos reais** e o `flock` real, em pastas temporárias
e sem tocar na sessão: dois processos disputando; exclusiva × compartilhada;
leitores simultâneos e leitura durante escrita; segunda operação esperando a
primeira; tempo limite e cancelamento; exceção dentro da operação; processo morto
com `SIGKILL`; registro de dono antigo ignorado; pasta sem permissão, diretório ou
link no lugar do arquivo; CLI × CLI, serviço × CLI nos dois sentidos, dois
“KonGUI”; lista de perfis relida depois da espera; primeira execução simultânea;
códigos de saída 75/1/130; reentrância e proibição de promover a trava;
comandos sem trava (`--version`, `--help`) nunca esperam; textos da interface.
`tests.test_gui_lock_wait` cobre a interface: faixa de espera com dica do dono,
janela responsiva durante a espera (temporizador Qt continua disparando), botões
travados, cancelamento (nada alterado, próxima operação normal), fim da espera
quando a outra termina, tempo esgotado, fechar a janela, aviso “Espera cancelada”,
leitura em segundo plano que não parece espera, e os mesmos fluxos com os serviços
reais contra um processo auxiliar que segura o `flock` de verdade.
Os testes antigos (`tests.test_profile_service_integration`, `tests.test_gui_startup`)
foram ajustados apenas para aceitar o arquivo `.kongui.lock` e o módulo
`konsave.lock`.
