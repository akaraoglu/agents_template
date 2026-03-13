FROM pytorch/pytorch:2.10.0-cuda13.0-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-venv \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-extra.txt /opt/openclaw/requirements-extra.txt

RUN mkdir -p /opt/openclaw/wheels \
    && python3 -m pip download --dest /opt/openclaw/wheels -r /opt/openclaw/requirements-extra.txt
