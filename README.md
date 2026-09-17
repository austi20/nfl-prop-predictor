# NFL Fantasy Projection and Prop Engine

How many fantasy points is a player going to score this week, and how wrong could
that be? The second half of that question is the one that decides a lineup, and a
single projected number throws it away. So this projects a distribution for every
rostered skill player: a projection, a floor, a ceiling, and the probability of a
boom week, ranked into a weekly board.

It runs as a desktop app. A Python service does the modeling and a React front end
in a Tauri shell displays it. Prop pricing and paper trading sit alongside the
fantasy board and carry no real money.

## How this was built

I did not write most of the code in this repository. It was built with AI coding
agents working from specifications I wrote, and I reviewed and redirected the
output as it went.

Mine: deciding what the system should predict and what a good prediction looks
like, choosing the modeling approach and the walk forward backtest design, reading
the outputs and deciding whether to trust them, rejecting changes that made them
worse, and running it.

Not mine: most of the implementation. I can explain what every component does and
why it is there, and I can defend the evaluation. I cannot claim to have written
the internals line by line, so I am saying that here rather than letting someone
find out later.

## What I found

The most useful thing I did on this project was refuse to believe an output.

The first 2026 week one board projected Puka Nacua at **30.4 points with an 0.84
boom probability** in full PPR. Nobody scores 30 points as an expectation. Nothing
in 376 passing tests flagged it, because the aggregate error was fine. The
trailing anchor underneath it was fine too, at roughly 21.

Everything downstream of that anchor was the problem. The regression model was
over projecting elite pass catchers, three separate "good offense" adjustments
were all firing on the same team at once, and the distributions were too tight to
be honest about weekly variance. Pulling every downstream knob into one object and
tuning it against a 2025 backtest brought that projection to **22.5 points and an
0.61 boom probability**, and improved the aggregate numbers at the same time.

## The numbers

2025 backtest, balanced across positions, before and after the calibration layer:

| Metric | Default | Tuned |
|---|---|---|
| Mean absolute error | 5.12 | 4.99 |
| Absolute bias | 0.48 | 0.27 |
| Boom calibration error | 0.047 | 0.044 |
| Bust calibration error | 0.066 | 0.050 |
| Rank correlation | 0.574 | 0.595 |

Rank correlation improved for every position: QB 0.40 to 0.44, RB 0.67 to 0.69,
WR 0.64 to 0.65, TE 0.59 to 0.60. The backtest is 2741 player weeks across all
four positions.

Per stat holdout accuracy, trained on 2015 through 2024 and scored on 2025:

| Position | Stat | n | MAE | Bias |
|---|---|---|---|---|
| QB | passing yards | 692 | 79.35 | +24.82 |
| QB | passing TDs | 692 | 0.96 | +0.09 |
| RB | rushing yards | 1650 | 22.70 | +1.08 |
| RB | carries | 1650 | 4.23 | +0.44 |
| WR and TE | receiving yards | 3979 | 21.47 | +4.39 |
| WR and TE | receptions | 3979 | 1.51 | +0.26 |

That quarterback passing bias of nearly 25 yards per game is the largest known
problem in the model and it is discussed below.

## What I expected and did not get

I expected the situational factors to carry more weight than they do. The project
was built to account for opponent, coaching, rest, usage trend, and weather, and
when the 2025 backtest was allowed to scale each factor independently, two of them
were scaled almost to nothing: rest to 0.02 and usage trend to 0.13. On that
sample they carry close to no predictive signal.

I left both wired up and still visible in the projection breakdown rather than
deleting them, because the sample is one season and the honest statement is "this
did not help here", not "this does not work". But I am not going to claim the app
accounts for rest when the tuning says it effectively does not.

## How it works

Every scoring stat starts from a recency weighted average of the player's last
eight games, then gets regressed toward a positional baseline by `n/(n+4)`, so a
player with three games is pulled hard toward the baseline and a player with thirty
barely moves.

Generalized linear models fit on the training seasons are blended in at a weight of
0.275 rather than trusted outright, and the blended mean is clamped to a band
around the player's own recent form. The clamp exists because the models were fit
on seasons whose scoring environment no longer matches the current one.

On top of that sit multiplicative context factors for opponent matchup, game
script, injuries, usage, rest, coaching, and weather. The three factors that all
measure roughly "this is a good offense" are capped at 1.03x combined, because
before that cap they triple counted the same fact.

A Monte Carlo layer then samples the per stat distributions and applies the
league's scoring rules. That is what produces the floor, the ceiling, and the boom
probability instead of a single number.

Evaluation is walk forward. Training years are 2015 through 2024 and the holdout
year is 2025, and they are kept disjoint. Model defaults came from an ablation grid
scored on the holdout, not from what looked best on the training data.

## The data

Everything comes from [nflverse](https://github.com/nflverse), the public NFL data
project, pulled through `nfl-data-py`:

- Weekly player box scores back to 2015
- Schedules, rosters, and injury reports
- Snap counts and Next Gen Stats air yards share, for usage
- Weather forecasts by stadium, for wind sensitive passing adjustments

One thing about this data is easy to get wrong and worth stating. nflverse
publishes no box scores for the current season until games are actually played,
and it publishes no preseason box scores at all. There is no 2026 player data to
train on in week one. The week one board therefore runs a separate cold start path
built on prior season history plus schedule and roster data, and it should be
judged as its own case rather than lumped in with the in season numbers.

## Running it

Python 3.13 and [uv](https://docs.astral.sh/uv/). The desktop client needs Node.

```bash
uv sync
uv run pytest
```

Run the service and the front end separately during development:

```bash
uv run uvicorn api.server:app --host 127.0.0.1 --port 8000
npm install --prefix desktop
npm run dev --prefix desktop
```

Or run the native window, which spawns the Python service itself:

```bash
npm run tauri dev --prefix desktop
```

Front end tests:

```bash
npm run test --prefix desktop
```

## What would break this

- **The quarterback projections are the weak spot.** The models over project
  passing yards by 24.8 per game against the 2025 holdout. Because the bias on the
  training set is near zero, the model cannot detect this itself. Every QB1
  clusters between 18 and 21 projected points, and thin sample rookies leak into
  that range.
- **The models carry an old scoring environment.** They are fit on seasons with
  more offense than recent ones. The blend weight and the clamp dampen that, they
  do not remove it.
- **Tight end projections now center about 0.6 points low**, a side effect of the
  aggressive correction applied to the tight end model. Error and ranking both
  improved anyway, so I accepted it, but it is a known bias and not noise.
- **Prop backtests use synthetic lines**, not captured historical quotes. Any
  number about prop profitability is therefore about the model against a simulated
  market, not against a real one.
- **The situational factors are tuned on a single season**, so the scalings that
  went near zero could be sample noise rather than a real absence of signal.

## What I would do next

Recalibrate bias and variance against actual 2026 results once enough weeks have
been played, which is the real fix for the quarterback problem and is deliberately
not something to hack in before a season starts. Capture real market quotes to
replace the synthetic prop lines. Re tune the situational factors once there is
more than one season behind them.

## License

MIT.
