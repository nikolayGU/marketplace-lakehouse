select
    customer_id,
    customer_unique_id,
    customer_zip_code_prefix,
    customer_city,
    customer_state,
    _is_deleted as is_deleted,
    _updated_at as updated_at
from {{ source('silver', 'customers') }}
