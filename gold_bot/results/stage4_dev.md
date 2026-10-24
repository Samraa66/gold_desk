# Stage 4 dev results (research 2018-21, validation 2022-23). Spec: results/stage4_pullback_spec.md

## RR 1.5
- base research:   n=1650 netR=-377.6 PF=0.64 win=35.4% exp=-0.229R ret=-61.3% maxDD=61.6%
- base validation: n=874 netR=-121.7 PF=0.77 win=39.7% exp=-0.139R ret=-26.5% maxDD=26.3%
- stress (all dev): n=2485 netR=-816.5 PF=0.52 win=32.9% exp=-0.329R ret=-87.1% maxDD=87.1%
- criterion 1 (net R>0 and PF>=1.15 in BOTH periods): FAIL; criterion 2 trade counts: PASS

| Year | Trades | Win % | Net R | PF | Max DD % |
|---|---|---|---|---|---|
| 2018 | 385 | 33.2 | -116.6 | 0.56 | 25.5 |
| 2019 | 404 | 31.9 | -132.8 | 0.51 | 28.5 |
| 2020 | 437 | 38.4 | -61.7 | 0.76 | 15.7 |
| 2021 | 424 | 37.5 | -66.5 | 0.74 | 17.3 |
| 2022 | 484 | 42.4 | -44.5 | 0.84 | 11.6 |
| 2023 | 390 | 36.4 | -77.2 | 0.69 | 18.0 |

## RR 2.0
- base research:   n=1595 netR=-393.8 PF=0.63 win=31.5% exp=-0.247R ret=-62.9% maxDD=63.4%
- base validation: n=835 netR=-121.8 PF=0.77 win=35.6% exp=-0.146R ret=-26.5% maxDD=26.3%
- stress (all dev): n=2378 netR=-800.7 PF=0.53 win=29.8% exp=-0.337R ret=-86.6% maxDD=86.6%
- criterion 1 (net R>0 and PF>=1.15 in BOTH periods): FAIL; criterion 2 trade counts: PASS

| Year | Trades | Win % | Net R | PF | Max DD % |
|---|---|---|---|---|---|
| 2018 | 366 | 27.9 | -131.5 | 0.51 | 28.3 |
| 2019 | 395 | 29.4 | -130.8 | 0.53 | 28.3 |
| 2020 | 424 | 33.7 | -67.1 | 0.75 | 17.2 |
| 2021 | 410 | 34.4 | -64.4 | 0.75 | 17.0 |
| 2022 | 459 | 37.3 | -51.7 | 0.82 | 13.1 |
| 2023 | 376 | 33.5 | -70.1 | 0.72 | 16.3 |

## Pick: RR 1.5 (higher base net R over research + validation)
## Verdict at dev: FAIL. The test years stay unopened. Strategy rejected.

## Informational: sensitivity (research + validation, base costs, RR 1.5). One good setting among bad ones = overfit.
| Variant | n | Net R | PF |
|---|---|---|---|
| as specified | 2524 | -499.3 | 0.68 |
| pull EMA 10 | 3349 | -666.5 | 0.68 |
| pull EMA 30 | 2122 | -421.7 | 0.68 |
| swing 5 | 2794 | -596.6 | 0.67 |
| swing 20 | 2146 | -415.4 | 0.68 |
| min stop 0.75 ATR | 2527 | -505.3 | 0.68 |
| min stop 1.5 ATR | 2498 | -491.1 | 0.68 |

## Informational: regimes (terciles at entry, research + validation, base costs)
| Regime | n | Net R | PF |
|---|---|---|---|
| trend strength low | 842 | -171.6 | 0.66 |
| trend strength mid | 840 | -158.8 | 0.69 |
| trend strength high | 842 | -168.8 | 0.69 |
| volatility low | 842 | -239.7 | 0.59 |
| volatility mid | 840 | -186.7 | 0.66 |
| volatility high | 842 | -72.9 | 0.83 |
