# OSINT Project Manual

## Startup
To run the complete OSINT stack (Backend API, Workers, Frontend, and local Redis cache), you need to start multiple services. 

*(Note: Your Postgres database is hosted on Supabase Cloud, so it is always running and doesn't need to be started locally).*

### The "One-Liner" Startup Command
You can start everything in the background by copying and pasting this single line into your terminal at the root of the project:

```bash
docker compose up -d redis ; (source .venv/bin/activate && uvicorn app.main:app --port 8000 &) ; (source .venv/bin/activate && celery -A app.tasks worker -l INFO &) ; (source .venv/bin/activate && celery -A app.tasks beat -l INFO &) ; (cd osint-frontend && pnpm dev &)
```

### Line-by-Line Breakdown

```bash
docker compose up -d redis
```
**Start Local Redis**
Starts your local Redis cache (required for Celery workers). *Requires the Docker Desktop app to be open on your Mac.*

```bash
source .venv/bin/activate && uvicorn app.main:app --port 8000 &
```
**Start FastAPI Backend**
Activates your Python virtual environment and starts the FastAPI backend server in the background.

```bash
source .venv/bin/activate && celery -A app.tasks worker -l INFO &
```
**Start Celery Worker**
Activates the virtual environment and starts the Celery worker (for running asynchronous tasks) in the background.

```bash
source .venv/bin/activate && celery -A app.tasks beat -l INFO &
```
**Start Celery Beat Scheduler**
Activates the virtual environment and starts the Celery beat scheduler (for triggering recurring tasks) in the background.

```bash
cd osint-frontend && pnpm dev &
```
**Start Next.js Frontend**
Moves into your frontend folder and starts the Next.js development server in the background.

---

## Shutdown
To stop all the background processes and containers cleanly.

### The "One-Liner" Shutdown Command
Copy and paste this single line into your terminal to kill all background services:

```bash
pkill -f "uvicorn" ; pkill -f "celery" ; pkill -f "next-server" ; pkill -f "pnpm dev" ; docker compose stop
```

### Line-by-Line Breakdown

```bash
pkill -f "uvicorn"
```
**Kill FastAPI Backend**
Finds and forcefully kills the FastAPI backend process.

```bash
pkill -f "celery"
```
**Kill Celery Processes**
Finds and forcefully kills all Celery workers and beat schedulers.

```bash
pkill -f "next-server"
```
**Kill Next.js Server**
Finds and forcefully kills the running Next.js server instance.

```bash
pkill -f "pnpm dev"
```
**Kill Node Dev Process**
Finds and forcefully kills the Node.js process running the frontend development command.

```bash
docker compose stop
```
**Stop Docker Compose Services**
Stops the Redis container spun up by your `docker-compose.yml`.
