from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl, validator
import uvicorn
import os
import logging
from logging.handlers import RotatingFileHandler
from typing import Optional, Dict, List, Any
import re
import asyncio
import sqlite3
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, RetryError
from datetime import datetime, timedelta
from jose import JWTError, jwt

# Import our modules
import scraper
import ai_agent
import poster
import utils
import config
import httpx

# Configure comprehensive logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler('app.log', maxBytes=10485760, backupCount=5),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize Database
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting application...")
    utils.init_pool() # Initialize the pool
    utils.init_db()
    yield
    # Close pool on shutdown
    if utils.pg_pool:
        try:
            utils.pg_pool.close(timeout=5)
        except Exception as e:
            logger.warning(f"Error closing pool: {e}")

app = FastAPI(title="AI Reply Agent", lifespan=lifespan)

# Global Exception Handler
from fastapi.responses import JSONResponse
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    error_msg = f"Global error: {str(exc)}\n{traceback.format_exc()}"
    print(error_msg) # Print to stdout/stderr for Docker logs
    try:
        logger.error(error_msg)
    except:
        pass
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "error": str(exc)},
    )

@app.get("/api/health")
async def health_check():
    """Check system health and DB access."""
    try:
        # Try to write to DB
        with utils.get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT count(*) FROM users")
            count = c.fetchone()[0]
        return {"status": "healthy", "user_count": count, "db_write": "ok"}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "unhealthy", "error": str(e)}
        )

# Auth Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")

class Token(BaseModel):
    access_token: str
    token_type: str

class User(BaseModel):
    username: str
    id: Optional[int] = None
    credits: int = 0

class UserCreate(BaseModel):
    username: str
    password: str
    ref: Optional[str] = None

    @validator('password')
    def validate_password(cls, v):
        if len(v.encode('utf-8')) > 70:
            raise ValueError('Password must be less than 70 bytes')
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        return v

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = utils.get_user(username)
    if user is None:
        raise credentials_exception
    return user

# Rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS Configuration - Restrict to specific origins in production
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "PUT", "PATCH"],
    allow_headers=["Content-Type", "Authorization"],
)

# Auth Endpoints

@app.post("/api/auth/signup", response_model=Token)
async def signup(user: UserCreate):
    try:
        # 0. Check if username exists
        db_user = utils.get_user(user.username)
        if db_user:
            raise HTTPException(status_code=400, detail="Username already registered")

        # 1. Handle referral
        referred_by_id = None
        if user.ref:
            referred_by_user = utils.get_user_by_referral_code(user.ref)
            if referred_by_user:
                referred_by_id = referred_by_user['id']
                logger.info(f"User {user.username} referred by {referred_by_user['username']} ({referred_by_id})")

        utils.create_user(user.username, user.password, referred_by=referred_by_id)
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": user.username}, expires_delta=access_token_expires
        )
        return {"access_token": access_token, "token_type": "bearer"}
    except Exception as e:
        if "IntegrityError" in str(e) or "duplicate key" in str(e):
             raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already registered"
            )
        logger.error(f"Signup error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not create user account: {str(e)}"
        )
@app.post("/api/auth/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = utils.get_user(form_data.username)
    if not user or not utils.verify_password(form_data.password, user['password_hash']):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user['username']}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/api/auth/me", response_model=User)
async def read_users_me(current_user: dict = Depends(get_current_user)):
    return {
        "username": current_user["username"], 
        "id": current_user["id"],
        "credits": current_user.get("credits", 0)
    }

# --- Twitter OAuth 2.0 PKCE Flow ---

# In-memory store for code_verifier mapped by state (dict: state -> code_verifier)
oauth_states = {}

@app.get("/api/auth/twitter/login")
async def twitter_login(request: Request, current_user: dict = Depends(get_current_user)):
    """Generate the OAuth 2.0 Authorization URL for the user."""
    import tweepy
    import secrets
    
    if not config.TWITTER_CLIENT_ID or not config.TWITTER_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Twitter Client ID and Secret not configured")
        
    oauth2_user_handler = tweepy.OAuth2UserHandler(
        client_id=config.TWITTER_CLIENT_ID,
        redirect_uri=config.OAUTH_CALLBACK_URL,
        scope=["tweet.read", "tweet.write", "users.read", "offline.access"],
        client_secret=config.TWITTER_CLIENT_SECRET
    )

    auth_url = oauth2_user_handler.get_authorization_url()
    
    # Extract state parameter from auth_url
    from urllib.parse import urlparse, parse_qs
    parsed_url = urlparse(auth_url)
    state = parse_qs(parsed_url.query).get('state', [None])[0]
    
    if state:
        # Save code_verifier mapped to state, along with user_id
        oauth_states[state] = {
            "code_verifier": oauth2_user_handler._code_verifier,
            "user_id": current_user["id"]
        }
        
    return {"url": auth_url}

from fastapi.responses import HTMLResponse

@app.get("/api/auth/twitter/callback")
async def twitter_callback(request: Request, state: str, code: str):
    """Handle the OAuth 2.0 callback from Twitter."""
    import tweepy
    
    if state not in oauth_states:
        return HTMLResponse("<html><body><h3>Error: Invalid state. Please try logging in again.</h3></body></html>", status_code=400)
        
    state_data = oauth_states.pop(state)
    user_id = state_data["user_id"]
    code_verifier = state_data["code_verifier"]

    try:
        oauth2_user_handler = tweepy.OAuth2UserHandler(
            client_id=config.TWITTER_CLIENT_ID,
            redirect_uri=config.OAUTH_CALLBACK_URL,
            scope=["tweet.read", "tweet.write", "users.read", "offline.access"],
            client_secret=config.TWITTER_CLIENT_SECRET
        )
        
        # We must restore the code_verifier we saved earlier
        oauth2_user_handler._code_verifier = code_verifier
        
        # This exchanges the code for the access token
        access_token = oauth2_user_handler.fetch_token(
            f"{config.OAUTH_CALLBACK_URL}?state={state}&code={code}"
        )
        
        # Save to user settings
        creds = {
            "oauth2": True,
            "access_token": access_token.get("access_token"),
            "refresh_token": access_token.get("refresh_token"),
            "expires_at": access_token.get("expires_at")
        }
        utils.save_setting("posting_credentials", creds, user_id=user_id)
        utils.add_log("Successfully connected Twitter account via OAuth 2.0", user_id=user_id)
        
        # Redirect back to the frontend settings page
        return HTMLResponse(
            "<html><body><script>window.location.href = '/?view=settings';</script></body></html>"
        )
    except Exception as e:
        logger.error(f"OAuth Callback Error: {e}")
        return HTMLResponse(f"<html><body><h3>Error connecting Twitter account: {e}</h3></body></html>", status_code=500)

# Data Models with Validation
class ScrapeRequest(BaseModel):
    url: str
    
    @validator('url')
    def validate_twitter_url(cls, v):
        """Validate that we can extract a Tweet ID from the input."""
        try:
            # We use the util function to validate if an ID can be extracted
            # This allows standard links, intent links, and raw IDs
            utils.extract_tweet_id(v)
            return v
        except ValueError:
            raise ValueError('Invalid input: Must be a Twitter URL, Intent link, or Tweet ID')

class GenerateRequest(BaseModel):
    tweet_text: str
    tone: str = "professional"
    
    @validator('tweet_text')
    def validate_tweet_text(cls, v):
        """Validate tweet text is not empty."""
        if not v or not v.strip():
            raise ValueError('Tweet text cannot be empty')
        return v.strip()
    
    @validator('tone')
    def validate_tone(cls, v):
        """Validate tone is one of the allowed values."""
        allowed_tones = ['professional', 'casual', 'witty', 'friendly', 'shuffle']
        if v not in allowed_tones:
            raise ValueError(f'Tone must be one of: {", ".join(allowed_tones)}')
        return v

class PostRequest(BaseModel):
    reply_text: str
    reply_to_id: str
    tweet_text: Optional[str] = None
    
    @validator('reply_text')
    def validate_reply_text(cls, v):
        """Validate reply text."""
        if not v or not v.strip():
            raise ValueError('Reply text cannot be empty')
        if len(v) > 280:
            raise ValueError('Reply text exceeds 280 characters')
        return v

@app.get("/api/user/referrals")
async def get_user_referrals(current_user: dict = Depends(get_current_user)):
    """Get the current user's referral code and list of referrals."""
    try:
        # Safety check: if code is missing for old user, generate one on the fly
        ref_code = current_user.get("referral_code")
        if not ref_code:
            ref_code = utils.generate_referral_code()
            with utils.get_db_connection() as conn:
                c = conn.cursor()
                ph = utils.get_placeholder()
                c.execute(f"UPDATE users SET referral_code = {ph} WHERE id = {ph}", (ref_code, current_user['id']))
            logger.info(f"Generated missing referral code for user {current_user['username']}")

        referrals = utils.get_user_referrals(current_user['id'])
        return {
            "referral_code": ref_code,
            "referrals": referrals
        }
    except Exception as e:
        logger.error(f"Error getting referrals: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve referrals")

@app.get("/api/logs")
@limiter.limit("20/minute")
async def get_logs(request: Request, current_user: dict = Depends(get_current_user)):
    """Get recent logs."""
    try:
        return utils.get_recent_logs(user_id=current_user['id'])
    except Exception as e:
        logger.error(f"Error getting logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve logs")

@app.get("/api/stats")
@limiter.limit("20/minute")
async def get_stats(request: Request, current_user: dict = Depends(get_current_user)):
    """Get user statistics."""
    try:
        stats = utils.get_stats(current_user['id'])
        # Calculate success rate
        if stats['count'] > 0:
            stats['success_rate'] = round((stats['success_count'] / stats['count']) * 100)
        else:
            stats['success_rate'] = 0
        
        # Get daily history for chart
        daily_stats = utils.get_daily_stats(current_user['id'], days=7)
        return {
            "success_rate": stats['success_rate'],
            "daily": daily_stats
        }
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve stats")

@app.get("/api/admin/stats")
async def get_admin_stats(request: Request, current_user: dict = Depends(get_current_user)):
    """Admin only: Get usage stats for all users."""
    if current_user['username'] != 'web3kaiju':
        raise HTTPException(status_code=403, detail="Admin access required")
        
    try:
        return utils.get_all_user_stats()
    except Exception as e:
        logger.error(f"Error getting admin stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve admin stats")

@app.get("/api/history")
@limiter.limit("20/minute")
async def get_history(request: Request, current_user: dict = Depends(get_current_user)):
    """Get reply history."""
    try:
        return utils.get_history(user_id=current_user['id'])
    except Exception as e:
        logger.error(f"Error getting history: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve history")

@app.get("/api/queue")
@limiter.limit("100/minute")  # Changed from 30 to 100
async def get_queue(request: Request, current_user: dict = Depends(get_current_user)):
    """Get all items in the review queue."""
    try:
        return utils.get_queue(user_id=current_user['id'])
    except Exception as e:
        logger.error(f"Error getting queue: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve queue")

class QueueItem(BaseModel):
    tweet_id: str
    tweet_text: str
    reply_text: str

@app.post("/api/queue")
@limiter.limit("100/minute") 
async def add_to_queue(request: Request, item: QueueItem, current_user: dict = Depends(get_current_user)):
    """Add an item to the review queue."""
    try:
        queue_id = utils.add_to_queue(item.tweet_id, item.tweet_text, item.reply_text, user_id=current_user['id'])
        logger.info(f"Added item {queue_id} to queue")
        return {"status": "success", "queue_id": queue_id}
    except Exception as e:
        logger.error(f"Error adding to queue: {e}")
        raise HTTPException(status_code=500, detail="Failed to add to queue")

@app.delete("/api/queue/{queue_id}")
@limiter.limit("30/minute")
async def remove_from_queue(request: Request, queue_id: int, current_user: dict = Depends(get_current_user)):
    """Remove an item from the review queue."""
    try:
        deleted = utils.remove_from_queue(queue_id, user_id=current_user['id'])
        if not deleted:
            raise HTTPException(status_code=404, detail="Queue item not found")
        logger.info(f"Removed item {queue_id} from queue")
        return {"status": "success", "message": f"Queue item {queue_id} removed"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing from queue: {e}")
        raise HTTPException(status_code=500, detail="Failed to remove from queue")

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type(Exception)
)
async def scrape_tweet_with_retry(tweet_id: str, user_id: int = None, tweet_url: str = None):
    """Helper function to scrape with retry logic."""
    # scraper.get_tweet_text is now synchronous, so run it in thread pool
    return await asyncio.wait_for(
        asyncio.to_thread(scraper.get_tweet_text, tweet_id, user_id, tweet_url), 
        timeout=30.0
    )

@app.post("/api/scrape")
@limiter.limit("10/minute")
async def scrape_tweet(request: Request, scrape_req: ScrapeRequest, current_user: dict = Depends(get_current_user)):
    """Scrape tweet content with rate limiting and retry logic."""
    try:
        # Extract ID from URL with validation
        tweet_id = utils.extract_tweet_id(scrape_req.url)
        msg = f"Scraping tweet ID: {tweet_id}"
        logger.info(msg)
        utils.add_log(msg, user_id=current_user['id'])
        
        # Add timeout to prevent hanging
        try:
            text = await scrape_tweet_with_retry(tweet_id, user_id=current_user['id'], tweet_url=scrape_req.url)
        except RetryError as e:
            logger.error(f"Retry failed for {tweet_id}: {e}")
            # Check if it was a rate limit error
            if "TooManyRequests" in str(e) or "429" in str(e):
                raise HTTPException(status_code=429, detail="Twitter API rate limit exceeded. Please try again later.")
            raise HTTPException(status_code=500, detail="Failed to scrape tweet after multiple attempts")
        except asyncio.TimeoutError:
            error_msg = f"Timeout while scraping tweet {tweet_id}"
            logger.error(error_msg)
            utils.add_log(error_msg, "ERROR", user_id=current_user['id'])
            raise HTTPException(status_code=504, detail="Request timeout")
        
        if "Error" in text:
            utils.add_log(f"Error scraping {tweet_id}: {text}", "ERROR", user_id=current_user['id'])
            raise HTTPException(status_code=400, detail=text)
            
        utils.add_log(f"Successfully scraped {tweet_id}", user_id=current_user['id'])
        # TRACKING: Increment scraped count
        utils.increment_scraped_count(current_user['id'])
        return {"tweet_id": tweet_id, "text": text}
        
    except HTTPException:
        raise
    except ValueError as ve:
        logger.error(f"Validation error: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        err_msg = f"Scrape error: {str(e)}"
        logger.error(err_msg)
        utils.add_log(err_msg, "ERROR", user_id=current_user['id'])
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/mark_done")
async def mark_done(request: Request, post_req: PostRequest, current_user: dict = Depends(get_current_user)):
    """Manually mark a reply as done (for manual posting)."""
    try:
        # 1. Extra strict validation
        if not post_req.reply_text or not post_req.reply_text.strip():
            # Log it so we know why it failed
            logger.warning(f"Attempted to mark done with empty text for ID {post_req.reply_to_id}")
            raise HTTPException(status_code=400, detail="Reply text cannot be empty")

        msg = f"Manually marking reply as done for ID: {post_req.reply_to_id}"
        logger.info(msg)
        utils.add_log(msg, user_id=current_user['id'])
        
        # 2. Use Keyword Arguments to prevent any order mix-ups
        utils.add_history(
            tweet_id=post_req.reply_to_id, 
            reply_text=post_req.reply_text, 
            status="posted", 
            user_id=current_user['id'],
            tweet_text=post_req.tweet_text
        )
        
        # 3. Increment stats
        utils.increment_reply_count(user_id=current_user['id'])
        
        return {"status": "success", "message": "Marked as done"}
        
    except HTTPException:
        raise
    except Exception as e:
        err_msg = f"Error marking as done: {str(e)}"
        logger.error(err_msg)
        # Only log to DB if we can, to prevent loops
        try:
            utils.add_log(err_msg, "ERROR", user_id=current_user['id'])
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")



@app.post("/api/generate")
@limiter.limit("15/minute")
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception)
)
async def generate_reply(request: Request, gen_req: GenerateRequest, current_user: dict = Depends(get_current_user)):
    """Generate AI reply with rate limiting and retry logic."""
    try:
        msg = f"Generating reply for text: {gen_req.tweet_text[:50]}..."
        logger.info(msg)
        utils.add_log(msg, user_id=current_user['id'])
        
        # Add timeout
        try:
            reply = await asyncio.wait_for(
                asyncio.to_thread(ai_agent.generate_reply, gen_req.tweet_text, gen_req.tone, current_user['id']),
                timeout=30.0
            )
            
            # TRACKING: Increment generated count
            if "Error" not in reply:
                utils.increment_generated_count(current_user['id'])
                
            return {"reply": reply}
        except asyncio.TimeoutError:
            error_msg = "Timeout while generating reply"
            logger.error(error_msg)
            utils.add_log(error_msg, "ERROR", user_id=current_user['id'])
            raise HTTPException(status_code=504, detail="Request timeout")
        
        raise
    except Exception as e:
        err_msg = f"Posting error: {str(e)}"
        logger.error(err_msg)
        utils.add_log(err_msg, "ERROR", user_id=current_user['id'])
        raise HTTPException(status_code=500, detail=str(e))

# Settings Endpoints

@app.get("/api/settings")
async def get_settings(request: Request, current_user: dict = Depends(get_current_user)):
    """Get all application settings."""
    try:
        posting_creds = utils.get_setting("posting_credentials", {}, user_id=current_user['id'])
        scraping_creds = utils.get_setting("scraping_credentials", [], user_id=current_user['id'])
        
        # Mask secrets for security
        masked_posting = posting_creds.copy()
        if masked_posting:
            masked_posting["api_secret"] = "********"
            masked_posting["access_secret"] = "********"
            
        masked_scraping = []
        for cred in scraping_creds:
            masked = cred.copy()
            masked["api_secret"] = "********"
            masked["access_secret"] = "********"
            masked_scraping.append(masked)
            
        return {
            "posting_credentials": masked_posting,
            "scraping_credentials": masked_scraping,
            "gemini_api_key": utils.get_setting("gemini_api_key", "", user_id=current_user['id'])
        }
    except Exception as e:
        logger.error(f"Error getting settings: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve settings")

class SettingsRequest(BaseModel):
    posting_credentials: Optional[Dict[str, str]] = None
    scraping_credentials: Optional[List[Dict[str, str]]] = None
    gemini_api_key: Optional[str] = None

@app.post("/api/settings")
async def save_settings(request: Request, settings: SettingsRequest, current_user: dict = Depends(get_current_user)):
    """Save application settings."""
    try:
        if settings.posting_credentials is not None:
            # Don't overwrite with masked values if they weren't changed
            current_creds = utils.get_setting("posting_credentials", {}, user_id=current_user['id'])
            new_creds = settings.posting_credentials
            
            if new_creds.get("api_secret") == "********":
                new_creds["api_secret"] = current_creds.get("api_secret", "")
            if new_creds.get("access_secret") == "********":
                new_creds["access_secret"] = current_creds.get("access_secret", "")
                
            utils.save_setting("posting_credentials", new_creds, user_id=current_user['id'])
            
        if settings.scraping_credentials is not None:
            # Handle masking for list
            current_list = utils.get_setting("scraping_credentials", [], user_id=current_user['id'])
            new_list = []
            
            for i, cred in enumerate(settings.scraping_credentials):
                if cred.get("api_secret") == "********":
                    # Try to find matching original secret (assuming order is preserved or index matching)
                    if i < len(current_list):
                        cred["api_secret"] = current_list[i].get("api_secret", "")
                
                if cred.get("access_secret") == "********":
                    if i < len(current_list):
                        cred["access_secret"] = current_list[i].get("access_secret", "")
                
                new_list.append(cred)
                
            utils.save_setting("scraping_credentials", new_list, user_id=current_user['id'])

        if settings.gemini_api_key is not None:
            utils.save_setting("gemini_api_key", settings.gemini_api_key, user_id=current_user['id'])
            
        utils.add_log("Settings updated successfully", user_id=current_user['id'])
        return {"status": "success", "message": "Settings saved"}
    except Exception as e:
        logger.error(f"Error saving settings: {e}")
        raise HTTPException(status_code=500, detail="Failed to save settings")

# Batch Processing Manager
class BatchSession:
    def __init__(self, user_id: int, urls: List[str], tone: str):
        self.user_id = user_id
        self.urls = urls
        self.tone = tone
        self.total_urls = len(urls)
        self.current_index = 0
        self.current_url = ""
        self.is_processing = True
        self.should_stop = False
        self.task = None
        self.api_cooldown_until = None  # Track when to retry API

class BatchManager:
    def __init__(self):
        self.sessions: Dict[int, BatchSession] = {}

    async def start(self, urls: List[str], tone: str, user_id: int):
        if user_id in self.sessions and self.sessions[user_id].is_processing:
             raise HTTPException(status_code=400, detail="You already have a batch process running")
        
        # Credit Check (Estimate)
        credits = utils.get_user_credits(user_id)
        cost_per_tweet = 5
        if credits < cost_per_tweet:
             raise HTTPException(status_code=402, detail=f"Insufficient credits. You need at least {cost_per_tweet} credits to start.")

        # Create new session
        session = BatchSession(user_id, urls, tone)
        self.sessions[user_id] = session
        
        # Start background task
        session.task = asyncio.create_task(self._process_batch(session))
        utils.add_log(f"Started batch processing for {len(urls)} URLs. Credits: {credits}", user_id=user_id)

    def stop(self, user_id: int):
        if user_id in self.sessions and self.sessions[user_id].is_processing:
            self.sessions[user_id].should_stop = True
            utils.add_log("Stopping batch process...", "WARNING", user_id=user_id)

    async def _process_batch(self, session: BatchSession):
        """
        Process URLs in batches of 5.
        1. Batch Scrape (5 URLs -> 1 API Call)
        2. Batch Generate (5 Texts -> 1 AI Call)
        """
        try:
            total_urls = len(session.urls)
            chunk_size = 5
            
            # chunk urls
            chunks = [session.urls[i:i + chunk_size] for i in range(0, total_urls, chunk_size)]
            
            for batch_index, chunk_urls in enumerate(chunks):
                if session.should_stop: break
                
                utils.add_log(f"Starting Batch {batch_index + 1}/{len(chunks)} ({len(chunk_urls)} items)", user_id=session.user_id)
                
                # 1. Prepare IDs for this batch
                batch_ids_to_scrape = [] # Only scrape these
                cached_tweets = [] # Already found
                
                # Map tweet_id -> url (for logging errors)
                id_to_url = {}
                
                # Pre-filter (History check)
                for url in chunk_urls:
                    try:
                        t_id = utils.extract_tweet_id(url)
                        # Check History
                        if utils.has_user_processed(session.user_id, t_id):
                            utils.add_log(f"Skipping {t_id}: You have already processed this.", "WARNING", user_id=session.user_id)
                            continue
                            
                        # Check Cache
                        cached_text = utils.get_cached_tweet_content(t_id)
                        if cached_text:
                            utils.add_log(f"Found {t_id} in Shared Pool! Skipping scrape...", "INFO", user_id=session.user_id)
                            cached_tweets.append({"id": t_id, "text": cached_text})
                        else:
                            batch_ids_to_scrape.append(t_id)

                        id_to_url[t_id] = url
                    except:
                        utils.add_log(f"Skipping invalid URL: {url}", "ERROR", user_id=session.user_id)

                # 2. Batch Scrape (Only scrape what we don't have)
                scraped_data = {}
                if batch_ids_to_scrape:
                    # Rotation Index = batch_index (Ensures Batch 1 -> Key 1, Batch 2 -> Key 2)
                    utils.add_log(f"  > Batch Scraping {len(batch_ids_to_scrape)} tweets...", "INFO", user_id=session.user_id)
                    await asyncio.sleep(2) # Small safety delay
                    
                    # Rate limit retry logic
                    max_rate_limit_retries = 3
                    rate_limit_cooldown_seconds = 900  # 15 minutes
                    
                    for retry_attempt in range(max_rate_limit_retries + 1):
                        if session.should_stop: break
                        
                        # 0. Check Cooldown
                        if getattr(session, 'api_cooldown_until', None):
                            now = datetime.now()
                            if now < session.api_cooldown_until:
                                sleep_seconds = (session.api_cooldown_until - now).total_seconds()
                                utils.add_log(f"API rate limited. Pausing processing for {int(sleep_seconds // 60)} minutes...", "WARNING", user_id=session.user_id)
                                
                                # Sleep in smaller chunks so we can check if user stopped the batch
                                while datetime.now() < session.api_cooldown_until:
                                    if session.should_stop: break
                                    await asyncio.sleep(5)
                                    
                            if not session.should_stop:
                                session.api_cooldown_until = None # Cooldown expired
                                utils.add_log(f"API cooldown expired. Resuming API attempts.", "INFO", user_id=session.user_id)
                                
                        if session.should_stop: break

                        # Current scraper.get_tweets_batch is synchronous, run in thread
                        scraped_data = await asyncio.to_thread(
                            scraper.get_tweets_batch, 
                            tweet_ids=batch_ids_to_scrape, 
                            user_id=session.user_id, 
                            rotation_index=batch_index
                        )
                        
                        # Check if all accounts failed (Rate Limit or Auth Error)
                        if scraped_data.get("_all_failed"):
                            if retry_attempt < max_rate_limit_retries:
                                cooldown_mins = 15
                                session.api_cooldown_until = datetime.now() + timedelta(minutes=cooldown_mins)
                                utils.add_log(
                                    f"All API keys exhausted. Initiating {cooldown_mins}m background cooldown before retry...", 
                                    "WARNING", 
                                    user_id=session.user_id
                                )
                                scraped_data = {} # Clear error flags
                                continue # Go to next retry attempt, which handles the sleep
                            else:
                                utils.add_log(f"Max retries reached after cooldowns. Skipping these tweets.", "ERROR", user_id=session.user_id)
                                scraped_data = {}
                                break # Exit retry loop
                        else:
                            # Success or normal partial failure
                            break
                    
                    # Remove any metadata keys from scraped_data
                    scraped_data = {k: v for k, v in scraped_data.items() if not k.startswith("_")}
                    
                    # Log missing IDs (no fallback anymore)
                    missing_ids = [tid for tid in batch_ids_to_scrape if tid not in scraped_data]
                    if missing_ids:
                        utils.add_log(f"{len(missing_ids)} tweets missed by API. (No fallback available)", "WARNING", user_id=session.user_id)

                    
                    # Remove any metadata keys from scraped_data
                    scraped_data = {k: v for k, v in scraped_data.items() if not k.startswith("_")}
                    
                    # TRACKING: Increment scraped count for batch
                    if scraped_data:
                        utils.increment_scraped_count(session.user_id, len(scraped_data))
                else:
                    if not cached_tweets:
                         continue # Empty batch after filtering
                
                # 3. Check what we got
                valid_tweets_for_ai = [] # List of dicts {'id': '...', 'text': '...'}
                
                # Add cached items
                valid_tweets_for_ai.extend(cached_tweets)
                
                # Add scraped items
                if batch_ids_to_scrape:
                    for t_id in batch_ids_to_scrape:
                        if t_id in scraped_data:
                            text = scraped_data[t_id]
                            # Cache it
                            utils.cache_tweet_content(t_id, text)
                            valid_tweets_for_ai.append({"id": t_id, "text": text})
                        else:
                            utils.add_log(f"  > Failed to scrape {t_id} (Deleted or Access Denied)", "ERROR", user_id=session.user_id)

                if not valid_tweets_for_ai:
                    utils.add_log(f"  > No valid tweets obtained in this batch.", "WARNING", user_id=session.user_id)
                    continue

                # 4. Batch Generate
                current_tone = session.tone
                if session.tone == "shuffle":
                    tones = ['professional', 'casual', 'witty', 'friendly']
                    current_tone = tones[batch_index % len(tones)]
                    utils.add_log(f"  > Shuffle Mode: Using '{current_tone}' tone for this batch.", "INFO", user_id=session.user_id)

                utils.add_log(f"  > Generating batch replies ({len(valid_tweets_for_ai)} items)...", "INFO", user_id=session.user_id)
                
                try:
                    generated_replies = await asyncio.to_thread(
                        ai_agent.generate_batch_replies,
                        tweets_data=valid_tweets_for_ai,
                        tone=current_tone,
                        user_id=session.user_id
                    )
                    
                    # TRACKING: Increment generated count for batch
                    if generated_replies:
                        utils.increment_generated_count(session.user_id, len(generated_replies))
                    
                    # 5. Add to Queue
                    for item in generated_replies:
                        t_id = item.get("id")
                        reply = item.get("reply")
                        
                        # Find original text for logging/queue
                        original_text = next((t["text"] for t in valid_tweets_for_ai if t["id"] == t_id), "")
                        
                        if reply and "Error" not in reply:
                            # DEDUCT CREDITS
                            # Cost: 5 credits per successful reply
                            if utils.deduct_credits(session.user_id, 5):
                                utils.add_to_queue(t_id, original_text, reply, user_id=session.user_id)
                                utils.add_log(f"  Ready: {t_id} (Credits -5)", "SUCCESS", user_id=session.user_id)
                            else:
                                utils.add_log(f"  Paused {t_id}: Insufficient credits to finalize.", "ERROR", user_id=session.user_id)
                                session.should_stop = True # Stop the batch
                                break # Exit loop
                        else:
                             utils.add_log(f"  > Generation error for {t_id}: {reply}", "ERROR", user_id=session.user_id)
                             
                except Exception as e:
                    utils.add_log(f"Batch AI Generation Failed: {e}", "ERROR", user_id=session.user_id)

                # Batch Cooldown
                await asyncio.sleep(2)

            if session.should_stop:
                utils.add_log("Batch processing stopped by user", "WARNING", user_id=session.user_id)
            else:
                utils.add_log("Batch processing complete", "SUCCESS", user_id=session.user_id)
                
        except Exception as e:
            utils.add_log(f"Batch processing crashed: {e}", "ERROR", user_id=session.user_id)
        finally:
            session.is_processing = False
            session.current_url = ""
            session.task = None
            if session.user_id in self.sessions:
                del self.sessions[session.user_id]

# --- ADMIN ENDPOINTS ---

@app.get("/api/admin/stats")
async def get_admin_stats(current_user: dict = Depends(get_current_user)):
    """Get stats for all users (Admin only)."""
    if current_user['username'].lower() != 'web3kaiju':
        raise HTTPException(status_code=403, detail="Admin access required")
    
    stats = utils.get_all_user_stats()
    return stats

class AddCreditsRequest(BaseModel):
    username: str
    amount: int

@app.post("/api/admin/credits")
async def add_user_credits(req: AddCreditsRequest, current_user: dict = Depends(get_current_user)):
    """Add credits to a user (Admin only)."""
    if current_user['username'].lower() != 'web3kaiju':
        raise HTTPException(status_code=403, detail="Admin access required")
    
    success = utils.add_credits(req.username, req.amount)
    if not success:
        raise HTTPException(status_code=404, detail="User not found")
    
    utils.add_log(f"Admin added {req.amount} credits to {req.username}", "WARNING", user_id=current_user['id'])
    return {"status": "success", "message": f"Added {req.amount} credits to {req.username}"}

batch_manager = BatchManager()

class BatchStartRequest(BaseModel):
    urls: List[str]
    tone: str = "professional"
    payment_proof: Optional[Dict[str, Any]] = None

@app.post("/api/batch/start")
async def start_batch(request: BatchStartRequest, current_user: dict = Depends(get_current_user)):
    """Start batch processing."""
    # Start batch without payment verification
    try:
        await batch_manager.start(request.urls, request.tone, current_user['id'])
        return {"status": "success", "message": "Batch processing started"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))



@app.post("/api/batch/stop")
async def stop_batch(current_user: dict = Depends(get_current_user)):
    """Stop batch processing."""
    batch_manager.stop(current_user['id'])
    return {"status": "stopping"}

@app.get("/api/dashboard/summary")
async def get_dashboard_summary(request: Request, current_user: dict = Depends(get_current_user)):
    """Unified endpoint for dashboard status, logs, and queue."""
    try:
        # 1. Batch Status
        session = batch_manager.sessions.get(current_user['id'])
        batch_status = {
            "is_processing": session.is_processing,
            "current_url": session.current_url,
            "current_index": session.current_index,
            "total_urls": session.total_urls
        } if session else {"is_processing": False}
        
        # 2. Recent Logs
        logs = utils.get_recent_logs(user_id=current_user['id'])
        
        # 3. Queue Items
        queue = utils.get_queue(user_id=current_user['id'])
        
        # 4. Credits (for instant header update)
        credits = utils.get_user_credits(current_user['id'])
        
        return {
            "batch": batch_status,
            "logs": logs,
            "queue": queue,
            "credits": credits
        }
    except Exception as e:
        logger.error(f"Error getting dashboard summary: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve dashboard summary")

class VerifyPaymentRequest(BaseModel):
    reference: str

@app.get("/api/config/payment")
async def get_payment_config():
    """Returns the Paystack public key for the frontend."""
    return {
        "squad_public_key": config.SQUAD_PUBLIC_KEY
    }

@app.post("/api/payment/verify")
async def verify_payment(req: VerifyPaymentRequest, current_user: dict = Depends(get_current_user)):
    """Verify a Squad payment and add credits to the user."""
    if not config.SQUAD_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Squad API key not configured")
        
    try:
        logger.info(f"DEBUG: Using SQUAD_API_BASE='{config.SQUAD_API_BASE}'")
        url = f"{config.SQUAD_API_BASE}/transaction/verify/{req.reference}"
        headers = {
            "Authorization": f"Bearer {config.SQUAD_SECRET_KEY.strip()}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64 AppleWebKit/537.36)"
        }
        utils.add_log(f"Initiating Squad verification for ref: {req.reference}", "INFO", user_id=current_user['id'])
        
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            retry=retry_if_exception_type(httpx.RequestError),
            reraise=True
        )
        async def call_squad_api():
            async with httpx.AsyncClient(http2=False) as client:
                return await client.get(url, headers=headers, timeout=15.0)

        response = await call_squad_api()
            
        logger.info(f"Squad API response for {req.reference}: {response.status_code}")
        if response.status_code != 200:
            logger.error(f"Squad Verification Failed. Status: {response.status_code}, Body: {response.text}")
            raise HTTPException(status_code=400, detail=f"Squad verification failed with status {response.status_code}")
            
        data = response.json()
        tx_data = data.get("data")
        
        # DEBUG: Log the actual transaction data to identify missing keys
        logger.info(f"Squad Transaction Data for {req.reference}: {tx_data}")
        
        if not tx_data or tx_data.get("transaction_status", "").lower() != "success":
            status = tx_data.get("transaction_status") if tx_data else "Unknown"
            raise HTTPException(status_code=400, detail=f"Payment status is: {status}")
            
        # Success! Now update the database
        # 1. Try to complete existing transaction
        tx = utils.complete_transaction(req.reference)
        
        if not tx:
            # 2. If it doesn't exist, use meta/metadata for credits if available
            # Squad uses 'meta', Paystack uses 'metadata'
            metadata = tx_data.get("meta") or tx_data.get("metadata")
            credits_to_add = 0
            
            if metadata and isinstance(metadata, dict):
                credits_to_add = int(metadata.get("credits", 0))
            
            # Fallback calculation if metadata is missing
            if credits_to_add <= 0:
                try:
                    # Squad uses 'transaction_amount', Paystack uses 'amount'
                    amount_kobo = int(tx_data.get("transaction_amount") or tx_data.get("amount") or 0)
                    amount_ngn = amount_kobo / 100
                    # Use default rate: 1 NGN = 3 credits
                    credits_to_add = int(amount_ngn * 3)
                except (ValueError, TypeError) as e:
                    logger.error(f"Error parsing amount from Squad: {e}")
                    credits_to_add = 0
            
            # Create and complete
            amount_kobo_final = int(tx_data.get("transaction_amount") or tx_data.get("amount") or 0)
            amount_ngn_final = amount_kobo_final / 100
            utils.create_transaction(current_user['id'], req.reference, amount_ngn_final, credits_to_add)
            tx = utils.complete_transaction(req.reference)
            
        if not tx:
            raise HTTPException(status_code=500, detail="Could not process transaction in database")
            
        utils.add_log(f"Payment verified for ref: {req.reference}. Added {tx['credits_added']} credits.", "SUCCESS", user_id=current_user['id'])
        
        return {
            "status": "success", 
            "credits_added": tx['credits_added'],
            "new_balance": utils.get_user_credits(current_user['id'])
        }
        
    except httpx.RequestError as e:
        logger.error(f"Network error verifying payment: {repr(e)}")
        raise HTTPException(status_code=503, detail=f"Could not connect to Squad gateway: {type(e).__name__}. Please try again.")
    except Exception as e:
        logger.error(f"Unexpected error in payment verification: {repr(e)}")
        if isinstance(e, HTTPException): raise
        raise HTTPException(status_code=500, detail=str(e))



# Serve Static Files (SPA Support)
# This MUST be last to allow API routes to work first
app.mount("/", StaticFiles(directory="static", html=True), name="static")
