FROM python:3.6-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1

RUN python -m pip install --no-cache-dir \
    tensorflow==1.4.1 \
    numpy==1.13.3 \
    matplotlib==2.1.1

WORKDIR /app
