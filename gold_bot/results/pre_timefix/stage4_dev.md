# Stage 4 dev results (research 2018-21, validation 2022-23). Spec: results/stage4_pullback_spec.md

## RR 1.5
- base research:   n=1728 netR=-398.2 PF=0.64 win=35.2% exp=-0.230R ret=-63.3% maxDD=63.6%
- base validation: n=918 netR=-126.1 PF=0.77 win=39.5% exp=-0.137R ret=-27.3% maxDD=27.1%
- stress (all dev): n=2595 netR=-873.1 PF=0.52 win=32.6% exp=-0.336R ret=-88.8% maxDD=88.8%
- criterion 1 (net R>0 and PF>=1.15 in BOTH periods): FAIL; criterion 2 trade counts: PASS

| Year | Trades | Win % | Net R | PF | Max DD % |
|---|---|---|---|---|---|
| 2018 | 411 | 32.6 | -131.8 | 0.54 | 28.2 |
| 2019 | 430 | 31.2 | -145.7 | 0.51 | 30.7 |
| 2020 | 444 | 39.6 | -48.4 | 0.81 | 13.2 |
| 2021 | 443 | 37.0 | -72.3 | 0.73 | 18.5 |
| 2022 | 507 | 41.8 | -52.5 | 0.82 | 13.4 |
| 2023 | 411 | 36.7 | -73.6 | 0.71 | 17.3 |

## RR 2.0
- base research:   n=1667 netR=-416.1 PF=0.64 win=31.1% exp=-0.250R ret=-64.9% maxDD=65.4%
- base validation: n=870 netR=-126.6 PF=0.78 win=35.2% exp=-0.145R ret=-27.4% maxDD=27.2%
- stress (all dev): n=2478 netR=-853.0 PF=0.53 win=29.4% exp=-0.344R ret=-88.3% maxDD=88.3%
- criterion 1 (net R>0 and PF>=1.15 in BOTH periods): FAIL; criterion 2 trade counts: PASS

| Year | Trades | Win % | Net R | PF | Max DD % |
|---|---|---|---|---|---|
| 2018 | 392 | 27.6 | -144.6 | 0.51 | 30.6 |
| 2019 | 418 | 28.0 | -146.6 | 0.52 | 31.1 |
| 2020 | 426 | 34.5 | -56.0 | 0.79 | 15.3 |
| 2021 | 431 | 33.9 | -68.9 | 0.75 | 17.9 |
| 2022 | 476 | 36.6 | -60.8 | 0.8 | 15.1 |
| 2023 | 394 | 33.5 | -65.8 | 0.75 | 15.4 |

## Pick: RR 1.5 (higher base net R over research + validation)
## Verdict at dev: FAIL. The test years stay unopened. Strategy rejected.

## Informational: sensitivity (research + validation, base costs, RR 1.5). One good setting among bad ones = overfit.
| Variant | n | Net R | PF |
|---|---|---|---|
| as specified | 2646 | -524.3 | 0.69 |
| pull EMA 10 | 3482 | -685.4 | 0.69 |
| pull EMA 30 | 2248 | -450.7 | 0.68 |
| swing 5 | 2919 | -627.9 | 0.67 |
| swing 20 | 2225 | -434.7 | 0.68 |
| min stop 0.75 ATR | 2649 | -530.2 | 0.68 |
| min stop 1.5 ATR | 2621 | -519.1 | 0.68 |

## Informational: regimes (terciles at entry, research + validation, base costs)
| Regime | n | Net R | PF |
|---|---|---|---|
| trend strength low | 882 | -183.1 | 0.66 |
| trend strength mid | 882 | -167.0 | 0.7 |
| trend strength high | 882 | -174.2 | 0.7 |
| volatility low | 882 | -282.3 | 0.56 |
| volatility mid | 882 | -153.2 | 0.73 |
| volatility high | 882 | -88.7 | 0.81 |

## Diagnostic (information only, dev years, RR 1.5): where the loss comes from
| Costs | n | Net R | PF |
|---|---|---|---|
| zero | 2797 | +35.8 | 1.02 |
| spread 0.60 only | 2646 | -323.3 | 0.79 |
| base (0.60 + 0.30) | 2646 | -524.3 | 0.69 |

Average risk is about 5 points, so base costs eat about 0.18 R per trade. Before costs the rule is flat (PF 1.02),
so there is no edge for costs to be taken from. The test years (2024+) were NOT opened: the lock was never created and
`python -m src.run_pullback test --rr 1.5` refuses to run. Variants tried so far: 15.
