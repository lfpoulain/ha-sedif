FROM mcr.microsoft.com/playwright/python:v1.57.0-jammy

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY sedif_scraper.py addon_runner.py ./

CMD ["python", "-u", "/app/addon_runner.py"]
