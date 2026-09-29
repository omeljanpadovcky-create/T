# STRICT EDGE buffer +0.05%

Правило для PAPER-тесту:

- **STRICT 4/4:** EDGE проходить тільки якщо **Net Edge > +0.05%**.
- **TRAIN 3/4:** лишається старе правило **Net Edge > 0.00%**, щоб learner збирав навчальні дані.
- Поріг +0.05% застосовується **після** fees + spread + slippage + safety margin.

## Як застосувати

1. Запусти Docker Desktop.
2. Завантаж `PATCH_STRICT_EDGE_005.ps1`.
3. Запусти:

    powershell -ExecutionPolicy Bypass -File .\PATCH_STRICT_EDGE_005.ps1

Скрипт сам пробує знайти активну папку ASTRA через контейнер `myshka-astra`, робить backup `api.py` та `edge.py`, перевіряє Python-синтаксис, rebuild-ить сервіс `astra` і перевіряє `/health`.

## STRICT 4/4

LONG: EMA fast > slow, structure UP, RSI 52–72, volume ratio >= 0.60.

SHORT: EMA fast < slow, structure DOWN, RSI 28–48, volume ratio >= 0.60.

Це PAPER/validation правило, а не гарантія прибутковості.
