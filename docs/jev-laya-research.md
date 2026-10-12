# JEV × Laya — supervised market research (no real orders)

This module is **not Pocket Option market access**. It learns from *public Kraken spot 5-minute candles* (BTC/USDT, ETH/USDT, SOL/USDT). It cannot copy Pocket Option traders or verify OTC settlements.

## Implemented

- `scripts/jev_laya_learning.py`: fetch only closed OHLCV, append historical candles, derive 6 **past-only** indicators, label outcomes using the next closed bar, and split every asset chronologically with a 25-bar purge between train / validation / untouched test.
- Train a small local **multinomial logistic baseline** (not Laya), evaluate on a held-out period, keep its coefficients and evidence report separate from the main JEV bot. Do **not** deploy any predictions to real trade endpoints.
- Generate `build/jev-laya/train.csv`, `validation.csv`, `test.csv` in actual Laya CLI format (`state` and `direction` columns). Each row is a textual indicator summary with labels UP, DOWN, STOP. The text never contains the next bar.
- Scheduled **daily best-effort** GitHub Actions collection and baseline retraining. GitHub cron may be delayed or dropped; this is not a continuously running 24/7 process. Current statistics are public in `data/jev-laya-research.json`.
- Analysis-only UI in Crypto Myshka → Autodemo (distinct from Pocket Option screenshot analysis and from the 1m Kraken paper runner).

### Current limits

The logistic baseline is not a fine-tuned Laya checkpoint, **and neither is a proven trading strategy**. Only a couple days of candles exist on the first run; the daily append grows the sample with time. The held-out window measures *the exact past run*, not a statistically independent live trial. A 92%-payout break-even rate of ~52.08% is only a hypothetical comparison, not a broker quote. Reported binary payouts ignore broker prices, spread, fees and execution. Class STOP is the custom label for small next-bar movements (absolute move below 2 basis points), not an optimal trading action and not a market "tie". The probabilistic classifier is not calibrated; its 66% confidence gate is fixed ahead of test data.

No broker keys, personal screenshots, signals from other traders or account identifiers are read. **No real trade execution**.

## Actually fine-tune Laya

Upstream project: https://github.com/NandhaKishorM/laya

To train **the real Laya checkpoint**, after enough labelled examples have accumulated:

1. Open [JEV Laya Data + Research Baseline workflow](https://github.com/omeljanpadovcky-create/T/actions/workflows/jev-laya-research.yml).
2. Choose `Run workflow`, enable `finetune_laya` (uses GitHub-hosted CPU and may hit duration/usage limits).
3. The optional second job installs `laya==0.3.27` and runs `laya-train` with train.csv and chronological test.csv. Its checkpoint is uploaded as a **private-to-repo Actions artifact**, not automatically loaded by live JEV.
4. Inspect held-out accuracy **and the trade win/loss metric** against basic baselines before considering deployment; merely training the classifier does not prove directional forecasting skill.

For a GPU-hosted experiment, download the `jev-laya-labeled-csv` artifact and run:

```bash
python -m pip install "laya==0.3.27"
laya-train --data train.csv --text-column state --label-column direction \
  --instructions "Classify the next 5-minute Kraken close from past-only indicators." \
  --base english --out ./jev-laya-checkpoint --epochs 4 \
  --eval-data test.csv
```

Use the **untouched** test split only for evaluation. Calibration must come from a separate slice of training data. Keep test examples out of gradient updates. Model sizes and upstream license are controlled by Laya's project. Do not publish weights automatically before tests.

To validate locally:

```bash
python3 scripts/jev_laya_learning.py --self-test
```

To collect current Kraken data and train the **lightweight baseline**:

```bash
python3 scripts/jev_laya_learning.py
```

The baseline is intentionally not connected to Pocket Option BUY/SELL; its research quality gate never authorizes real orders.
