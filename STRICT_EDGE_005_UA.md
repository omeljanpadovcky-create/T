# STRICT EDGE buffer +0.05%

Поточне PAPER/validation правило:

- **STRICT 4/4:** сервер ASTRA відкидає кандидат, якщо **Net Edge <= +0.05%**.
- **TRAIN 3/4:** додатковий STRICT-поріг не застосовується; лишається поточне навчальне EDGE-правило.
- `Net Edge` уже рахується після modeled costs: fee + spread + slippage + safety margin.

## Чому патч стоїть у `api.py`

Фільтр спрацьовує **відразу після `check_edge(...)` і до JEV, signal lock, sizing, Astra Guard та PAPER ENTER**. Тобто старий сервер не зможе відкрити STRICT paper-позицію з Net Edge, наприклад, `+0.03%`.

Ця версія не змінює `edge.py`, тому не дублює safety margin і менше залежить від версії EDGE-модуля.

## Як застосувати

1. Запусти Docker Desktop і ASTRA.
2. Завантаж `PATCH_STRICT_EDGE_005.ps1`.
3. Запусти:

    powershell -ExecutionPolicy Bypass -File .\PATCH_STRICT_EDGE_005.ps1

Скрипт:
- знаходить активну папку ASTRA через контейнер `myshka-astra`;
- робить backup `api.py`;
- додає server-side STRICT guard;
- запускає `python -m py_compile api.py`;
- rebuild-ить `astra`;
- перевіряє `http://127.0.0.1:8088/health`.

## STRICT 4/4

LONG: EMA fast > slow, structure UP, RSI 52–72, volume ratio >= 0.60.

SHORT: EMA fast < slow, structure DOWN, RSI 28–48, volume ratio >= 0.60.

Поріг можна пізніше A/B-тестувати як `+0.05%` проти `+0.10%`; зараз default — **+0.05%**.
