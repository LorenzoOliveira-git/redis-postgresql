import json

from cliente_redis import cliente

from cliente_postgres import conectar

from decimal import Decimal

import psycopg2


def gravar_produto(conn, produto):
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO solicitacoes_processadas (id_solicitacao)
                VALUES (%s)
                ON CONFLICT (id_solicitacao) DO NOTHING
                RETURNING id_solicitacao
                """,
                (produto["id_solicitacao"],),
            )

            nova_solicitacao = cursor.fetchone()

            if nova_solicitacao is not None:
                cursor.execute(
                    """
                    INSERT INTO produtos (nome, preco)
                    VALUES (%s, %s)
                    """,
                    (
                        produto["nome"],
                        Decimal(produto["preco"]),
                    ),
                )

        conn.commit()
        return nova_solicitacao is not None

    except psycopg2.Error:
        conn.rollback()
        raise

def executar_worker():
    conn = conectar()

    try:
        while True:
            mensagem = cliente.blmove(
                "fila:produtos",
                "fila:processando",
                timeout=5,
                src="LEFT",
                dest="RIGHT",
            )

            if mensagem is None:
                continue

            produto = json.loads(mensagem)
            chave_status = f"status:{produto['id_solicitacao']}"

            cliente.set(chave_status, "processando", ex=86400)

            inseriu = gravar_produto(conn, produto)

            cliente.set(chave_status, "concluido", ex=86400)

            cliente.lrem("fila:processando", 1, mensagem)

            if inseriu:
                print("Produto gravado:", produto["nome"])
            else:
                print("Solicitação já processada:", produto["id_solicitacao"])

    finally:
        conn.close()


if __name__ == "__main__":
    executar_worker()