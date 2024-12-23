FROM docker.io/opendevorg/python-base:3.12-bookworm as builder

ENV DEBIAN_FRONTEND=noninteractive
ENV POETRY_HOME=/opt/poetry
ENV POETRY_NO_INTERACTION=1
ENV POETRY_VIRTUALENVS_IN_PROJECT=1
ENV POETRY_VIRTUALENVS_CREATE=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV POETRY_CACHE_DIR=/opt/.cache

RUN apt-get update \
     && apt-get install -y git \
     && apt-get clean \
     && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /poetry-env &&\
    /poetry-env/bin/pip install poetry poetry-dynamic-versioning

COPY . /app
WORKDIR /app

RUN /poetry-env/bin/poetry install

FROM docker.io/opendevorg/python-base:3.12-bookworm as app

COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"
RUN mkdir /config

CMD ["pandaprint", "/config/printers.yaml"]
