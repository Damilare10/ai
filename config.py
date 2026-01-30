# config.py
"""
Configuration module using environment variables for secure credential management.
Create a .env file based on .env.example and populate with your actual credentials.
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# TWITTER OFFICIAL API - Multi-Account Support
# Load credentials for up to 11 accounts for rotation
API_KEYS = []
API_SECRETS = []
ACCESS_TOKENS = []
ACCESS_SECRETS = []
BEARER_TOKENS = []

for i in range(1, 12):  # Accounts 1-11
    api_key = os.getenv(f"TWITTER_API_KEY_{i}")
    api_secret = os.getenv(f"TWITTER_API_SECRET_{i}")
    access_token = os.getenv(f"TWITTER_ACCESS_TOKEN_{i}")
    access_secret = os.getenv(f"TWITTER_ACCESS_SECRET_{i}")
    bearer_token = os.getenv(f"TWITTER_BEARER_TOKEN_{i}")
    
    # Only add if all credentials are present (bearer token is required for API v2)
    if api_key and api_secret and access_token and access_secret and bearer_token:
        API_KEYS.append(api_key)
        API_SECRETS.append(api_secret)
        ACCESS_TOKENS.append(access_token)
        ACCESS_SECRETS.append(access_secret)
        BEARER_TOKENS.append(bearer_token)

# Fallback to single account if multi-account not configured
if not API_KEYS:
    single_key = os.getenv("TWITTER_API_KEY")
    single_secret = os.getenv("TWITTER_API_SECRET")
    single_token = os.getenv("TWITTER_ACCESS_TOKEN")
    single_access = os.getenv("TWITTER_ACCESS_SECRET")
    single_bearer = os.getenv("TWITTER_BEARER_TOKEN")
    if single_key and single_secret and single_token and single_access and single_bearer:
        API_KEYS = [single_key]
        API_SECRETS = [single_secret]
        ACCESS_TOKENS = [single_token]
        ACCESS_SECRETS = [single_access]
        BEARER_TOKENS = [single_bearer]

# Legacy single-account variables (for backward compatibility with poster.py)
API_KEY = API_KEYS[0] if API_KEYS else os.getenv("TWITTER_API_KEY")
API_SECRET = API_SECRETS[0] if API_SECRETS else os.getenv("TWITTER_API_SECRET")
ACCESS_TOKEN = ACCESS_TOKENS[0] if ACCESS_TOKENS else os.getenv("TWITTER_ACCESS_TOKEN")
ACCESS_SECRET = ACCESS_SECRETS[0] if ACCESS_SECRETS else os.getenv("TWITTER_ACCESS_SECRET")
BEARER_TOKEN = BEARER_TOKENS[0] if BEARER_TOKENS else os.getenv("TWITTER_BEARER_TOKEN")

# GOOGLE GEMINI API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# GROQ API
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
DEBUG = os.getenv("DEBUG", "True").lower() == "true"
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))

# Validate required environment variables
# We ONLY enforce variables required for the server to actually run (DB + Security).
# API Keys are now optional because they can be loaded from the Database per user.
REQUIRED_VARS = [
    # "DATABASE_URL", # Uncomment if you want to strictly enforce DB URL presence
    # "SECRET_KEY"    # Uncomment if you want to enforce a custom secret key
]

missing_vars = [var for var in REQUIRED_VARS if not os.getenv(var)]
if missing_vars:
    raise EnvironmentError(
        f"Missing required environment variables: {', '.join(missing_vars)}\n"
        f"Please create a .env file based on .env.example"
    )

# Log number of accounts loaded for scraping
print(f"Loaded {len(API_KEYS)} System Twitter API credential set(s).") 
print("Note: Individual user credentials will be loaded from the database.")