# Stage 5 dev results (research 2018-21, validation 2022-23). Spec: results/stage5_h4_spec.md

- research:   n=245 netR=-12.2 PF=0.92 win=35.9% exp=-0.050R ret=-3.1% maxDD=6.7%
- validation: n=122 netR=+14.4 PF=1.2 win=41.0% exp=+0.118R ret=3.6% maxDD=3.4%
- stress (all dev): n=366 netR=-13.9 PF=0.94 win=36.9% exp=-0.038R ret=-3.6% maxDD=8.1%
- criterion 1: FAIL; criterion 2 counts: PASS

| Year | Trades | Win % | Net R | PF | Max DD % |
|---|---|---|---|---|---|
| 2018 | 59 | 30.5 | -15.9 | 0.6 | 4.5 |
| 2019 | 63 | 33.3 | -4.3 | 0.9 | 2.6 |
| 2020 | 66 | 39.4 | +5.9 | 1.15 | 2.3 |
| 2021 | 57 | 40.4 | +2.0 | 1.07 | 1.8 |
| 2022 | 62 | 35.5 | -1.2 | 0.97 | 2.1 |
| 2023 | 60 | 46.7 | +15.6 | 1.49 | 2.2 |

## Verdict at dev: FAIL. The test years stay unopened.

## Diagnostic (information only): costs
| Costs | n | Net R | PF |
|---|---|---|---|
| zero | 379 | +23.3 | 1.11 |
| spread only | 367 | +9.8 | 1.04 |
| base | 367 | +2.2 | 1.01 |

## Informational: sensitivity (research + validation, base costs)
| Variant | n | Net R | PF |
|---|---|---|---|
| as specified | 367 | +2.2 | 1.01 |
| lookback 10 | 468 | -19.1 | 0.93 |
| lookback 40 | 276 | -0.3 | 1.0 |
| stop 1.5 ATR | 437 | -14.5 | 0.95 |
| stop 3.0 ATR | 295 | +4.4 | 1.03 |
| RR 1.5 | 414 | -12.9 | 0.95 |
| RR 3.0 | 322 | +0.3 | 1.0 |

## Reading
Research PF 0.92 (net -12 R), validation PF 1.20 (net +14 R): the criterion was PF >= 1.15 in BOTH, so FAIL. Costs matter little
here (zero cost PF 1.11, base 1.01): the signal itself is close to a coin flip. Test years (2024+) never opened (no lock file).
Variants tried so far: 16. The frozen rule now runs as a forward call log (src/paper_calls.py).
