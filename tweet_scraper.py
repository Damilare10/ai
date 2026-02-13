import asyncio
import os
import json
import re
import random
from playwright.async_api import async_playwright

def extract_tweet_id(url: str) -> str:
    """Extracts the tweet ID from a standard X/Twitter URL."""
    match = re.search(r'(?:status/|in_reply_to=|q=)(\d+)', url)
    return match.group(1) if match else None

def get_auth_file(user_id=None):
    """Finds an available authentication file from the user_data directory."""
    base_dir = "user_data"
    if not os.path.exists(base_dir):
        return None
    
    # If user_id is provided, look in that user's specific folder
    target_dirs = []
    if user_id:
        user_path = os.path.join(base_dir, str(user_id))
        if os.path.isdir(user_path):
            target_dirs.append(user_path)
    
    # If no user_id or folder not found, look in all (fallback)
    if not target_dirs:
        for uid in os.listdir(base_dir):
            path = os.path.join(base_dir, uid)
            if os.path.isdir(path):
                target_dirs.append(path)
    
    auth_files = []
    for d in target_dirs:
        for f in os.listdir(d):
            if f.endswith('.json'):
                auth_files.append(os.path.join(d, f))
    
    return random.choice(auth_files) if auth_files else None

    return None

def extract_tweet_text_from_json(json_data, tweet_id: str):
    """
    Recursively searches for the 'full_text' of the tweet with the given ID.
    Accessing 'legacy' -> 'full_text' is the standard path.
    Also checks for 'note_tweet' which contains full text for long tweets.
    """
    if isinstance(json_data, dict):
        # Check if this object represents the tweet
        if json_data.get('rest_id') == tweet_id or json_data.get('id_str') == tweet_id:
            # CHECK FOR LONG TWEET (Note Tweet) FIRST
            # Structure usually: result -> note_tweet -> note_tweet_results -> result -> text
            note_tweet = json_data.get('note_tweet')
            if note_tweet and isinstance(note_tweet, dict):
                try:
                    text = note_tweet['note_tweet_results']['result']['text']
                    if text:
                        return text
                except (KeyError, TypeError):
                    pass
            
            # Check for legacy.full_text (common pattern)
            legacy = json_data.get('legacy')
            if isinstance(legacy, dict) and 'full_text' in legacy:
                return legacy['full_text']
            # Check for direct full_text
            if 'full_text' in json_data:
                return json_data['full_text']
        
        # Recursive search in values
        for key, value in json_data.items():
            result = extract_tweet_text_from_json(value, tweet_id)
            if result:
                return result
                
    elif isinstance(json_data, list):
        # Recursive search in list items
        for item in json_data:
            result = extract_tweet_text_from_json(item, tweet_id)
            if result:
                return result
                
    return None

async def scrape_tweet_content(tweet_url: str, user_id=None):
    """
    Scrapes the text content of a specific tweet URL.
    """
    tweet_id = extract_tweet_id(tweet_url)
    if not tweet_id:
        print(f"❌ Invalid URL: Could not extract Tweet ID from {tweet_url}")
        return None

    auth_file = get_auth_file(user_id)
    # auth_file = None
    if auth_file:
        print(f"🔑 Using auth file: {auth_file}")
    else:
        print("⚠️ No auth file found. Attempting scan as guest (might fail for sensitive content)...")

    found_text = None
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        
        if auth_file:
            context = await browser.new_context(storage_state=auth_file)
        else:
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )

        page = await context.new_page()
        
        # Intercept responses
        async def handle_response(response):
            nonlocal found_text
            try:
                if found_text: return # Stop processing if we already found it
                
                url = response.url
                if ("x.com" in url or "twitter.com" in url) and response.status == 200:
                    content_type = response.headers.get("content-type", "")
                    if "json" in content_type:
                        if "TweetDetail" in url:
                            print(f"📡 Intercepted TweetDetail API: {url[:60]}...")
                        
                        try:
                            data = await response.json()
                            text = extract_tweet_text_from_json(data, tweet_id)
                            if text:
                                found_text = text
                                print(f"✅ Successfully captured tweet text!")
                        except:
                            pass
            except:
                pass

        page.on("response", handle_response)
        
        try:
            print(f"🌐 Navigating to: {tweet_url}")
            # Use 'commit' to wait for initial response but not full load, avoiding strict timeouts
            try:
                await page.goto(tweet_url, wait_until="commit", timeout=20000)
                await asyncio.sleep(5) # Give it a moment to render basic structure
                
                title = await page.title()
                current_url = page.url
                print(f"📄 Page Title: {title}")
                print(f"🔗 Current URL: {current_url}")
                
                try:
                    content = await page.evaluate("document.body.innerText")
                    print(f"📝 Page Content Preview: {content[:200].replace('\n', ' ')}...")
                except:
                    print("⚠️ Could not get page content.")
                    
            except Exception as e:
                print(f"⚠️ Page load timeout (continuing anyway): {e}")

            # Wait loop - check if text is found
            print("⏳ Waiting for tweet data...")
            for i in range(20):
                if found_text:
                    break
                await asyncio.sleep(1)
                
                # Scroll a bit if need be (sometimes triggers lazy loading)
                if i == 5 or i == 10:
                     try:
                        await page.evaluate("window.scrollBy(0, 500)")
                     except:
                        pass
            
            if not found_text:
                print("⚠️ Timeout: Tweet text not found in API responses.")
                try:
                    await page.screenshot(path="debug_screenshot.png")
                    print("📸 Saved screenshot to 'debug_screenshot.png'")
                except Exception as e:
                    print(f"❌ Failed to save screenshot: {e}")

        except Exception as e:
            print(f"❌ Error during scrape: {e}")
        finally:
            await browser.close()

    return found_text

if __name__ == "__main__":
    import sys
    
    # Simple CLI interface
    print("--- Tweet Content Scraper ---")
    
    url_input = ""
    if len(sys.argv) > 1:
        url_input = sys.argv[1]
    else:
        url_input = input("Enter Tweet URL: ").strip()
    
    if url_input:
        print(f"Target URL: {url_input}")
        print("\nStarting scraper...")
        result = asyncio.run(scrape_tweet_content(url_input))
        
        if result:
            print("\n" + "="*40)
            print("TWEET CONTENT:")
            print("="*40)
            print(result)
            print("="*40 + "\n")
        else:
            print("\n❌ Failed to retrieve tweet content.")
    else:
        print("No URL provided.")
