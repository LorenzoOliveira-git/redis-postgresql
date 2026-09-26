-- Opcional, para uso local com a aplicação parada.
INSERT INTO produtos (nome, preco)
SELECT exemplo.nome, exemplo.preco
FROM (VALUES
    ('Teclado Mecânico RGB', 249.90),
    ('Mouse Gamer', 129.50),
    ('Monitor 27''', 1049.00),
    ('Notebook i7 16GB', 3850.00),
    ('Headset USB', 199.99),
    ('Cadeira Gamer', 899.90),
    ('Webcam Full HD', 299.00)
) AS exemplo(nome, preco)
WHERE NOT EXISTS (
    SELECT 1 FROM produtos p
    WHERE p.nome = exemplo.nome AND p.preco = exemplo.preco
);
