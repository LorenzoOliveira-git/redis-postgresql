import json
from contextlib import closing
from decimal import Decimal, InvalidOperation
from time import perf_counter
from uuid import uuid4

import psycopg2
import redis

from cliente_postgres import conectar
from cliente_redis import cliente
from produtor import consultar_status, receber_produto
from worker import executar_worker

CACHE_TTL = 60


def ler_texto(pergunta):
    valor = input(pergunta).strip()
    if not valor:
        raise ValueError("O campo não pode ficar vazio.")
    return valor


def cadastrar_produto():
    print("Para repetir uma solicitação, use o mesmo ID e os mesmos dados.")
    identificador = input("ID da solicitação (Enter para gerar): ").strip() or str(uuid4())
    nome = ler_texto("Nome: ")
    preco = Decimal(ler_texto("Preço (ex.: 19,90): ").replace(",", "."))
    if not preco.is_finite() or preco <= 0:
        raise ValueError("Preço deve ser positivo e finito.")
    if preco.as_tuple().exponent < -2:
        raise ValueError("Use no máximo duas casas decimais.")
    print("Guarde o ID para consultar ou repetir:", identificador)
    print(json.dumps(receber_produto(identificador, nome, format(preco, ".2f")), ensure_ascii=False, indent=2))


def mostrar_status():
    identificador = ler_texto("ID da solicitação: ")
    inicio = perf_counter()
    resultado = consultar_status(identificador)
    tempo = (perf_counter() - inicio) * 1000
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    print(f"Tempo desta consulta: {tempo:.2f} ms (medição pontual).")


def buscar_produto(id_produto):
    chave = f"produto:{id_produto}"
    produto = cliente.hgetall(chave)
    if produto:
        print("Produto carregado do cache Redis.")
    else:
        with closing(conectar()) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT nome, preco FROM produtos WHERE id = %s", (id_produto,))
                resultado = cursor.fetchone()
        if resultado is None:
            print("Produto não encontrado.")
            return
        nome, preco = resultado
        produto = {"nome": nome, "preco": str(preco)}
        with cliente.pipeline() as pipe:
            pipe.hset(chave, mapping=produto)
            pipe.expire(chave, CACHE_TTL)
            pipe.execute()
        print(f"Consultado no PostgreSQL e salvo no cache por {CACHE_TTL}s.")
    print(f"Produto: {produto['nome']} - R$ {Decimal(produto['preco']):.2f}")


def consultar_produto():
    identificador = int(ler_texto("ID numérico do produto: "))
    if identificador <= 0:
        raise ValueError("O ID deve ser positivo.")
    buscar_produto(identificador)


def listar_produtos():
    with closing(conectar()) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, nome, preco FROM produtos ORDER BY id DESC LIMIT 50")
            produtos = cursor.fetchall()
    print("Até 50 produtos mais recentes:")
    for identificador, nome, preco in produtos:
        print(f"{identificador} | {nome} | R$ {preco:.2f}")
    if not produtos:
        print("Nenhum produto cadastrado.")


def listar_chaves_produtos():
    encontrou = False
    for chave in cliente.scan_iter(match="produto:*", count=100):
        produto = cliente.hgetall(chave)
        if produto:
            encontrou = True
            print(chave, produto)
    if not encontrou:
        print("Nenhum produto no cache.")


def mostrar_filas():
    for chave in ("fila:produtos", "fila:processando"):
        print(f"\n{chave}: {cliente.llen(chave)} mensagem(ns)")
        for mensagem in cliente.lrange(chave, 0, 9):
            print(" ", mensagem)
    print("Até 10 mensagens por lista, sem removê-las.")


def mostrar_reserva():
    identificador = ler_texto("ID da solicitação: ")
    ttl = cliente.ttl(f"solicitacao:{identificador}")
    if ttl == -2:
        print("Sem reserva no Redis. O banco ainda protege solicitações já processadas.")
    elif ttl == -1:
        print("Reserva sem expiração.")
    else:
        print(f"A reserva expira em aproximadamente {ttl} segundo(s).")


def rodar_worker():
    print("Worker neste terminal. Abra o menu em outro terminal para enviar produtos.")
    print("Ctrl+C volta ao menu. Mensagens pendentes não são recuperadas automaticamente.")
    try:
        executar_worker()
    except KeyboardInterrupt:
        print("\nWorker interrompido.")


def menu():
    opcoes = {
        "1": cadastrar_produto,
        "2": mostrar_status,
        "3": consultar_produto,
        "4": listar_produtos,
        "5": listar_chaves_produtos,
        "6": mostrar_filas,
        "7": mostrar_reserva,
        "8": rodar_worker,
    }
    try:
        while True:
            print("""
=== PRODUTOS — REDIS E POSTGRESQL ===
1 - Enviar cadastro / repetir solicitação
2 - Consultar status da solicitação
3 - Buscar produto por ID (com cache)
4 - Listar últimos produtos no PostgreSQL
5 - Listar produtos presentes no cache
6 - Ver filas de entrada e processamento
7 - Consultar expiração da reserva
8 - Executar worker neste terminal
0 - Sair
""")
            opcao = input("Escolha: ").strip()
            if opcao == "0":
                break
            acao = opcoes.get(opcao)
            if acao is None:
                print("Opção inválida.")
                continue
            try:
                acao()
            except (ValueError, InvalidOperation) as erro:
                print(f"Entrada inválida: {erro}")
            except redis.exceptions.RedisError as erro:
                print(f"Falha no Redis: {erro}")
            except psycopg2.Error as erro:
                print(f"Falha no PostgreSQL: {erro}")
    except (KeyboardInterrupt, EOFError):
        print("\nEncerrando o menu.")
    finally:
        cliente.close()


if __name__ == "__main__":
    menu()
