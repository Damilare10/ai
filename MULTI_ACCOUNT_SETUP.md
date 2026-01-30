# Multi-Account Setup Guide - Official Twitter API

## Overview
Your scraper now uses the **official Twitter API v2** (via Tweepy) and rotates through up to 10 Twitter developer accounts to avoid rate limits. Each time a tweet is fetched, it automatically cycles to the next account.

## How It Works
1. **Account Rotation**: The system maintains a global counter that increments with each tweet fetch
2. **Automatic Cycling**: When the counter reaches the end of your account list, it wraps back to the first account
3. **Official API**: Uses Twitter's official API v2, which is more stable and reliable than browser-based scraping
4. **Transparent**: The rotation happens automatically - you don't need to manage it manually

---

## Setting Up Your Accounts

### Step 1: Create Twitter Developer Apps

For each of your 10 Twitter accounts, you need to create a developer app and get API credentials.

**How to get API credentials:**

1. **Go to Twitter Developer Portal**: https://developer.twitter.com/
2. **Sign in** with one of your Twitter accounts
3. **Create a new App**:
   - Click on "Projects & Apps" → "Create App"
   - Fill in the required information (App name, description, etc.)
   - Agree to the Developer Agreement
4. **Get your credentials**:
   - After creating the app, go to the app's "Keys and Tokens" tab
   - You'll see:
     - **API Key** (also called Consumer Key)
     - **API Secret** (also called Consumer Secret)
     - **Access Token**
     - **Access Token Secret**
   - Click "Generate" for Access Token and Secret if not already created
   - **Important**: Save these immediately - you won't be able to see the secrets again!
5. **Repeat for all 10 accounts**

### Step 2: Set API Permissions

Make sure each app has **Read** permissions (required for fetching tweets):
- In the Developer Portal, go to your app settings
- Under "User authentication settings" or "App permissions"
- Select **Read** or **Read and Write** (Read is sufficient for scraping)

### Step 3: Update Your .env File

Open your `.env` file and add credentials for each account:

```env
# Account 1
TWITTER_API_KEY_1=your_actual_api_key_for_account_1
TWITTER_API_SECRET_1=your_actual_api_secret_for_account_1
TWITTER_ACCESS_TOKEN_1=your_actual_access_token_for_account_1
TWITTER_ACCESS_SECRET_1=your_actual_access_secret_for_account_1

# Account 2
TWITTER_API_KEY_2=your_actual_api_key_for_account_2
TWITTER_API_SECRET_2=your_actual_api_secret_for_account_2
TWITTER_ACCESS_TOKEN_2=your_actual_access_token_for_account_2
TWITTER_ACCESS_SECRET_2=your_actual_access_secret_for_account_2

# ... continue for all 10 accounts
```

**Note:** You can use fewer than 10 accounts. The system will rotate through however many you configure.

---

## Rate Limits

Understanding Twitter API rate limits is important:

### Free Tier
- **Tweet Lookup**: 50 requests per 15 minutes per account
- **With 10 accounts**: 500 requests per 15 minutes total (33 requests/minute)

### Basic Tier ($100/month)
- **Tweet Lookup**: 100 requests per 15 minutes per account
- **With 10 accounts**: 1,000 requests per 15 minutes total (66 requests/minute)

### Pro Tier ($5,000/month)
- Much higher limits

**Recommendation**: Start with the Free tier on all accounts. Monitor your usage in the Developer Portal.

---

## Testing the Rotation

When you run your scraper, you'll see log messages like:
```
🔄 Using API account #1 for tweet 1234567890
✅ API account #1 authenticated
🔄 Using API account #2 for tweet 0987654321
✅ API account #2 authenticated
...
```

This confirms the rotation is working correctly.

---

## Benefits
- **Official API**: More stable than browser scraping, no cookie/token expiration issues
- **Better Rate Limits**: Clear, predictable rate limits with automatic rotation
- **Higher Throughput**: Scrape more tweets without hitting limits
- **Automatic Management**: No manual intervention required
- **Long-form Support**: Properly handles Twitter Articles (Note tweets)
- **Error Handling**: Clear error messages for different failure scenarios

---

## Troubleshooting

### "No Twitter API credentials configured for scraping"
- **Solution**: Make sure at least one account's credentials (all 4 values) are in your `.env` file

### Rotation isn't happening
- **Solution**: Check the terminal logs - you should see different account numbers being used

### Authentication errors
- **Solution**: 
  - Verify all 4 credentials (API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET) are correct
  - Check that your app has the correct permissions in Developer Portal
  - Regenerate tokens if needed

### "Rate limit exceeded"
- **Solution**: 
  - You've hit the rate limit on an account
  - Add more accounts to the rotation
  - Wait 15 minutes for the rate limit to reset
  - Consider upgrading to Basic tier for higher limits

### "Access forbidden" or "Tweet not found"
- **Solution**: The tweet might be from a protected account, deleted, or requires elevated API access
