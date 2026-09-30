FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# BOT_TOKEN must be provided at runtime (env var), e.g.:
#   docker run -e BOT_TOKEN=123456789:AAH... -d --name otpbot otpbot
CMD ["python", "bot.py"]
