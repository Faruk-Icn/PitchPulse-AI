# Location-only xG model

The Stats Analyst estimates the probability of a goal from shot distance and goal angle. Its coefficients were fitted to **StatsBomb Open Data** for the 2018 men's FIFA World Cup: 1,166 open-play shots for training and 390 from held-out matches for testing. The test Brier score was 0.083839, compared with 0.094956 for a constant-rate baseline. The [training script](../../scripts/train_xg.py) pins the source commit and reproduces the saved coefficients.

This is PitchPulse's own location-only model, not StatsBomb's xG value. It does not account for goalkeeper position, defenders, body part, or shot type. Its calibration outside that tournament has not been measured. Synthetic match shots are treated as open-play shots.

Data source: [StatsBomb Open Data](https://github.com/hudl/open-data). For public visualizations using this model, credit StatsBomb and use its logo from the [official Media Pack](https://statsbomb.com/media-pack/), as requested by the open-data provider.
