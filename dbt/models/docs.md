{% docs purchase_date %}
The date of `order_purchase_timestamp`: business time, shifted by one constant so that the last
purchase of the full Olist history fell on the day of the initial load (`oltp/replayer/load.py`);
the replay has not played all of it, so the data ends earlier. Every date in the marts is a
purchase date, never a processing time.
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
without a delivery date counts as delivered and not on time. The denominator is `delivered`
orders only: an order that is not delivered, even past its estimated date, is in neither part.
{% enddocs %}

{% docs cancellation_rate %}
Cancellation rate: the share of `canceled` orders among all orders whose purchase date falls in
the row: a day, a month, a period, or a seller and month (for a seller: the orders with any
item of the seller, deleted items included).
{% enddocs %}

{% docs review_score %}
Review score: the average `review_score` of reviews that were not removed.
{% enddocs %}

{% docs orders %}
Orders: the number of orders of the period, of every status, canceled and unavailable included.
{% enddocs %}

{% docs freight_share %}
Freight share: the freight of live items of orders that are neither `canceled` nor `unavailable`,
divided by the GMV of the same orders.
{% enddocs %}

{% docs delivered_orders %}
Delivered orders: the number of orders with status `delivered`.
{% enddocs %}

{% docs late_orders %}
Late orders: `delivered` orders whose delivery date is later than the estimated delivery date, by
calendar date. A delivered order without a delivery date is not counted as late.
{% enddocs %}

{% docs avg_delivery_days %}
Average delivery days: the average of `delivery_days`, calendar days from the purchase date to the
delivery date, over `delivered` orders. An order without a delivery date has no value and is left
out of the average.
{% enddocs %}

{% docs name_scopes %}
Same name, different scope. `orders_count` in mart_daily_sales counts orders per seller state, so
an order with sellers in two states counts in both and the sum over states can exceed the orders of
the day; in mart_seller_performance it counts orders per seller, and the sum over sellers can exceed
the number of orders. `freight_value` and `items_count` in fct_orders cover live items of orders
of every status; in mart_daily_sales only the orders counted in GMV, neither `canceled` nor
`unavailable`.
{% enddocs %}
