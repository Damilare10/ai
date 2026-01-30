import logging
import tweepy
import config
import time
import utils

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
    """
    # 1. Get credentials ONLY for this user
    creds = utils.get_scraping_credentials(user_id)
    
    if not creds:
        return "Error: No scraping accounts configured. Please add them in Settings."
    
    max_attempts = len(creds)
    
    for attempt, cred in enumerate(creds):
        # Add small cooldown between attempts if retrying
        if attempt > 0:
            time.sleep(2)

        account_num = attempt + 1
        logger.info(f"🔄 User {user_id}: Using API account #{account_num} for tweet {tweet_id}")

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
                logger.error(f"Tweet {tweet_id} not found or inaccessible")
                if attempt == max_attempts - 1:
                    return f"Error: Tweet {tweet_id} not found or inaccessible"
                continue
            
            text = _extract_text_from_tweepy_tweet(response.data)
            
            if text:
                return text
            
        except tweepy.errors.TooManyRequests:
            logger.warning(f"⚠️ Rate limit hit for User {user_id} Account #{account_num}")
            continue  # Try next account in user's list
        
        except tweepy.errors.NotFound:
            return f"Error: Tweet {tweet_id} not found (deleted or private)"
        
        except tweepy.errors.Forbidden:
            return f"Error: Access to tweet {tweet_id} forbidden"
        
        except Exception as e:
            logger.error(f"Error with account #{account_num}: {e}")
            continue

    return f"Error: All {max_attempts} accounts exhausted or rate limited for tweet {tweet_id}"