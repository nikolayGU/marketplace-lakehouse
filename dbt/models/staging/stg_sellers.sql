select
    seller_id,
    seller_zip_code_prefix,
    seller_city,
    seller_state,
    _is_deleted as is_deleted,
    _updated_at as updated_at
from {{ source('silver', 'sellers') }}
