# Tiny app-layer image (T09, OS-2): the contracts and their compiler, so an application tier outside
# Databricks can validate payloads against the same rules the pipeline enforces. Runs from source, as the
# compiler finds contracts/ next to src/. Synthetic data only.
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "pyyaml==6.0.3"
COPY src ./src
COPY contracts ./contracts
ENV PYTHONPATH=/app/src
CMD ["python", "-m", "meridian.contracts.compiler"]
