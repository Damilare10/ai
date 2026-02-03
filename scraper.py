import logging
import tweepy
import config
import time
import utils
import random

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

def get_tweet_text(tweet_id: str, user_id: int = None) -> str:
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
    
    # Return "accounts exhausted" keyphrase to trigger the sleep in BatchManager
    return f"Error: All {max_attempts} accounts exhausted or rate limited. Details: {error_summary}"