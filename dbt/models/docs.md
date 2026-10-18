{% docs purchase_date %}
The date of `order_purchase_timestamp`: business time, shifted so that the last day of the
dataset is "today". Every date in the marts is a purchase date, never a processing time.
{% enddocs %}

{% docs gmv %}
GMV: the sum of `price` over live (not deleted) items of orders whose status is neither
`canceled` nor `unavailable`. Freight is a separate metric, `freight_value`.
{% enddocs %}

{% docs aov %}
AOV: GMV divided by the number of orders that are neither `canceled` nor `unavailable` and have at
least one live item.
{% enddocs %}

{% docs canceled_gmv %}
Canceled GMV: the sum of `price` over every item of `canceled` orders, deleted items included
(the replayer deletes the items of an order canceled before shipping).
{% enddocs %}

{% docs on_time_rate %}
On-time rate: the share of `delivered` orders with
`date(order_delivered_customer_date) <= date(order_estimated_delivery_date)`. A delivered order
without a delivery date counts as delivered and not on time.
{% enddocs %}

{% docs cancellation_rate %}
Cancellation rate: the share of `canceled` orders among all orders of the same purchase date
(in mart_seller_performance: of the same seller and purchase month).
{% enddocs %}

{% docs review_score %}
Review score: the average `review_score` of reviews that were not removed.
{% enddocs %}
