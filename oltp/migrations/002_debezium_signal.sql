-- Debezium signaling table (ADR-019). A row inserted here asks the running connector to do
-- something, e.g. an incremental snapshot of tables whose history Kafka no longer holds.
-- It lives outside `shop` so its topic, oltp.cdc.debezium_signal, stays out of bronze.
-- The connector also writes here: open and close watermarks around every snapshot chunk.

create schema cdc;

create table cdc.debezium_signal (
    id varchar(42) primary key,
    type varchar(32) not null,  -- noqa: RF04, the column names are fixed by Debezium
    data varchar(2048)  -- noqa: RF04
);

-- Signals travel through the WAL like any change, so the table must be published.
alter publication shop_publication add table cdc.debezium_signal;

-- The CDC role's name comes from .env (DEBEZIUM_USER), which plain SQL cannot read; the role is
-- the one non-superuser login with REPLICATION that oltp/init creates.
do $$
declare
    cdc_role name;
begin
    for cdc_role in
        select rolname from pg_roles
        where rolreplication and rolcanlogin and not rolsuper
    loop
        execute format('grant usage on schema cdc to %I', cdc_role);
        execute format('grant select, insert on cdc.debezium_signal to %I', cdc_role);
    end loop;
end
$$;
