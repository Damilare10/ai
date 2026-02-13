import logging
import tweepy
import config
import time
import utils
import random
import tweet_scraper

logger = logging.getLogger(__name__)

def _extract_text_from_tweepy_tweet(tweet_data) -> str:
    """Helper to extract text from Tweet object."""
    try:
        # LEVEL 1: Check for note_tweet (long-form)
        if hasattr(tweet_data, 'note_tweet') and tweet_data.note_tweet:
            note_text = tweet_data.note_tweet.get('text', '')
            if note_text:
                logger.info(f"✅ Found note_tweet (long-form) for tweet {tweet_data.id}")
                return note_text
        
        # LEVEL 2: Standard text
        if hasattr(tweet_data, 'text') and tweet_data.text:
            logger.info(f"Using standard text for tweet {tweet_data.id}")
            return tweet_data.text
        
        logger.warning(f"⚠️ No text found for tweet {tweet_data.id}")
        return ""
    except Exception as e:
        logger.error(f"Error extracting text from tweet: {e}")
        return ""

def get_tweet_text(tweet_id: str, user_id: int = None, tweet_url: str = None) -> str:
    """
    Main Entry Point.
    Fetches credentials specific to the user_id and rotates through them locally.
    Uses random shuffling for load balancing.
    """
    # 1. Get credentials ONLY for this user (which now includes system pool)
    creds = utils.get_scraping_credentials(user_id)
    
    if not creds:
        return "Error: No scraping accounts configured. Please add them in Settings."
    
    # Shuffle credentials to spread load (Simple Load Balancing)
    random.shuffle(creds)
    
    max_attempts = len(creds)
    errors = [] # Track errors for debugging
    
    for attempt, cred in enumerate(creds):
        # Add small cooldown between attempts if retrying
        if attempt > 0:
            time.sleep(2)

        # We can't identify "Account #1" easily after shuffle without extra tracking, 
        # so we rely on the API key or just "Account Index [i]" logging.
        # Let's log a truncated key for ID.
        key_hint = cred["api_key"][:4] + "..." if cred.get("api_key") else "Unknown"
        logger.info(f"🔄 User {user_id}: Using API account (Key: {key_hint}) for tweet {tweet_id}")

        try:
            # 2. Initialize Client with SPECIFIC credentials
            client = tweepy.Client(
                bearer_token=cred["bearer_token"],
                consumer_key=cred["api_key"],
                consumer_secret=cred["api_secret"],
                access_token=cred["access_token"],
                access_token_secret=cred["access_secret"]
            )
            
            # 3. Fetch Tweet
            response = client.get_tweet(
                id=tweet_id,
                tweet_fields=['text', 'note_tweet'],
                expansions=['author_id']
            )
            
            if not response or not response.data:
                # If we get a 200 OK but empty data, it might mean weird permissions or deleted.
                # Usually tweepy raises exception for errors. 
                logger.warning(f"  > Empty response for tweet {tweet_id} with Key {key_hint}")
                errors.append(f"{key_hint}: Empty Response")
                continue
            
            text = _extract_text_from_tweepy_tweet(response.data)
            
            if text:
                return text
            
        except tweepy.errors.TooManyRequests:
            logger.warning(f"⚠️ Rate limit hit for User {user_id} (Key: {key_hint})")
            errors.append(f"RateLimit")
            continue  # Try next account
        
        except tweepy.errors.Forbidden as e:
            # FIX: Don't stop on Forbidden. Could be a bad credential or specific restrictions.
            # Only stop if ALL accounts fail.
            logger.warning(f"⛔ Forbidden for User {user_id} (Key: {key_hint}): {e}")
            errors.append(f"Forbidden")
            continue 
        
        except tweepy.errors.NotFound:
            # If ANY account says "Not Found", the tweet is likely actually deleted.
            # No point checking other accounts (unless user blocks specific account?)
            # Assuming deleted:
            return f"Error: Tweet {tweet_id} not found (deleted or private)"
        
        except tweepy.errors.Unauthorized as e:
            logger.error(f"❌ Unauthorized (Bad Keys) for User {user_id} (Key: {key_hint}): {e}")
            errors.append(f"Unauthorized")
            continue

        except Exception as e:
            logger.error(f"Error with account (Key: {key_hint}): {e}")
            errors.append(f"{type(e).__name__}")
            continue

    # If we fall through, all accounts failed
    error_summary = ", ".join(errors)
    logger.error(f"❌ All {max_attempts} accounts failed for tweet {tweet_id}. Errors: {error_summary}")
    
    # FALLBACK: Try Browser Scraper
    logger.info(f"⚠️ API failed for {tweet_id}. Attempting browser fallback...")
    try:
        # Use provided URL or construct best-effort
        target_url = tweet_url if tweet_url else f"https://x.com/i/status/{tweet_id}"
        
        # Run async scraper in this sync function (using asyncio.run since we are in a thread)
        # However, if we are already in an event loop (which we are, in main.py), asyncio.run might fail if not careful.
        # But wait, main.py calls this via asyncio.to_thread, so we are in a separate thread. 
        # asyncio.run() *should* create a new loop for this thread.
        import asyncio
        fallback_text = asyncio.run(tweet_scraper.scrape_tweet_content(target_url, user_id))
        
        if fallback_text and "Error" not in fallback_text:
            logger.info(f"✅ Browser fallback successful for {tweet_id}")
            return fallback_text
        else:
            logger.error(f"❌ Browser fallback also failed for {tweet_id}")
            
    except Exception as e:
        logger.error(f"❌ Browser fallback exception: {e}")

    # Return "accounts exhausted" keyphrase to trigger the sleep in BatchManager
    return f"Error: All {max_attempts} accounts exhausted/rate limited AND fallback failed. Details: {error_summary}"

def get_tweets_batch(tweet_ids: list[str], user_id: int = None, rotation_index: int = 0) -> dict[str, str]:
    """
    Fetches a batch of tweets (up to 100 per call, but we usually do 5) using ONE credential.
    Rotates credentials based on rotation_index (Round Robin).
    Returns a dict: { "tweet_id": "text" }
    
    Special return values:
    - {"_rate_limited": True, "_all_failed": True} = All accounts hit rate limits, caller should wait
    - {} = Normal empty (tweets deleted/private)
    """
    creds = utils.get_scraping_credentials(user_id)
    if not creds:
        logger.error("No scraping credentials found.")
        return {}

    # 1. Select Credential (Round Robin based on batch index)
    # This ensures Batch 1 uses Key 1, Batch 2 uses Key 2, etc.
    cred_idx = rotation_index % len(creds)
    
    # Try the selected credential, but allow failover to others if it fails
    attempt_order = list(range(len(creds)))
    # Rotate order so selected is first: [2, 3, 0, 1] if idx is 2
    attempt_order = attempt_order[cred_idx:] + attempt_order[:cred_idx]
    
    results = {}
    rate_limit_count = 0  # Track how many accounts hit rate limits
    total_attempts = len(attempt_order)
    
    for idx in attempt_order:
        cred = creds[idx]
        key_hint = cred["api_key"][:4] + "..." if cred.get("api_key") else "Unknown"
        logger.info(f"🔄 User {user_id}: Batch Scrape (Size {len(tweet_ids)}) using Account #{idx+1} (Key: {key_hint})")
        
        try:
            client = tweepy.Client(
                bearer_token=cred["bearer_token"],
                consumer_key=cred["api_key"],
                consumer_secret=cred["api_secret"],
                access_token=cred["access_token"],
                access_token_secret=cred["access_secret"]
            )
            
            # 2. Batch Fetch
            response = client.get_tweets(
                ids=tweet_ids,
                tweet_fields=['text', 'note_tweet'],
                expansions=['author_id']
            )
            
            if response and response.data:
                for tweet in response.data:
                    text = _extract_text_from_tweepy_tweet(tweet)
                    if text:
                        results[str(tweet.id)] = text
                
                logger.info(f"✅ Automatically scraped {len(results)}/{len(tweet_ids)} tweets.")
                return results # Success! Return immediately.
                
            else:
                logger.warning(f"  > Empty batch response with Key {key_hint}")
                # Don't failover immediately for empty response, might be just empty.
                # But if ALL are empty, we return empty dict.
                # Actually, empty response usually means none found (deleted/private), which is valid result.
                return {} 

        except tweepy.errors.TooManyRequests:
            logger.warning(f"⚠️ Rate limit hit for User {user_id} (Key: {key_hint}). Failing over...")
            rate_limit_count += 1
            time.sleep(1)
            continue # Try next key
            
        except tweepy.errors.Forbidden as e:
            logger.warning(f"⛔ Forbidden for User {user_id} (Key: {key_hint}): {e}")
            continue
            
        except tweepy.errors.Unauthorized as e:
            logger.error(f"❌ Unauthorized (Bad Keys) for User {user_id} (Key: {key_hint}): {e}")
            continue
            
        except Exception as e:
            logger.error(f"Batch scrape error with Key {key_hint}: {e}")
            continue
    
    # All accounts failed - check if it was due to rate limits
    if rate_limit_count == total_attempts:
        logger.warning(f"🛑 ALL {total_attempts} accounts hit rate limits for User {user_id}!")
        return {"_rate_limited": True, "_all_failed": True}
    
    return results # Return whatever we got (maybe empty if all failed)