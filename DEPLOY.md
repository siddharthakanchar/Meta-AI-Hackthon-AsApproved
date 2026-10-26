# Deploying the hosted demo

The hosted demo runs **cache-only**: it reads `data/runs/` and never calls an
API. That is deliberate — a live demo that depends on a model call can fail for
latency, a rate limit or an exhausted credit, and none of those are debuggable
while a judge is watching.

## Streamlit Community Cloud (3 minutes)

1. Push the repo to GitHub (public).
2. Go to **share.streamlit.io** → *New app*.
3. Repository `siddharthakvss/asapproved`, branch `main`,
   main file **`app/streamlit_app.py`**.
4. *Deploy*. No secrets are required.

Notes:

- `requirements.txt` pins **`opencv-python-headless`**, not `opencv-python`.
  The non-headless build needs libGL, which Community Cloud containers lack —
  the app would install cleanly and then crash on first import.
- `data/runs/` must be committed for the hosted demo to have anything to show.
  It is small (previews are downscaled JPEGs). The masters and variants
  themselves stay gitignored and are regenerated locally.
- The app degrades honestly: with no `data/runs/` it says what to run rather
  than showing an empty dashboard.

## Checking it before you share the link

```bash
# exactly what the host does
python -m streamlit run app/streamlit_app.py --server.headless true
```

Then open an **incognito window** — a logged-out view catches
"works-on-my-machine" state that a warm session hides.

## If Community Cloud is unavailable

Render, Fly.io or any container host works; the app is a single Streamlit
process with no database and no background workers.

```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8501
CMD ["streamlit", "run", "app/streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```
