# MLOps Task 0 — Rolling Mean Signal Batch Job

This is my submission for Task 0. It's a small batch job that reads OHLCV
(open/high/low/close/volume) data, computes a rolling mean on `close`,
turns that into a basic up/down signal, and writes out logs + a metrics
file so the run is actually observable and not just a black box.

## What it does, step by step

1. Loads `config.yaml` and checks that `seed`, `window`, and `version` are
   all there and look sane (window has to be an int >= 2, seed has to be an int)
2. Sets the random seed using `numpy.random.seed()` so results are reproducible
3. Reads the input CSV and checks it's actually valid (not empty, not
   corrupt, has a `close` column, etc.)
4. Computes a rolling mean on `close` over `window` rows
   - The first `window - 1` rows don't have a full window of history yet,
     so I left their rolling mean (and signal) as `NaN` on purpose and
     excluded them from `signal_rate`. They're still counted in
     `rows_processed` though, since technically the row was still processed,
     it just doesn't have a signal.
5. Generates the signal itself: `1` if `close` is above its rolling mean,
   `0` if it's below (and `NaN` if there's no rolling mean yet)
6. Writes `metrics.json` (either the success version or an error version)
   and a detailed `run.log`

## Files in here

```
run.py            # the actual script
config.yaml       # seed / window / version
data.csv          # sample OHLCV data (10,000 rows) — swap for the real one if needed
requirements.txt  # pandas, numpy, PyYAML
Dockerfile        # python:3.9-slim based image
README.md         # this file
metrics.json      # example output from a run that worked
run.log           # example log from that same run
```

## Running it locally

```bash
pip install -r requirements.txt

python run.py --input data.csv --config config.yaml \
               --output metrics.json --log-file run.log
```

I didn't hard-code any paths in `run.py` — everything's passed in through
the 4 CLI flags (`--input`, `--config`, `--output`, `--log-file`). That
was mainly so the exact same script works both locally and inside Docker
without me having to change anything.

## Running it with Docker

```bash
docker build -t mlops-task .
docker run --rm mlops-task
```

The image already has `data.csv` and `config.yaml` baked in, and the
`CMD` in the Dockerfile runs the job automatically. It'll print the final
metrics to stdout and also write `metrics.json` + `run.log` inside the
container (at `/app`). Exit code is `0` if it succeeded, non-zero if
something went wrong.

To grab the output files back out of the container after running:

```bash
docker create --name mlops-task-tmp mlops-task
docker cp mlops-task-tmp:/app/metrics.json .
docker cp mlops-task-tmp:/app/run.log .
docker rm mlops-task-tmp
```

## Example metrics.json (success case)

```json
{
  "version": "v1",
  "rows_processed": 10000,
  "metric": "signal_rate",
  "value": 0.4991,
  "latency_ms": 45,
  "seed": 42,
  "status": "success"
}
```

## Example metrics.json (error case)

```json
{
  "version": "v1",
  "status": "error",
  "error_message": "Input CSV is missing required column: 'close'"
}
```

`metrics.json` always gets written no matter what happens, success or
failure — that was one of the requirements I wanted to make sure I
actually hit.

## Errors I handled

- Missing input file
- Empty input file
- Corrupt / unparseable CSV
- Missing `close` column
- Missing or invalid config fields (`seed`, `window`, `version`)
- Basically anything else that throws an unexpected exception during processing

For all of these, the script logs the exception (with the full traceback)
to `run.log`, still writes the error-shaped `metrics.json`, and exits with
a non-zero code so a caller/CI job knows it failed.

## On reproducibility

The seed from `config.yaml` gets set via `numpy.random.seed(seed)` right
at the start, before any processing happens. Since the actual computation
is just deterministic pandas/numpy math on a fixed CSV, running it twice
on the same `data.csv` + `config.yaml` gives the same `signal_rate` and
`rows_processed` every time (I checked this locally by running it a few
times back to back — only `latency_ms` moved around a bit, which makes
sense since that's just wall-clock timing).

## Note on data.csv

The `data.csv` in here is a synthetic 10,000-row OHLCV dataset I generated
myself (same columns as the real thing would have: `timestamp, open,
high, low, close, volume`) just to build and test the pipeline end to
end. If a real dataset gets swapped in before final submission, `run.py`
shouldn't need any changes since it only actually cares about the `close`
column plus the 4 CLI args.
