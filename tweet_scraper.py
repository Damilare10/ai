import asyncio
import os
import json
import random
from twikit import Client
import utils

async def scrape_tweet_content(tweet_url: str, user_id=None):
    """
    Scrapes the text content of a specific tweet URL using Twikit (API Wrapper).
    Manages cookies to maintain sessions and avoid suspicious login activity.
    """
    tweet_id = utils.extract_tweet_id(tweet_url)
    if not tweet_id:
        print(f"Invalid URL: Could not extract Tweet ID from {tweet_url}")
        return None

    # 1. Get Credentials
    creds = utils.get_scraping_credentials(user_id)
    if not creds:
        print("No scraping credentials found for fallback.")
        return None
    
    # Filter for credentials with username/password (required for Twikit)
    valid_creds = [c for c in creds if c.get("username") and c.get("password")]
    
    if not valid_creds:
        print("No valid credentials (username/password) found for Twikit fallback.")
        print("   -> Please update Scraping Credentials in Settings.")
        return None
        
    # Shuffle for simple load balancing
    random.shuffle(valid_creds)
    cred = valid_creds[0]
    username = cred["username"]
    password = cred["password"]
    email = cred.get("email") # Optional but good for 2FA/suspicion
    
    print(f"Using account: {username}")

    # 2. Initialize Client
    client = Client('en-US')
    
    # 3. Cookie Management Paths
    cookies_dir = os.path.join("user_data", str(user_id) if user_id else "guest")
    os.makedirs(cookies_dir, exist_ok=True)
    cookies_path = os.path.join(cookies_dir, f"{username}_cookies.json")
    
    login_needed = True

    # 3.5 Check Environment Variable for Cookies (Render Support)
    # If no local file exists, check if cookies are provided via env var (e.g. on Render)
    if not os.path.exists(cookies_path):
        env_cookies = os.getenv("TWITTER_COOKIES")
        if env_cookies:
            try:
                print("🍪 Loading cookies from TWITTER_COOKIES environment variable...")
                with open(cookies_path, "w") as f:
                    f.write(env_cookies)
                print(f"✅ Saved environment cookies to {cookies_path}")
            except Exception as e:
                print(f"❌ Failed to save environment cookies: {e}")

    # 4. Try Loading Cookies
    if os.path.exists(cookies_path):
        try:
            print(f"Loading cookies from {cookies_path}...")
            client.load_cookies(cookies_path)
            login_needed = False
            # Optional: verify session, but might cost an API call. 
            # We'll just try to scrape and re-login if it fails with 401/403.
        except Exception as e:
            print(f"Failed to load cookies: {e}")
            login_needed = True

    # 5. Login (if needed)
    if login_needed:
        try:
            print(f"Logging in as {username}...")
            await client.login(
                auth_info_1=username, 
                password=password,
                auth_info_2=email
            )
            # Save cookies
            client.save_cookies(cookies_path)
            print("Login successful & cookies saved.")
        except Exception as e:
            print(f"Login failed: {e}")
            return None

    # 6. Fetch Tweet
    try:
        print(f"Fetching tweet {tweet_id}...")
        # Use batch endpoint as 'get_tweet_by_id' is currently broken (KeyError: itemContent)
        tweets = await client.get_tweets_by_ids([tweet_id])
        
        if tweets:
            tweet = tweets[0]
            print(f"Successfully fetched tweet!")
            return tweet.full_text
        else:
            print("Tweet retrieved but empty?")
            return None

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error fetching tweet: {e}")
        # If error was auth related, maybe cookies expired?
        # Could implement a retry with fresh login here, but keeping it simple for now.
        if "401" in str(e) or "403" in str(e) or "Unauthorized" in str(e):
             print("   -> Tip: Cookies might be invalid. Next run will re-login.")
             # Delete bad cookies
             if os.path.exists(cookies_path):
                 os.remove(cookies_path)
        return None

if __name__ == "__main__":
    import sys
    
    # Simple CLI interface
    print("--- Twikit Scraper ---")
    
    url_input = ""
    if len(sys.argv) > 1:
        url_input = sys.argv[1]
    else:
        url_input = input("Enter Tweet URL: ").strip()
    
    if url_input:
        print(f"Target URL: {url_input}")
        print("\nStarting scraper...")
        # Note: In real app, user_id is passed. Here we use None (might fail if no credentials for None user)
        # You might need to hardcode a user_id or ensure system credentials have username/pass
        result = asyncio.run(scrape_tweet_content(url_input))
        
        if result:
            print("\n" + "="*40)
            print("TWEET CONTENT:")
            print("="*40)
            print(result)
            print("="*40 + "\n")
        else:
            print("\nFailed to retrieve tweet content.")
    else:
        print("No URL provided.")

