FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml requirements.txt ./
COPY src ./src
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home --uid 10001 bot && mkdir /data && chown bot:bot /data
USER bot
ENV BOT_DATA_DIR=/data
ENTRYPOINT ["python", "-m", "isbn_bot"]
CMD ["run"]
