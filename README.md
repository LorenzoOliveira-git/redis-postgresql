# Redis na prática: cache, filas e idempotência com Python

Projeto de estudo que usa **Redis e PostgreSQL para cadastrar produtos de forma assíncrona**, evitar gravações duplicadas e consultar o andamento de solicitações. Uma interface no terminal permite observar cada etapa sem escrever comandos Python para cada operação.

A proposta é mostrar que Redis pode participar de diferentes soluções para problemas reais: cache de consultas frequentes, armazenamento temporário de solicitações, controle de repetição e consulta rápida de status.

## Contexto e proposta

O ponto de partida foi um exercício sobre a fintech fictícia **FastPix**, cuja API gravava diretamente no PostgreSQL e sofria com picos de conexões, timeouts e solicitações repetidas. A diretriz era retirar a gravação relacional do caminho de recebimento.

Neste repositório, o domínio foi adaptado para **cadastro de produtos**, aproveitando uma aplicação inicial de cache. Não há integração Pix, API HTTP ou aplicativo mobile: `produtor.py` representa a entrada de uma solicitação, e `worker.py` executa o trabalho em outro processo.

As metas de 5.000 transações por segundo e consultas abaixo de 10 ms pertencem ao enunciado original; **não são resultados comprovados deste projeto**.

## O que foi aprendido

- Separar o recebimento de uma solicitação da conclusão do trabalho: `recebido` não significa `concluido`.
- Usar uma fila como buffer para absorver uma diferença temporária entre a velocidade de chegada e a de gravação.
- Manter produtor e worker independentes: o produtor precisa do Redis, mas não abre conexão com PostgreSQL.
- Serializar dicionários com `json.dumps()` e reconstruí-los com `json.loads()`.
- Reutilizar uma conexão PostgreSQL no worker sequencial, em vez de abrir uma por cadastro.
- Combinar `SET NX` no Redis com uma restrição única no PostgreSQL. O primeiro filtra repetições; o segundo protege o efeito da operação.
- Confirmar o produto e o identificador da solicitação na mesma transação, usando `commit()` e `rollback()`.
- Mover uma mensagem para uma lista de processamento antes de gravar, removendo-a somente após a confirmação.
- Distinguir cache, persistência, idempotência e recuperação: resolver um desses pontos não resolve automaticamente os demais.
- Separar configuração e credenciais do código com variáveis de ambiente.

## Como funciona

```text
Menu / produtor
    │
    ├── SET NX EX → reserva temporária da solicitação
    ├── RPUSH → fila:produtos
    └── SET NX → status recebido
                       │
                     worker
                       │
    BLMOVE: fila:produtos → fila:processando
                       │
                 status processando
                       │
          Transação no PostgreSQL:
          1. Registrar id_solicitacao, se for novo
          2. Inserir produto somente para solicitação nova
          3. COMMIT
                       │
                  status concluido
                       │
        LREM → remover de fila:processando
```

### Escrita assíncrona

O produtor aguarda os comandos do Redis, mas não a gravação no PostgreSQL. Aqui, “assíncrono” significa processamento desacoplado por uma fila; o código usa clientes síncronos e não `asyncio`.

O worker usa `BLMOVE` para aguardar trabalho e mover uma mensagem da entrada para processamento em uma operação. O comando está disponível desde Redis 6.2. A espera bloqueia a chamada do worker, sem impedir que outros clientes enfileirem mensagens. [Documentação de BLMOVE](https://redis.io/docs/latest/commands/blmove/).

### Idempotência em duas camadas

Cada solicitação tem um `id_solicitacao`, diferente do `id` numérico do produto. Para repetir uma tentativa, use **o mesmo identificador e os mesmos dados**. Um identificador novo representa outra solicitação.

1. O produtor usa `SET NX EX 60` para reservar o identificador por 60 segundos. Se a chave existir, retorna `aguarde`.
2. No banco, `solicitacoes_processadas.id_solicitacao` é chave primária. O worker usa `ON CONFLICT DO NOTHING RETURNING` para decidir se precisa inserir o produto.
3. A marca no banco e o produto são confirmados juntos. Se a transação falhar, ambos são desfeitos.

A expiração no Redis libera uma nova tentativa, mas não apaga o histórico do PostgreSQL. O efeito de inserção é protegido; a mensagem ainda pode passar pelo worker mais de uma vez. [SET e suas opções](https://redis.io/docs/latest/commands/set/) e [transações no Psycopg](https://www.psycopg.org/docs/connection.html).

### Cache de produtos

Na busca por ID, o menu consulta um hash no Redis. Quando não encontra, consulta o PostgreSQL e armazena `nome` e `preco` por 60 segundos: padrão **cache-aside**. Esse cache só é preenchido pela consulta, não pelo cadastro.

O preço circula no JSON como texto e é convertido para `Decimal` no worker. No banco, é armazenado como `NUMERIC`.

### Status

O produtor cria `recebido` com `NX`, preservando um estado que o worker já tenha escrito. O worker atualiza para `processando` e, após o commit, `concluido`. A consulta usa Redis, sem fallback para o PostgreSQL.

Uma chave ausente retorna `desconhecido`: ela pode não ter sido criada ou já ter expirado. Isso não prova que o produto não existe.

## Estruturas no Redis

| Chave | Tipo | Expiração | Função |
| --- | --- | --- | --- |
| `fila:produtos` | List | Sem TTL | Solicitações aguardando processamento |
| `fila:processando` | List | Sem TTL | Mensagens assumidas e ainda não removidas |
| `solicitacao:{id_solicitacao}` | String | 60 segundos | Reserva temporária para filtrar repetição |
| `status:{id_solicitacao}` | String | 24 horas após cada escrita | Andamento da solicitação |
| `produto:{id_produto}` | Hash | 60 segundos | Cache de nome e preço |

Não ter TTL não significa ter durabilidade garantida: persistência, memória disponível e política de remoção do servidor também importam.

## Tecnologias

- **Python**: menu, produtor, worker e conversão de dados.
- **Redis**: listas, strings, hashes, expiração e operações atômicas individuais.
- **PostgreSQL**: dados definitivos, transações e unicidade de solicitações.
- **redis-py**: cliente Redis (`redis==8.1.0` no projeto; essa é a versão do cliente, não do servidor).
- **psycopg2**: acesso ao PostgreSQL (`2.9.13`).
- **python-dotenv**: carregamento do arquivo `.env`.

## Estrutura do projeto

```text
.
├── README.md
├── .env.example                     # Modelo público de configuração
├── .env                             # Configuração local; não versionar
├── .gitignore                       # Exclui segredos, ambiente virtual e caches
├── requirements.txt                 # Dependências Python
├── config.py                        # Carrega .env e monta configurações
├── cliente_redis.py                 # Cliente Redis reutilizado em cada processo
├── cliente_postgres.py              # Função que abre conexão quando chamada
├── produtor.py                      # Recebe solicitações e consulta status
├── worker.py                        # Consome, grava com idempotência e confirma
├── menu.py                          # Interface de terminal e consultas com cache
└── sql/
    ├── 01_produtos.sql              # Tabela de produtos
    ├── 02_solicitacoes_processadas.sql # Registro permanente de identificadores
    └── 03_dados_exemplo.sql          # Carga inicial opcional
```


## Requisitos

1. Python 3.10 ou superior, compatível com as dependências; o ambiente de desenvolvimento utilizou Python 3.14.
2. Redis **6.2 ou superior**, acessível pela aplicação. Para Windows, pode ser executado em WSL ou em um container. Consulte a [instalação oficial](https://redis.io/docs/latest/operate/oss_and_stack/install/).
3. PostgreSQL instalado, iniciado e um banco criado para o projeto.
4. As **duas tabelas obrigatórias** em `sql/01_produtos.sql` e `sql/02_solicitacoes_processadas.sql` criadas antes de executar o worker.
5. Um editor SQL, como o Query Tool do pgAdmin, ou o cliente `psql`.

A aplicação não instala nem inicia os serviços Redis e PostgreSQL. Use um ambiente local de estudo e uma instância/banco Redis separado de outros projetos, pois os nomes das filas são fixos.

## Instalação e configuração

### 1. Preparar o ambiente Python

Baixe ou clone este repositório e abra um terminal na pasta do projeto.

No Windows/PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

No Linux/macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Copie o modelo apenas na primeira configuração, para não substituir um `.env` já preenchido. Os comandos usam o Python do ambiente virtual diretamente; não é necessário ativá-lo.

### 2. Preencher o `.env`

| Variável | Finalidade |
| --- | --- |
| `POSTGRES_HOST` | Endereço do PostgreSQL; padrão `localhost` |
| `POSTGRES_PORT` | Porta; padrão `5432` |
| `POSTGRES_DB` | Nome do banco existente; obrigatório para conectar |
| `POSTGRES_USER` | Usuário autorizado; obrigatório para conectar |
| `POSTGRES_PASSWORD` | Senha desse usuário; obrigatória para conectar |
| `REDIS_HOST` | Endereço do Redis; padrão `localhost` |
| `REDIS_PORT` | Porta; padrão `6379` |
| `REDIS_DB` | Banco lógico Redis; padrão `0` |
| `REDIS_USERNAME` | Usuário ACL, opcional |
| `REDIS_PASSWORD` | Senha Redis, opcional para ambiente local sem autenticação |

O `.env` é carregado a partir da pasta de `config.py`, independentemente do diretório de execução. Variáveis já definidas no sistema têm prioridade sobre o arquivo. A validação das credenciais PostgreSQL acontece ao conectar, preservando a independência do produtor. [Comportamento do python-dotenv](https://pypi.org/project/python-dotenv/).

Os timeouts continuam no código: 3 segundos para conectar ao Redis, 10 segundos para leitura e 5 segundos de espera no `BLMOVE`. A leitura precisa permitir a espera do comando bloqueante. A conexão PostgreSQL usa limite de 5 segundos.

### 3. Criar o banco e executar os SQLs

Usando um usuário com permissão, crie o banco (uma única vez):

```sql
CREATE DATABASE rediscache;
```

Conecte-se ao banco `rediscache` e execute, nesta ordem:

1. [sql/01_produtos.sql](sql/01_produtos.sql) — obrigatório.
2. [sql/02_solicitacoes_processadas.sql](sql/02_solicitacoes_processadas.sql) — obrigatório.
3. [sql/03_dados_exemplo.sql](sql/03_dados_exemplo.sql) — opcional, com a aplicação parada.

Se preferir `psql`, estes comandos correspondem aos valores locais de exemplo; ajuste host, porta, usuário e banco ao seu `.env`:

```powershell
psql -h localhost -p 5432 -U postgres -d rediscache -v ON_ERROR_STOP=1 -f sql/01_produtos.sql
psql -h localhost -p 5432 -U postgres -d rediscache -v ON_ERROR_STOP=1 -f sql/02_solicitacoes_processadas.sql
psql -h localhost -p 5432 -U postgres -d rediscache -v ON_ERROR_STOP=1 -f sql/03_dados_exemplo.sql
```

O `psql` não carrega automaticamente o `.env`; informe a senha quando solicitada. Os scripts de tabela usam `IF NOT EXISTS`, mas não alteram uma tabela existente com estrutura diferente. O script opcional evita repetir pares nome/preço em execuções sequenciais; não é um mecanismo de unicidade concorrente.

### 4. Executar

No primeiro terminal, inicie o worker:

```powershell
.\.venv\Scripts\python.exe worker.py
```

No segundo terminal, abra o menu:

```powershell
.\.venv\Scripts\python.exe menu.py
```

Em Linux/macOS, substitua o executável por `.venv/bin/python`. Alternativamente, abra o menu em ambos os terminais e escolha **8** em um deles. Essa opção ocupa aquele terminal com o worker; `Ctrl+C` retorna ao menu. Comece com apenas um worker.

Após editar código ou `.env`, reinicie os processos para carregar as alterações.

## Operações do menu

| Opção | Operação |
| --- | --- |
| 1 | Enviar cadastro ou repetir uma solicitação; Enter gera um UUID novo |
| 2 | Consultar status e medir a duração daquela consulta |
| 3 | Buscar por ID numérico do produto, usando cache-aside |
| 4 | Listar até 50 produtos recentes diretamente do PostgreSQL |
| 5 | Listar produtos atualmente no cache |
| 6 | Mostrar tamanho e até 10 mensagens de cada fila, sem consumir |
| 7 | Consultar o tempo restante da reserva de uma solicitação |
| 8 | Executar o worker no terminal atual |
| 0 | Sair |

Para preços, use `19.90` ou `19,90`, sem separador de milhares. O menu aceita valores positivos com até duas casas decimais. Essa validação pertence ao menu; chamadas diretas ao produtor ainda precisam de validação adicional.

## Roteiro para experimentar

### Observar o buffering e os estados

1. Deixe o Redis funcionando e o worker parado.
2. Cadastre pela opção 1 com ID `estudo-001`, nome `Produto de estudo` e preço `19,90`.
3. Consulte o ID pela opção 2: deve aparecer `recebido`.
4. Veja a mensagem na entrada pela opção 6.
5. Inicie o worker em outro terminal. Após a gravação, consulte novamente: `concluido`.
6. Liste os produtos pela opção 4. As filas deverão estar vazias se não houver outras mensagens.

O estado `processando` pode ser rápido demais para observar manualmente.

### Verificar idempotência

1. Repita `estudo-001` com os mesmos dados antes de 60 segundos: espera-se `aguarde`.
2. Use a opção 7 para observar a reserva.
3. Após a expiração, envie novamente o mesmo ID: o produtor pode retornar `recebido`, mas o worker deve indicar solicitação já processada.
4. Confirme que não foi inserido outro produto por essa solicitação.

Não use um UUID novo nesse teste: isso representaria outro cadastro legítimo.

### Experimentar o cache

1. Descubra o ID numérico de um produto pela opção 4.
2. Consulte-o pela opção 3: se o cache estiver vazio, a busca acessa o banco.
3. Repita imediatamente: a busca deve usar Redis.
4. Veja o hash pela opção 5. Após 60 segundos, uma nova busca deverá repopular o cache.

### Observar indisponibilidade em ambiente de estudo

Com o worker parado e o PostgreSQL indisponível, o produtor ainda pode enfileirar se Redis estiver disponível. O worker só inicia depois de conseguir conectar ao PostgreSQL. Uma falha após mover a mensagem pode deixá-la em `fila:processando`; a opção 6 permite inspecionar esse estado, mas **não há recuperação automática implementada**.

Não trate uma fila de entrada vazia como prova de que tudo foi concluído: confira a lista de processamento e os status.

## Limites e próximas evoluções

| Desafio | Situação atual |
| --- | --- |
| Escrita assíncrona e buffer | Implementado entre produtor e worker; sem teste de capacidade |
| Idempotência da inserção | Implementada para o mesmo identificador, enquanto o registro no banco for preservado |
| Resiliência | Parcial: mensagem fica em processamento, mas faltam recuperação e reconexão |
| Status sem consultar banco | Implementado, com expiração e possíveis estados desatualizados |
| Meta de menos de 10 ms | Não validada por benchmark; o menu mostra apenas uma medição pontual |

Pontos que fazem parte do aprendizado e ainda precisam evoluir:

- **Reserva e enfileiramento são comandos separados.** Uma falha entre `SET NX` e `RPUSH` pode bloquear uma solicitação não enfileirada até a reserva expirar. Expiração não provoca reenvio automático.
- **Erros de rede podem ter resultado incerto.** Um comando pode ter sido aplicado sem sua resposta chegar. `recebimento_nao_confirmado` pede uma nova tentativa com o mesmo ID, após a espera; não prova ausência da mensagem.
- **Banco e status não compartilham uma transação.** O commit pode funcionar e a escrita de `concluido` falhar. A mensagem pode permanecer pendente e o status ficar desatualizado. Uma repetição também pode passar temporariamente de `concluido` para `processando`.
- **O worker pode encerrar por erro.** Faltam reconexão, tentativas com intervalo, recuperação de pendências e tratamento separado de mensagens inválidas. Reiniciar não recupera automaticamente a lista de processamento.
- **Redis precisa de configuração operacional.** O projeto não configura persistência, replicação, limites de memória ou política de eviction. AOF/RDB devem ser estudados e testados; por exemplo, AOF com sincronização a cada segundo ainda admite uma janela de perda. Veja a [documentação de persistência](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/).
- **Cache e fila dividem a mesma instância neste laboratório.** Em uma evolução, avalie separar cargas e políticas: perder cache pode ser tolerável; perder trabalho pendente pode não ser.
- **O conteúdo não é comparado para um ID repetido.** Enviar outro produto com um ID antigo não gera um erro de conflito de payload: o cadastro pode ser ignorado. Uma evolução é registrar e comparar uma assinatura dos dados.
- **Não existe controle de crescimento da fila**, garantia de 5.000 TPS, fila de mensagens com falha definitiva, API HTTP, TLS configurado nos clientes ou integração de pagamento real.
- **O cache pode ficar desatualizado até expirar** se um produto for alterado diretamente no banco. Não há fluxo de atualização/invalidação implementado.

## Guia de estudo

1. **Strings, hashes e TTL:** leia `cliente_redis.py` e as consultas do menu. Experimente as opções 3, 5 e 7; explique por que reserva, status e cache têm prazos diferentes.
2. **Produtor e consumidor:** leia `produtor.py` e `executar_worker()`. Cadastre com o worker parado e observe a fila. Estude [listas Redis](https://redis.io/docs/latest/develop/data-types/lists/).
3. **Idempotência e transações:** acompanhe `gravar_produto()`, os dois SQLs de tabela e o teste de repetição. Pergunte o que aconteceria com dois commits separados.
4. **Falhas entre etapas:** desenhe onde cada informação permanece se o processo cair antes/depois do commit. Estude [BLMOVE](https://redis.io/docs/latest/commands/blmove/) e [LREM](https://redis.io/docs/latest/commands/lrem/).
5. **Durabilidade e recuperação:** estude AOF/RDB, recuperação de pendências e política de memória. Como evolução, compare listas com [Redis Streams](https://redis.io/docs/latest/develop/data-types/streams/).
6. **Medição:** diferencie uma consulta isolada de testes sob carga. Meça percentis de latência, taxa de processamento, tamanho da fila e tempo de espera antes de afirmar metas de desempenho.

## Problemas comuns

| Sintoma | Verificação |
| --- | --- |
| `ModuleNotFoundError` | Instale as dependências com o Python da `.venv` usada para executar |
| Falha ao instalar `psycopg2` | A distribuição pode exigir compilador e bibliotecas de desenvolvimento do PostgreSQL; veja a [instalação do Psycopg](https://www.psycopg.org/docs/install.html) |
| Conexão recusada | Confira serviço iniciado, host, porta e acesso de rede |
| Variável obrigatória ausente | Copie e preencha `.env`; confira se o nome não ficou `.env.txt` |
| `relation ... does not exist` | Execute os dois SQLs obrigatórios no banco definido em `POSTGRES_DB` |
| `unknown command BLMOVE` | Confira a versão do servidor Redis: precisa ser 6.2+ |
| Timeout no worker ocioso | Preserve o timeout de leitura Redis maior que os 5s de espera do `BLMOVE` |
| `desconhecido` | Confira o mesmo ID, worker reiniciado, expiração e banco lógico Redis |
| `aguarde` | A reserva ainda existe; consulte a opção 7 |
| `processando` não muda | Inspecione erro do worker e lista de processamento; não há retomada automática |
| Alterar `.env` não muda conexão | Reinicie processos e confira variáveis do sistema, que têm prioridade |

## Preparação para publicar no GitHub

- Versione `.env.example`, os scripts SQL, o código, `requirements.txt` e este README.
- Não publique `.env`, `.venv`, caches, dumps ou credenciais reais. O `.gitignore` cobre esses arquivos locais comuns.
- Se um segredo já foi commitado, `.gitignore` não o remove do histórico. Troque a credencial exposta e trate o histórico antes de publicar.
- Escolha uma licença de uso antes de incentivar redistribuição; nenhuma licença foi presumida neste projeto.
- Como próximo incremento do portfólio, adicione testes de integração em ambiente isolado e um roteiro reproduzível de falhas. Depois, automatize a infraestrutura local e implemente a recuperação de pendências.

O objetivo deste repositório é tornar as decisões visíveis: **quando usar Redis, qual problema cada estrutura resolve e quais garantias ainda dependem do banco e da operação do sistema**.
