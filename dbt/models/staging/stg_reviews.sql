select
    review_id,
    order_id,
    review_score,
    review_comment_title,
    review_comment_message,
    review_creation_date,
    review_answer_timestamp,
    _is_deleted as is_deleted,
    _updated_at as updated_at
from {{ source('silver', 'reviews') }}
