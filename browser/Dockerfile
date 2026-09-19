FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY browser/ ./browser/

CMD ["uvicorn", "browser.server:app", "--host", "0.0.0.0", "--port", "8001"]