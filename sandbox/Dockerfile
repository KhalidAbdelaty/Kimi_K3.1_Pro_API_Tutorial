# Image that runs model-written CadQuery code. It holds no secrets and no reference files.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir cadquery==2.8.0
RUN useradd --create-home --uid 10001 runner
COPY entry.py /sandbox/entry.py
USER runner
WORKDIR /work
ENTRYPOINT ["python", "/sandbox/entry.py"]
