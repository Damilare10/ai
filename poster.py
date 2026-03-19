import tweepy
import utils

def post_reply(reply_text, reply_to_id, user_id):
    """
    Posts a reply to a tweet using the Twitter API v2.
    Supports both traditional App-level API Keys and OAuth 2.0 User Context.
    """
    try:
        creds = utils.get_setting("posting_credentials", {}, user_id=user_id)
        
        if not creds:
            return "Error: Posting credentials not configured. Please Connect Twitter in Settings."

        if creds.get("oauth2"):
            # OAuth 2.0 Flow
            if not creds.get("access_token"):
                return "Error: Twitter OAuth incomplete. Please reconnect."
                
            client = tweepy.Client(
                bearer_token=creds["access_token"]
            )
        else:
            # Traditional 4-Key Flow
            if not creds.get("api_key"):
                return "Error: Posting credentials not configured. Please add them in Settings."

            client = tweepy.Client(
                consumer_key=creds["api_key"],
                consumer_secret=creds["api_secret"],
                access_token=creds["access_token"],
                access_token_secret=creds["access_secret"]
            )

        response = client.create_tweet(text=reply_text, in_reply_to_tweet_id=reply_to_id)
        return f"Successfully posted! Tweet ID: {response.data['id']}"
    except tweepy.errors.TooManyRequests:
        return "RATE_LIMIT_EXCEEDED"
    except tweepy.errors.Unauthorized as e:
        if creds.get("oauth2"):
            return "Error: OAuth Token Expired. Please disconnect and reconnect Twitter in Settings."
        return f"Error: Unauthorized credentials. {e}"
    except tweepy.errors.Forbidden as e:
        if "Reply to this conversation is not allowed" in str(e):
             return "Error: The author has restricted who can reply to this tweet. You cannot post this reply."
        return f"Error: Action Forbidden by Twitter. {e}"
    except Exception as e:
        return f"Error posting tweet: {e}"