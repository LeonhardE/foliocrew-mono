# Show the selected chart period’s change

Date: 2026-11-22

## Summary

The market chart now shows how much the selected stock or index moved during the displayed period.

## Changes

- Keep the previous trading session’s close as the comparison for 1D. For 1W, 1M, 3M and 1Y, compare
  the first displayed candle’s open with the last displayed candle’s close. The caption names the
  period and the comparison in English, Simplified Chinese and Traditional Chinese.
- Show a dash until usable candles arrive for the selected symbol and period. The latest quoted
  price, chart reference line, index strip, market radar and watchlist keep their daily snapshot.

## Validation

- Web tests cover all five ranges, independent daily summaries, unavailable data and invalid
  endpoints. The market quote, chart reference line and translation suites also passed.
