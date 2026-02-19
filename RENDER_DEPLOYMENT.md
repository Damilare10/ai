<<<<<<< HEAD
# Deploying to Render (Twikit Update)

This guide covers how to deploy the updated application with the new `twikit`-based scraper.

## 1. Push Changes to GitHub
Run the following commands in your terminal to push your local changes to GitHub:

```bash
git add .
git commit -m "Migrate scraper to Twikit and add cookie support"
git push origin main
```

## 2. Update Render Environment Variables
Go to your **Render Dashboard** -> **Select your Service** -> **Environment**.

Add or Update the following variables:

| Variable | Value | Description |
| :--- | :--- | :--- |
| `TWITTER_USERNAME` | `trialbanan` | Your Twitter username (without @). |
| `TWITTER_PASSWORD` | `web3kaiju10` | Your Twitter password. |
| `TWITTER_EMAIL` | `mumunihabib1.0@gmail.com` | (Optional) Your Twitter email. |

### 3. (Critical) Add Cookies for Cloudflare Bypass
Because Render's IP might be blocked by Cloudflare login screens, you must provide the cookies you imported locally.

1.  Open `user_data/guest/trialbanan_cookies.json` on your local machine.
2.  Copy the **entire content** of the file (it's a JSON array).
3.  In Render Environment variables, add:
    *   **Key**: `TWITTER_COOKIES`
    *   **Value**: *Paste the JSON content here*

## 4. Deploy
1.  Go to **Manual Deploy** -> **Deploy latest commit**.
2.  Watch the logs. The build should be much faster now as it no longer installs Playwright browsers.

## 5. Verification
Once deployed, check the logs. If the API fails (or if you test the fallback), you should see:
`🍪 Loading cookies from TWITTER_COOKIES environment variable...`
followed by successful scraping.
=======
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
7.  **Start Command**: `uvicorn main:app --host 0.0.0.0 --port 8000`
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
>>>>>>> d1a2a7da81e5712ee21d65d93bdba171129236c3
