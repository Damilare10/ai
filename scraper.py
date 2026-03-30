import logging
import requests
import config
import time
import utils
import random

logger = logging.getLogger(__name__)

# TwitterAPI.io base URL
TWITTERAPI_BASE = "https://api.twitterapi.io"

def extract_tweet_for_ai(x_url: str) -> str:
    """
    Extract tweet data using vxtwitter API (no auth required).
    Primary method for tweet extraction.
    """
    # Convert the URL to vxtwitter API
    if "x.com" in x_url:
        api_url = x_url.replace("x.com", "api.vxtwitter.com")
    elif "twitter.com" in x_url:
        api_url = x_url.replace("twitter.com", "api.vxtwitter.com")
    else:
        return "Error: Invalid Twitter/X URL format"

    try:
        response = requests.get(api_url, timeout=10)
        if response.status_code == 200:
            tweet_data = response.json()

            # Extract from vxtwitter response structure
            tweet_text = tweet_data.get("text")
            # vxtwitter uses user_screen_name at top level
            author_handle = tweet_data.get("user_screen_name")

            if tweet_text and author_handle:
                return f"@{author_handle} | {tweet_text}"
            else:
                return f"Error: Could not extract tweet data (text={bool(tweet_text)}, author={bool(author_handle)})"
        else:
            return f"Error: vxtwitter API returned status {response.status_code}"
    except requests.exceptions.Timeout:
        return "Error: vxtwitter API request timed out"
    except Exception as e:
        return f"Error: vxtwitter request failed: {e}"


def _extract_from_tweet_obj(tweet_obj: dict):
    """
    Extract (text, username) from tweet object from either vxtwitter or TwitterAPI.io.
    Supports both shapes:
    - TwitterAPI.io: { text, author: { userName, username, ... }, ... }
    - vxtwitter:   { text, author: { screen_name, username, ... }, ... }
    """
    text = tweet_obj.get('text') or tweet_obj.get('full_text') or ''

    author = tweet_obj.get('author') or tweet_obj.get('user') or {}
    if isinstance(author, dict):
        username = (
            author.get('screen_name')
            or author.get('userName')
            or author.get('username')
            or author.get('name')
            or ''
        )
    else:
        username = ''

    return text, username


def get_tweet_text(tweet_id: str, user_id: int = None, tweet_url: str = None) -> str:
    """
    Fetch a single tweet's text.
    Primary method: vxtwitter API (if tweet_url provided)
    Fallback: TwitterAPI.io with credentials
    """
    # Try vxtwitter first if tweet_url is provided
    if tweet_url:
        logger.info(f"🔄 User {user_id}: Trying vxtwitter for tweet {tweet_id}")
        result = extract_tweet_for_ai(tweet_url)
        if not result.startswith("Error:"):
            logger.info(f"✅ Successfully fetched tweet {tweet_id} via vxtwitter")
            return result
        else:
            logger.warning(f"⚠️ vxtwitter failed for tweet {tweet_id}: {result}. Falling back to TwitterAPI.io")

    # Fallback to TwitterAPI.io
    creds = utils.get_scraping_credentials(user_id)

    if not creds:
        return "Error: No scraping accounts configured. Please add a TwitterAPI.io key in Settings."

    random.shuffle(creds)
    errors = []

    for attempt, cred in enumerate(creds):
        if attempt > 0:
            time.sleep(2)

        api_key = cred.get("api_key", "").strip()
        if not api_key:
            errors.append("Missing API Key")
            continue

        key_hint = api_key[:6] + "..."
        logger.info(f"🔄 User {user_id}: Fetching tweet {tweet_id} via TwitterAPI.io (Key: {key_hint})")

        try:
            response = requests.get(
                f"{TWITTERAPI_BASE}/twitter/tweets",
                headers={"X-API-Key": api_key},
                params={"tweet_ids": tweet_id},
                timeout=15
            )

            if response.status_code == 429:
                logger.warning(f"⚠️ Rate limit hit (Key: {key_hint})")
                errors.append("RateLimit")
                time.sleep(1)
                continue

            if response.status_code in (401, 403):
                logger.error(f"❌ Auth error (Key: {key_hint}): {response.status_code}")
                errors.append(f"AuthError-{response.status_code}")
                continue

            if response.status_code == 404:
                return f"Error: Tweet {tweet_id} not found (deleted or private)"

            response.raise_for_status()
            data = response.json()

            if data.get('status') == 'error':
                logger.warning(f"API returned error: {data.get('message')} (Key: {key_hint})")
                errors.append(f"APIError: {data.get('message', 'unknown')}")
                continue

            tweets = data.get('tweets', [])
            if not tweets:
                logger.warning(f"Empty tweet list for {tweet_id} (Key: {key_hint})")
                errors.append("EmptyResponse")
                continue

            text, username = _extract_from_tweet_obj(tweets[0])
            if text:
                logger.info(f"✅ Successfully scraped tweet {tweet_id}")
                if username:
                    return f"@{username} | {text}"
                return text

            errors.append("EmptyText")

        except requests.exceptions.Timeout:
            logger.error(f"Timeout for tweet {tweet_id} (Key: {key_hint})")
            errors.append("Timeout")
            continue

        except Exception as e:
            logger.error(f"Error with key {key_hint}: {e}")
            errors.append(f"{type(e).__name__}: {e}")
            continue

    error_summary = ", ".join(errors)
    logger.error(f"❌ All accounts failed for tweet {tweet_id}. Errors: {error_summary}")
    return f"Error: All accounts exhausted/rate limited. Details: {error_summary}"


def get_tweets_batch(tweet_ids: list[str], user_id: int = None, rotation_index: int = 0) -> dict[str, str]:
    """
    Batch-fetch tweets.
    Uses TwitterAPI.io (vxtwitter batch endpoint unreliable for batch requests).
    Returns: { "tweet_id": "@username | text", ... }

    Special return values:
    - {"_all_failed": True} = All accounts rate-limited/auth-failed
    - {} = Tweets not found / empty
    """
    creds = utils.get_scraping_credentials(user_id)
    if not creds:
        logger.error("No scraping credentials found.")
        return {}

    # Round-robin credential selection
    cred_idx = rotation_index % len(creds)
    attempt_order = list(range(len(creds)))
    attempt_order = attempt_order[cred_idx:] + attempt_order[:cred_idx]

    rate_limit_count = 0
    auth_error_count = 0
    total_attempts = len(attempt_order)

    for idx in attempt_order:
        cred = creds[idx]
        api_key = cred.get("api_key", "").strip()
        if not api_key:
            auth_error_count += 1
            continue

        key_hint = api_key[:6] + "..."
        logger.info(f"🔄 User {user_id}: Batch ({len(tweet_ids)} tweets) via Account #{idx+1} (Key: {key_hint})")

        try:
            # TwitterAPI.io supports comma-separated IDs in a single request
            ids_param = ",".join(tweet_ids)
            response = requests.get(
                f"{TWITTERAPI_BASE}/twitter/tweets",
                headers={"X-API-Key": api_key},
                params={"tweet_ids": ids_param},
                timeout=20
            )

            if response.status_code == 429:
                logger.warning(f"⚠️ Rate limit (Key: {key_hint}). Failing over...")
                rate_limit_count += 1
                time.sleep(1)
                continue

            if response.status_code in (401, 403):
                logger.warning(f"⛔ Auth error {response.status_code} (Key: {key_hint})")
                auth_error_count += 1
                continue

            response.raise_for_status()
            data = response.json()

            if data.get('status') == 'error':
                logger.warning(f"API error: {data.get('message')} (Key: {key_hint})")
                continue

            tweets = data.get('tweets', [])
            if not tweets:
                logger.warning(f"Empty batch response (Key: {key_hint})")
                return {}

            results = {}
            for tweet_obj in tweets:
                tid = str(tweet_obj.get('id', ''))
                text, username = _extract_from_tweet_obj(tweet_obj)
                if tid and text:
                    results[tid] = f"@{username} | {text}" if username else text

            logger.info(f"✅ Scraped {len(results)}/{len(tweet_ids)} tweets.")
            return results  # Success, return immediately

        except requests.exceptions.Timeout:
            logger.error(f"Batch timeout (Key: {key_hint})")
            continue

        except Exception as e:
            logger.error(f"Batch error (Key: {key_hint}): {e}")
            continue

    total_failures = rate_limit_count + auth_error_count
    if total_failures >= total_attempts:
        logger.warning(f"🛑 ALL {total_attempts} accounts failed (Rate: {rate_limit_count}, Auth: {auth_error_count})")
        return {"_all_failed": True}

    return {}