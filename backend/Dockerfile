FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY backend/requirements.lock /srv/requirements.lock
RUN pip install --no-cache-dir -r requirements.lock && useradd --create-home --uid 10001 records && mkdir /data && chown records:records /data
COPY backend/app /srv/app
COPY backend/migrations /srv/migrations
COPY backend/workflows /srv/workflows
COPY backend/tokenizers /srv/tokenizers
COPY dify/*.system.txt dify/*.user.txt /srv/prompts/
USER records
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
