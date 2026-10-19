# Следующая сессия: неделя 4, продолжение (W4-T02, W4-T03)

Обновлено 19.10.2026. Текст ниже копируется в новую сессию как есть.

```text
Ты агент в репозитории Marketplace Lakehouse (mini). Неделя 4 идёт по спеке
docs/planning/09-w4-spec.md (версия 0.2, решения W4-D1..D14 приняты владельцем 19.10).
W4-T01a и W4-T01b закоммичены: профиль obs поднят, 7 targets up, Connect с JMX-агентом,
Airflow шлёт StatsD, cadvisor заменён своим container-exporter (ADR-023). Владелец делегировал
исполнение W4 целиком («делай все сам»), кроме запретов ниже.

Прочитай первым, целиком:
1. AGENTS.md и docs/agent-rules.md.
2. docs/HANDOFF.md: «Состояние на 18.10.2026, конец недели 3», «После закрытия недели, 18.10»
   и «19.10, аудит перед W4».
3. docs/planning/09-w4-spec.md: раздел 2 (решения), раздел 3, карточки W4-T02 и W4-T03 и итоги
   W4-T01a, W4-T01b.

Первый шаг, только чтение (начни с make report):
- Сутки наблюдения B6 (W4-D13) идут с 19.10 12:31 UTC при работе от сети: `grep 'Heartbeat
  recovered'` в логе scheduler после этого времени (ожидается пусто), затем
  `airflow dags list-runs <dag> --state failed` по silver_upsert, dbt_build, dq_checks,
  iceberg_maintenance: новых красных после 19.10 12:31 быть не должно. Сон от батареи не
  отключён: если ноутбук был на батарее, это видно по тем же строкам лога.
- `docker stats` всех профилей, targets Prometheus (7 up), `lakehouse_slot_retained_bytes`.

Затем W4-T02 (lag в listener, перезапуск spark-bronze и порция реплея по W4-D10) и W4-T03
(экспорт dq_checks); коммит на карточку после полного make verify при остановленном scheduler
(пауза silver_upsert и iceberg_maintenance, дождаться конца запусков, stop scheduler, make verify,
start, unpause).

Без отдельного «ок» не делай: blast radius из AGENTS.md, реплей сверх W4-D10, правки .env, хуков
и .claude/settings.json, настроек Postgres и коннектора, push, гейты владельца (W4-T07,
Modify-гейт карантина). make silver и chaos-скрипты с run_silver при запущенном scheduler не
запускать до merge_silver (W4-D12).

Отчёт: каждое утверждение командой и выводом; «не проверено» с командой; факт, вывод и гипотеза
раздельно; git status --short и git diff --stat.
```
