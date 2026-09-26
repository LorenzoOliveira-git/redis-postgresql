"""Configuração local; variáveis do ambiente têm prioridade sobre o .env."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)


def obrigatoria(nome):
    valor = os.getenv(nome)
    if not valor:
        raise ValueError(f"Configure {nome} no .env ou no ambiente.")
    return valor


def configuracao_postgres():
    # Validação adiada: importar o produtor não exige credenciais do PostgreSQL.
    return {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "database": obrigatoria("POSTGRES_DB"),
        "user": obrigatoria("POSTGRES_USER"),
        "password": obrigatoria("POSTGRES_PASSWORD"),
        "connect_timeout": 5,
    }


def configuracao_redis():
    return {
        "host": os.getenv("REDIS_HOST", "localhost"),
        "port": int(os.getenv("REDIS_PORT", "6379")),
        "db": int(os.getenv("REDIS_DB", "0")),
        "username": os.getenv("REDIS_USERNAME") or None,
        "password": os.getenv("REDIS_PASSWORD") or None,
        "decode_responses": True,
        "socket_connect_timeout": 3,
        "socket_timeout": 10,
    }
