"""FR2: DDL import for Postgres and MySQL, including dialect variations."""

import pytest

from synthetic.ddl import parse_dbt_yaml, parse_ddl
from synthetic.errors import DDLParseError


def test_ecommerce_example(ecommerce_sql):
    s = parse_ddl(ecommerce_sql)
    assert s.table_names == ["customers", "products", "orders", "order_items"]
    customers = s.table("customers")
    assert customers.primary_key == ["id"]
    assert customers.column("email").type == "email" and customers.column("email").unique
    assert customers.column("email").pii and not customers.column("email").nullable
    assert customers.column("first_name").type == "name"
    orders = s.table("orders")
    assert orders.column("customer_id").foreign_key.table == "customers"
    assert orders.column("status").allowed_values == ["placed", "paid", "shipped", "delivered", "refunded"]
    assert orders.column("total_amount").min == 0
    assert any(c.right_column == "ordered_at" and c.op == ">" for c in orders.checks)
    items = s.table("order_items")
    assert items.primary_key == ["order_id", "product_id"]
    assert {c.name for c in items.foreign_keys} == {"order_id", "product_id"}
    q = items.column("quantity")
    assert (q.min, q.max) == (1, 10)
    assert s.warnings == []


POSTGRES_VARIANTS = [
    # table-level PK and named FK constraint, schema-qualified names, IF NOT EXISTS
    """CREATE TABLE IF NOT EXISTS public.users (id bigint NOT NULL, email text, PRIMARY KEY (id));
       CREATE TABLE public.posts (id bigint NOT NULL, user_id bigint NOT NULL, title varchar(200),
         CONSTRAINT posts_pkey PRIMARY KEY (id),
         CONSTRAINT posts_user_fk FOREIGN KEY (user_id) REFERENCES public.users (id) ON DELETE CASCADE);""",
    # pg_dump style: SET statements, ALTER TABLE ... ADD CONSTRAINT
    """SET statement_timeout = 0;
       CREATE TABLE users (id integer NOT NULL, email character varying(255));
       CREATE TABLE posts (id integer NOT NULL, user_id integer, title text);
       ALTER TABLE ONLY users ADD CONSTRAINT users_pkey PRIMARY KEY (id);
       ALTER TABLE ONLY posts ADD CONSTRAINT posts_pkey PRIMARY KEY (id);
       ALTER TABLE ONLY posts ADD CONSTRAINT posts_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id);""",
    # quoted identifiers, uuid keys, inline REFERENCES without a column list
    """CREATE TABLE "users" ("id" uuid PRIMARY KEY, "email" text UNIQUE NOT NULL);
       CREATE TABLE "posts" ("id" uuid PRIMARY KEY, "user_id" uuid NOT NULL REFERENCES "users", "title" text);""",
]


@pytest.mark.parametrize("sql", POSTGRES_VARIANTS)
def test_postgres_variants(sql):
    s = parse_ddl(sql, dialect="postgres")
    assert set(s.table_names) == {"users", "posts"}
    assert s.table("users").primary_key == ["id"]
    assert s.table("posts").primary_key == ["id"]
    fk = s.table("posts").column("user_id").foreign_key
    assert (fk.table, fk.column) == ("users", "id")


MYSQL_VARIANTS = [
    """CREATE TABLE `users` (
         `id` int unsigned NOT NULL AUTO_INCREMENT,
         `email` varchar(255) NOT NULL,
         `is_active` tinyint(1) NOT NULL DEFAULT '1',
         `plan` enum('free','pro','team') NOT NULL DEFAULT 'free',
         `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
         PRIMARY KEY (`id`), UNIQUE KEY `uniq_email` (`email`), KEY `idx_created` (`created_at`)
       ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
       CREATE TABLE `posts` (
         `id` bigint NOT NULL AUTO_INCREMENT, `user_id` int unsigned NOT NULL, `score` decimal(5,2) DEFAULT NULL,
         PRIMARY KEY (`id`), CONSTRAINT `fk_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
         CONSTRAINT `chk_score` CHECK (`score` BETWEEN 0 AND 100)
       ) ENGINE=InnoDB;""",
]


@pytest.mark.parametrize("sql", MYSQL_VARIANTS)
def test_mysql_variants(sql):
    s = parse_ddl(sql, dialect="mysql")
    users = s.table("users")
    assert users.primary_key == ["id"]
    assert users.column("id").min == 0  # unsigned
    assert users.column("is_active").type == "bool"  # tinyint(1)
    assert users.column("plan").allowed_values == ["free", "pro", "team"]
    assert users.column("email").unique and users.column("email").type == "email"
    assert users.column("created_at").type == "datetime"
    posts = s.table("posts")
    assert posts.column("user_id").foreign_key.table == "users"
    score = posts.column("score")
    assert (score.type, score.decimals, score.min, score.max) == ("float", 2, 0, 100)


def test_check_constraint_shapes():
    s = parse_ddl("""CREATE TABLE t (
        id int PRIMARY KEY,
        a int CHECK (a > 0 AND a < 10),
        b numeric(6,2) CHECK (b >= -5),
        c text CHECK (c IN ('x', 'y')),
        d date, e date,
        f text CHECK (length(f) > 3),
        CHECK (e >= d),
        CHECK (5 < a)
    );""")
    t = s.table("t")
    assert (t.column("a").min, t.column("a").max) == (5, 10)
    assert t.column("b").min == -5
    assert t.column("c").type == "category" and t.column("c").allowed_values == ["x", "y"]
    assert any(c.left == "e" and c.right_column == "d" and c.op == ">=" for c in t.checks)
    assert any("too complex" in w for w in s.warnings)  # length(f) > 3 is reported, not silently dropped


def test_postgres_enum_type_and_composite_unique():
    s = parse_ddl("""CREATE TYPE mood AS ENUM ('sad', 'ok', 'happy');
        CREATE TABLE people (id serial PRIMARY KEY, mood mood NOT NULL, team text, badge int,
                             UNIQUE (team, badge));""")
    people = s.table("people")
    assert people.column("mood").allowed_values == ["sad", "ok", "happy"]
    assert people.unique_together == [["team", "badge"]]


def test_unknown_types_and_composite_fk_warn():
    s = parse_ddl("""CREATE TABLE a (x int, y int, data jsonb, PRIMARY KEY (x, y));
        CREATE TABLE b (id int PRIMARY KEY, ax int, ay int, FOREIGN KEY (ax, ay) REFERENCES a (x, y));""")
    assert any("JSON" in w for w in s.warnings)
    assert any("composite foreign key" in w for w in s.warnings)


def test_errors():
    with pytest.raises(DDLParseError) as e:
        parse_ddl("SELECT 1;")
    assert e.value.code == "no_tables_found"
    with pytest.raises(DDLParseError) as e:
        parse_ddl("CREATE TABLE t (id int)", dialect="oracle")
    assert e.value.code == "unsupported_dialect"
    with pytest.raises(DDLParseError) as e:
        parse_ddl("CREATE TABLE o (id int PRIMARY KEY, c int REFERENCES missing (id));")
    assert "not in the schema" in e.value.message


def test_partial_failure_keeps_good_statements():
    s = parse_ddl("CREATE TABLE ok (id int PRIMARY KEY);\nCREATE TABLE bad ((;")
    assert s.table_names == ["ok"]
    assert any("could not be parsed" in w for w in s.warnings)


def test_dbt_schema_yml():
    s = parse_dbt_yaml("""
version: 2
models:
  - name: customers
    columns:
      - name: customer_id
        data_tests: [unique, not_null]
      - name: email
        data_type: varchar
  - name: orders
    columns:
      - name: order_id
        tests: [unique, not_null]
      - name: customer_id
        tests:
          - relationships: {to: "ref('customers')", field: customer_id}
      - name: status
        tests:
          - accepted_values: {values: [placed, shipped, returned]}
""")
    assert s.table("customers").primary_key == ["customer_id"]
    assert s.table("orders").column("customer_id").foreign_key.table == "customers"
    assert s.table("orders").column("status").allowed_values == ["placed", "shipped", "returned"]
    assert s.table("customers").column("email").type == "email"
