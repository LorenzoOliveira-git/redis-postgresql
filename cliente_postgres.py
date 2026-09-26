import psycopg2

from config import configuracao_postgres


def conectar():
    return psycopg2.connect(**configuracao_postgres())
