# Forever Free Deployment Guide (Render + Neon)

You are looking for a **completely free** option. 

*   **Render** is great for hosting the Python Bot application (Compute).
*   **Netlify / Vercel** will **NOT** work. Here is why:
    1.  **Timeouts**: They use "Serverless Functions" which are killed after 10-60 seconds. Your bot needs to run for minutes to process batches.
    2.  **No Background Tasks**: When your API replies "Success", Vercel freezes the CPU. Your `batch_manager` (which runs in the background) would stop working immediately.
    3.  **App Structure**: Your app is built as a long-running server (`uvicorn`), not a set of small serverless functions.
*   **However**, Render's free database expires after 30 days.

**The Solution:** Use **Render** for the App and **Neon.tech** for the Database. Both have generous "forever free" tiers.

---

## Architecture

1.  **Neon.tech (Database)**: Holds your data (Users, History, Queue). Forever free (0.5 GB).
2.  **Render (Web Service)**: Runs your Python Bot. Free tier (spins down when unused, wakes up on request).

---

## Step 1: Create Free Database (Neon)

1.  Go to [Neon.tech](https://neon.tech) and Sign Up (Free).
2.  Create a **New Project**.
    *   Name: `aireply-db`
    *   Postgres Version: 15 or 16 (default is fine).
    *   Region: Choose one close to you (e.g., US East, Frankfurt).
3.  **Copy the Connection String**.
    *   It looks like: `postgres://user:password@ep-cool-cloud.aws.neon.tech/neondb?sslmode=require`
    *   Uncheck "Pooled connection" if you see the option (direct is fine for this). Even if you copy the pooled one, it will work.

---

## Step 2: Push Code to GitHub

Make sure your code is committed and pushed to your GitHub repository.

---

## Step 3: Deploy the Python App (Render)

1.  Go to [Render Dashboard](https://dashboard.render.com/).
2.  Click **New +** -> **Web Service**.
3.  Connect your `aireply` GitHub repository.
4.  **Configuration**:
    *   **Name**: `aireply-bot`
    *   **Region**: Same as (or close to) your Neon DB region.
    *   **Runtime**: **Python 3**
    *   **Build Command**: `pip install -r requirements.txt`
    *   **Start Command**: `uvicorn main:app --host 0.0.0.0 --port 8000`
    *   **Instance Type**: **Free**
5.  **Environment Variables** (Click "Add Environment Variable"):
    *   `DATABASE_URL`: Paste the **Neon Connection String** from Step 1.
    *   `SECRET_KEY`: Generate a random string (e.g., `my-super-secret-key-123`).
    *   `GEMINI_API_KEY`: Your Gemini API Key.
    *   Add any other keys from your `.env` (e.g., Twitter/X credentials).
6.  Click **Create Web Service**.

---

## Step 4: Verification

1.  Wait for the deployment to finish (it might take a few minutes).
2.  In the **Logs**, look for `PostgreSQL Connection Pool Initialized`.
3.  Visit your app URL (e.g., `https://aireply-bot.onrender.com/docs`).

## Important Notes

*   **Spin Down**: The free Render web service will "sleep" after 15 minutes of inactivity. The first request after sleep will take 30-60 seconds to load. This is normal for the free tier. Your data in Neon is safe and always available.
*   **Batch Processing**: If the app goes to sleep while a batch is running, the batch might stop. To prevent this during a batch, keep the tab open or use a free uptime monitor (like UptimeRobot) to ping your homepage every 10 minutes.
