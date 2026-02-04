import os
import tweepy
from dotenv import load_dotenv

load_dotenv()

print("🔍 Testing Credentials...\n")

TEST_TWEET_ID = "1460323737035677698" # "Twitter is now X" or just a Jack/Elon tweet. Let's use Jack's first tweet or something standard. 
# Jack's first tweet: 20
TEST_TWEET_ID = "20" 

valid_count = 0
invalid_count = 0

# Check Env Vars
for i in range(1, 12):
    print(f"--- Account #{i} ---")
    bearer_token = os.getenv(f"TWITTER_BEARER_TOKEN_{i}")
    api_key = os.getenv(f"TWITTER_API_KEY_{i}")

    if not bearer_token:
        print("❌ Missing in .env (Skipping)")
        continue

    try:
        # Client Init
        client = tweepy.Client(bearer_token=bearer_token)
        
        # Test Call
        response = client.get_tweet(TEST_TWEET_ID)
        
        if response.data:
            print("✅ Valid (Read Success)")
            valid_count += 1
        elif response.errors:
            print(f"❌ Error: {response.errors}")
            invalid_count += 1
        else:
            print("❓ Unknown Response (Might be suspended?)")
            invalid_count += 1
            
    except tweepy.errors.Unauthorized:
        print("❌ UNAUTHORIZED (Bad Token)")
        invalid_count += 1
    except tweepy.errors.Forbidden:
        print("❌ FORBIDDEN (Suspended/Locked)")
        invalid_count += 1
    except Exception as e:
        print(f"❌ Exception: {e}")
        invalid_count += 1

print(f"\nSummary: {valid_count} Valid, {invalid_count} Invalid/Suspended")
