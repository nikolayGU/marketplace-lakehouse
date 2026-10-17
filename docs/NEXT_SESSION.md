# Следующая сессия: W3-T02, витрины

Обновлено 17.10.2026. Текст ниже копируется в новую сессию как есть.

```text
Ты агент в репозитории Marketplace Lakehouse (mini). Цель сессии: W3-T02, витрины
mart_daily_sales (инкрементальная, delete+insert по purchase_date), mart_delivery_sla,
mart_seller_performance и макрос safe_divide, по плану docs/planning/08-w3-plan/T02-dbt-marts.md.

Прочитай первым, целиком:
1. AGENTS.md (правила, запреты, формат отчёта) и docs/agent-rules.md.
2. docs/HANDOFF.md: раздел «Состояние на 17.10.2026, конец сессии».
3. docs/planning/08-w3-plan/README.md (протокол исполнителя) и T02-dbt-marts.md.
4. Решения D7, D8, D13 в docs/planning/07-w3-spec.md и D15 в README плана.

Первый шаг, только чтение:
- блок «Вход» T02 с выводом команд;
- аудит рисков плана T02 против текущего кода dbt/ (коммит 59dec70) и живого gold:
  водяной знак mart_daily_sales, атрибуция по D15 (заказы без позиций в unknown), DELETE
  и __dbt_tmp в gold, тест полного пересчёта, что сломает порция реплея;
- план выполнения: шаги, файлы, проверки, что требует моего «ок».
Затем стоп и отчёт. Правки только после моего «ок» на план.

Без отдельного моего «ок» не делай:
- make replay-burst, make replay-start, make replay-live и любой расход бюджета реплея
  (часть B T02 просит порцию 60 с, около 12 виртуальных часов: спроси перед ней);
- make silver и любые записи в silver и bronze; make verify сам вызывает make silver и пишет
  в silver, если в bronze есть снапшоты, которых silver ещё не видел, то есть после реплея;
- изменение настроек Postgres и коннектора Debezium;
- git push, rebase, force-push;
- всё из списка запретов AGENTS.md, в том числе DDL вне миграций, ручные DROP, DELETE,
  TRUNCATE и ослабление тестов или reconcile под результат.

Готово, когда (раздел «Готово, когда» T02):
- make dbt-build код 0, первый прогон строит витрины целиком;
- после порции реплея и merge silver make dbt-build код 0, тест полного пересчёта PASS,
  в soft-deleted Lakekeeper ровно одна новая запись mart_daily_sales__dbt_tmp;
- повтор без новых данных: count(*) и sum(gmv) витрины до и после равны;
- sum(gmv) витрины равен GMV по D8 из lake.silver, запрос и число в описании модели;
- make lint, make test, make dbt-parse зелёные; make verify печатает verify ok;
- коммит dbt: marts and incremental daily sales только после моего «ок» на diff, без push.

Отчёт:
- по каждому утверждению команда и её вывод;
- «не проверено» явно, с командой проверки;
- факт, вывод и гипотеза раздельно;
- virtual_now до и после, потраченный бюджет реплея;
- что затронуто, что ждёт моего решения, git status --short и git diff --stat.
```
