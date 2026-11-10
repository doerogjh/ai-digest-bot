FROM python:3.12-slim

RUN useradd -m -u 1000 user && mkdir -p /data && chown user:user /data
WORKDIR /home/user/app

COPY --chown=user:user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user:user . .
USER user

ENV PORT=7860 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

CMD ["python", "bot.py"]
