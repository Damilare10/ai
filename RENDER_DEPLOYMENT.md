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
