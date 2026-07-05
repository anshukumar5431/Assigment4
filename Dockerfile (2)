FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY run.py .
COPY config.yaml .
COPY data.csv .

# run.py itself doesn't hard-code any paths -- the paths just get passed
# in as CLI args here, same way I'd run it locally
CMD ["python", "run.py", "--input", "data.csv", "--config", "config.yaml", "--output", "metrics.json", "--log-file", "run.log"]
