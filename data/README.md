# data

- `raw/` (gitignored): full Olist dataset, fetched by `make data`.
- `sample/`: ~2 000 orders with their items, payments, reviews, customers, sellers and products,
  used by unit tests and the smoke workflow. Check the dataset license on Kaggle before
  publishing this folder.
- `checkpoints/` is not here: Spark checkpoints live in object storage.
