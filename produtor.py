import json
import redis

from cliente_redis import cliente


def receber_produto(id_solicitacao, nome, preco):
    produto = {
        "id_solicitacao": id_solicitacao,
        "nome": nome,
        "preco": str(preco),
    }

    mensagem = json.dumps(produto)
    chave = f"solicitacao:{id_solicitacao}"

    try:
        criou = cliente.set(chave, "reservada", nx=True, ex=60)

        if not criou:
            return {
                "id_solicitacao": id_solicitacao,
                "status": "aguarde",
                "tentar_novamente_em_segundos": 60,
            }

        cliente.rpush("fila:produtos", mensagem)

        cliente.set(
            f"status:{id_solicitacao}",
            "recebido",
            nx=True,
            ex=86400,
        )

    except redis.exceptions.RedisError:
        # A marca, se foi criada, permanece até expirar.
        return {
            "id_solicitacao": id_solicitacao,
            "status": "recebimento_nao_confirmado",
            "tentar_novamente_em_segundos": 60,
        }

    return {
        "id_solicitacao": id_solicitacao,
        "status": "recebido",
    }

def consultar_status(id_solicitacao):
    status = cliente.get(f"status:{id_solicitacao}")

    return {
        "id_solicitacao": id_solicitacao,
        "status": status if status is not None else "desconhecido",
    }