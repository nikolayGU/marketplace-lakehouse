# data

- `raw/` (gitignored): full Olist dataset, fetched by `make data`. 9 CSV files, ~126 MB.
- `sample/`: 2 000 orders with every row they reference (items, payments, reviews, customers,
  products, sellers) plus the category translation file. Referentially closed, so the same
  loader and the same foreign keys work on it. Regenerate with `uv run python
  scripts/make_sample.py`; the order ids are drawn with a fixed seed, so the result is stable.
- `checkpoints/` is not here: Spark checkpoints live in object storage.

## Source and license

Brazilian E-Commerce Public Dataset by Olist, published on Kaggle as
`olistbr/brazilian-ecommerce`, licensed CC BY-NC-SA 4.0. The sample in `sample/` is a subset of
that dataset and carries the same license: attribution to Olist, non-commercial use, share-alike.
