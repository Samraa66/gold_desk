# Stage 5 dev results (research 2018-21, validation 2022-23). Spec: results/stage5_h4_spec.md

- research:   n=237 netR=-7.8 PF=0.95 win=37.1% exp=-0.033R ret=-2.1% maxDD=6.7%
- validation: n=132 netR=-6.6 PF=0.92 win=35.6% exp=-0.050R ret=-1.7% maxDD=6.7%
- stress (all dev): n=365 netR=-36.7 PF=0.84 win=35.3% exp=-0.101R ret=-8.9% maxDD=12.9%
- criterion 1: FAIL; criterion 2 counts: PASS

| Year | Trades | Win % | Net R | PF | Max DD % |
|---|---|---|---|---|---|
| 2018 | 59 | 28.8 | -17.9 | 0.56 | 5.0 |
| 2019 | 60 | 36.7 | +0.2 | 1.01 | 2.1 |
| 2020 | 63 | 42.9 | +12.6 | 1.37 | 2.4 |
| 2021 | 55 | 40.0 | -2.8 | 0.91 | 2.3 |
| 2022 | 67 | 28.4 | -14.8 | 0.69 | 4.3 |
| 2023 | 65 | 43.1 | +8.2 | 1.22 | 3.4 |

## Verdict at dev: FAIL. The test years stay unopened.

## Diagnostic (information only): costs
| Costs | n | Net R | PF |
|---|---|---|---|
| zero | 372 | +17.3 | 1.08 |
| spread only | 369 | -6.8 | 0.97 |
| base | 369 | -14.4 | 0.94 |

## Informational: sensitivity (research + validation, base costs)
| Variant | n | Net R | PF |
|---|---|---|---|
| as specified | 369 | -14.4 | 0.94 |
| lookback 10 | 460 | -12.4 | 0.96 |
| lookback 40 | 273 | -7.1 | 0.96 |
| stop 1.5 ATR | 433 | -29.6 | 0.9 |
| stop 3.0 ATR | 295 | +4.7 | 1.03 |
| RR 1.5 | 405 | -24.4 | 0.9 |
| RR 3.0 | 322 | -2.5 | 0.99 |
