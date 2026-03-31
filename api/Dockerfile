FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Initialize git repo if it doesn't exist, then start gunicorn
# --workers 1 --threads 4: keeps git writes serialized via threading.Lock
ENTRYPOINT ["sh", "-c", \
    "python -c 'from git_manager import GitManager; import os; GitManager(os.environ.get(\"GIT_REPO_PATH\", \"/var/cmdb/repo\"), os.environ.get(\"GIT_USER_NAME\", \"CMDB API\"), os.environ.get(\"GIT_USER_EMAIL\", \"cmdb@localhost\"))' \
    && exec gunicorn --bind 0.0.0.0:5000 --workers 1 --threads 4 --timeout 60 app:app"]
