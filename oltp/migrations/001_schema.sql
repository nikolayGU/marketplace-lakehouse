-- Olist source schema. Column names are kept exactly as the CSV headers ship them, typos
-- included (`lenght`), so a row in Postgres can be diffed against the raw file without a
-- mapping; dbt staging is where they get renamed.
-- Timestamps are naive: the source has no timezone and inventing one would shift every event.
-- Ids are 32-char hex, zip prefixes keep their leading zeros and so must stay text.

create table shop.customers (
    customer_id varchar(32) primary key,
    customer_unique_id varchar(32) not null,
    customer_zip_code_prefix varchar(5) not null,
    customer_city varchar(64) not null,
    customer_state char(2) not null
);

create table shop.sellers (
    seller_id varchar(32) primary key,
    seller_zip_code_prefix varchar(5) not null,
    seller_city varchar(64) not null,
    seller_state char(2) not null
);

create table shop.products (
    product_id varchar(32) primary key,
    product_category_name varchar(64),
    product_name_lenght integer,
    product_description_lenght integer,
    product_photos_qty integer,
    product_weight_g integer,
    product_length_cm integer,
    product_height_cm integer,
    product_width_cm integer
);

create table shop.orders (
    order_id varchar(32) primary key,
    customer_id varchar(32) not null references shop.customers (customer_id),
    order_status varchar(16) not null,
    order_purchase_timestamp timestamp not null,
    order_approved_at timestamp,
    order_delivered_carrier_date timestamp,
    order_delivered_customer_date timestamp,
    order_estimated_delivery_date timestamp not null,
    constraint orders_status_check check (
        order_status in (
            'created', 'approved', 'invoiced', 'processing',
            'shipped', 'delivered', 'canceled', 'unavailable'
        )
    )
);

create table shop.order_items (
    order_id varchar(32) not null references shop.orders (order_id),
    order_item_id integer not null,
    product_id varchar(32) not null references shop.products (product_id),
    seller_id varchar(32) not null references shop.sellers (seller_id),
    shipping_limit_date timestamp not null,
    price numeric(10, 2) not null,
    freight_value numeric(10, 2) not null,
    primary key (order_id, order_item_id)
);

create table shop.payments (
    order_id varchar(32) not null references shop.orders (order_id),
    payment_sequential integer not null,
    payment_type varchar(16) not null,
    payment_installments integer not null,
    payment_value numeric(10, 2) not null,
    primary key (order_id, payment_sequential),
    constraint payments_type_check check (
        payment_type in ('credit_card', 'boleto', 'voucher', 'debit_card', 'not_defined')
    )
);

-- review_id repeats across orders in the source (99 224 rows, 98 410 distinct ids), so the
-- key has to be the pair. Debezium derives the Kafka message key from it, and silver merges on it.
create table shop.reviews (
    review_id varchar(32) not null,
    order_id varchar(32) not null references shop.orders (order_id),
    review_score smallint not null,
    review_comment_title text,
    review_comment_message text,
    review_creation_date timestamp not null,
    review_answer_timestamp timestamp not null,
    primary key (review_id, order_id),
    constraint reviews_score_check check (review_score between 1 and 5)
);

-- Postgres does not index foreign keys on its own; the replayer and dbt both join on these.
create index orders_customer_id_idx on shop.orders (customer_id);
create index orders_purchase_ts_idx on shop.orders (order_purchase_timestamp);
create index order_items_product_id_idx on shop.order_items (product_id);
create index order_items_seller_id_idx on shop.order_items (seller_id);
create index reviews_order_id_idx on shop.reviews (order_id);

-- REPLICA IDENTITY FULL puts the whole pre-image into the WAL, so Debezium emits a populated
-- `before` on update and delete instead of just the key. Costs WAL volume, buys the ability to
-- explain what actually changed in a row. See ADR-018.
alter table shop.customers replica identity full;
alter table shop.sellers replica identity full;
alter table shop.products replica identity full;
alter table shop.orders replica identity full;
alter table shop.order_items replica identity full;
alter table shop.payments replica identity full;
alter table shop.reviews replica identity full;
