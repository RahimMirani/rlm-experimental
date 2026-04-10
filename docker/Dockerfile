FROM python:3.12-slim

WORKDIR /app

# Install litellm and python-dotenv
RUN pip install --no-cache-dir litellm python-dotenv

# Copy the REPL script
COPY rlm/repl/rlm_repl.py /app/rlm_repl.py

ENTRYPOINT ["python", "/app/rlm_repl.py"]
