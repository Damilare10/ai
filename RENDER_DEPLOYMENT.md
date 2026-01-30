# Deploying to Render.com with Persistent Storage

This guide describes how to deploy your **AI Reply Agent** to [Render](https://render.com). Render is recommended because it supports background workers and persistent storage (PostgreSQL) out of the box, which are required for your bot's long-running tasks and database.

## Architecture Overview

You will create **two** separate resources on Render:
1.  **PostgreSQL Database**: For storing users, history, queue, and logs persistently.
2.  **Web Service (Python App)**: Runs the main `FastAPI` bot application.

---

## Step 1: Push Code to GitHub

Ensure your latest code (including the recent changes to support environment variables) is pushed to your GitHub repository.

---

## Step 2: Create the Database (PostgreSQL)

1.  Log in to your Render Dashboard.
2.  Click **New +** and select **PostgreSQL**.
3.  **Name**: `aireply-db`
4.  **Database**: `aireply`
5.  **User**: `aireply_user`
6.  **Region**: Select a region close to you (e.g., Frankfurt or Oregon).
7.  **Plan**: **Free** config is fine for starting.
8.  Click **Create Database**.
9.  **Wait** for it to become "Available".
10. **Copy the `Internal Connection String`**. It looks like: `postgresql://aireply_user:password@hostname/aireply`. You will need this completely for Step 4.

---

## Step 3: Deploy the Python App (Main Bot)

1.  Click **New +** and select **Web Service**.
2.  Connect **the same** GitHub repository.
3.  **Name**: `aireply-app`
4.  **Region**: **Must be the same** as your database.
5.  **Runtime**: **Python 3**
6.  **Build Command**: `pip install -r requirements.txt`
7.  **Start Command**: `uvicorn main:app --host 0.0.0.0 --port 10000`
8.  **Environment Variables**:
    *   `DATABASE_URL`: Paste the **Internal Connection String** from Step 2.
    *   `SECRET_KEY`: Generate a random string (e.g., using `openssl rand -hex 32`).
    *   `GEMINI_API_KEY`: Your Gemini API Key.
    *   Add any other keys from your local `.env` (Twitter/X credentials, etc.).
9.  Click **Create Web Service**.

---

## Step 5: Verification

1.  Watch the deploy logs for `aireply-app`.
2.  You should see "PostgreSQL Connection Pool Initialized" in the logs.
3.  Visit your app's URL: `https://aireply-app.onrender.com/docs`.
4.  Test the API or use your frontend to interact with it.

## Notes on Persistence

*   **Database**: Your `history`, `users`, etc., are now stored in the Render PostgreSQL database. This data is safe and persistent even if you redeploy the app.
*   **Logs**: Render automatically keeps recent logs in its dashboard. The app also writes logs to the database (`logs` table), so you can query them anytime.
*   **Local Files**: Do **not** rely on saving files to the disk (like `app.log` or generic text files) as they will be deleted on redeploy. The code has been checked, and it primarily uses the database, which is correct.
