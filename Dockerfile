FROM python:3.13-slim

ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# System deps for psycopg2/pg client
RUN apt-get update && apt-get install -y gcc libpq-dev curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Minimal requirements from provided list
# We rely on SQLAlchemy, Alembic (already installed by constraints in environment text),
# but inside container we must install needed ones.
# Since we're constrained to use 'pip' and only listed packages, we pin to those versions.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic
COPY app /app/app
COPY static /app/static

EXPOSE 8080

CMD ["python", "app/main.py"]
