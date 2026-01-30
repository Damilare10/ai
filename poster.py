import tweepy
import utils

def post_reply(reply_text, reply_to_id, user_id):
    """
    Posts a reply to a tweet using the Twitter API v2.
    """
    try:
        creds = utils.get_setting("posting_credentials", {}, user_id=user_id)
        
        if not creds or not creds.get("api_key"):
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
    except Exception as e:
        return f"Error posting tweet: {e}"