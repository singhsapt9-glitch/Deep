FROM python:3.11-slim
RUN apt-get update && apt-get install -y espeak-ng && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements_bank_guard.txt
EXPOSE 7860
CMD ["python", "bank_guard_ai_hardened.py"]
