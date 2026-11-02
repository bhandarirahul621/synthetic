-- Example e-commerce schema (Postgres dialect).
-- Try: synthetic generate --schema examples/ecommerce.sql \
--        --rows customers=2000,orders=50000 --seed 42 --out ./out --format parquet

CREATE TYPE order_status AS ENUM ('placed', 'paid', 'shipped', 'delivered', 'refunded');

CREATE TABLE customers (
    id           SERIAL PRIMARY KEY,
    email        VARCHAR(255) NOT NULL UNIQUE,
    first_name   VARCHAR(80)  NOT NULL,
    last_name    VARCHAR(80)  NOT NULL,
    phone        VARCHAR(32),
    city         VARCHAR(80),
    country      VARCHAR(80),
    segment      VARCHAR(20)  NOT NULL,
    created_at   TIMESTAMP    NOT NULL
);

CREATE TABLE products (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(120) NOT NULL,
    category     VARCHAR(40)  NOT NULL CHECK (category IN ('electronics', 'home', 'outdoors', 'apparel', 'kitchen')),
    price        NUMERIC(10, 2) NOT NULL CHECK (price > 0 AND price <= 2000),
    is_active    BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE orders (
    id             BIGSERIAL PRIMARY KEY,
    customer_id    INT NOT NULL REFERENCES customers (id),
    status         order_status NOT NULL,
    currency       CHAR(3) NOT NULL,
    total_amount   NUMERIC(12, 2) NOT NULL CHECK (total_amount >= 0),
    is_fraud       BOOLEAN NOT NULL DEFAULT FALSE,
    ordered_at     TIMESTAMP NOT NULL,
    shipped_at     TIMESTAMP,
    CONSTRAINT shipped_after_ordered CHECK (shipped_at > ordered_at)
);

CREATE TABLE order_items (
    order_id     BIGINT NOT NULL,
    product_id   INT NOT NULL,
    quantity     INT NOT NULL CHECK (quantity BETWEEN 1 AND 10),
    unit_price   NUMERIC(10, 2) NOT NULL CHECK (unit_price > 0),
    PRIMARY KEY (order_id, product_id),
    CONSTRAINT fk_items_order   FOREIGN KEY (order_id)   REFERENCES orders (id),
    CONSTRAINT fk_items_product FOREIGN KEY (product_id) REFERENCES products (id)
);
