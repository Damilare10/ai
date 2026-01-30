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
    # Close pool on shutdown if you want to be clean
    if utils.pg_pool: utils.pg_pool.closeall()

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

class UserCreate(BaseModel):
    username: str
    password: str

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
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

# Auth Endpoints

@app.post("/api/auth/signup", response_model=Token)
async def signup(user: UserCreate):
    try:
        db_user = utils.get_user(user.username)
        if db_user:
            raise HTTPException(status_code=400, detail="Username already registered")
            
        # Debug logging
        print(f"DEBUG: Signup request for user '{user.username}'")
        print(f"DEBUG: Password received: '{user.password}'")
        print(f"DEBUG: Password length: {len(user.password)}")
        print(f"DEBUG: Password bytes: {len(user.password.encode('utf-8'))}")
        import passlib
        print(f"DEBUG: passlib version: {passlib.__version__}")

        utils.create_user(user.username, user.password)
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
    return {"username": current_user["username"], "id": current_user["id"]}

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
        allowed_tones = ['professional', 'casual', 'witty', 'friendly']
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
@limiter.limit("20/minute")
async def get_logs(request: Request):
    """Get recent logs."""
    try:
        return utils.get_recent_logs()
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
        # We need to fetch more data for the chart if not present in stats table
        # But for now, let's just return what we have. 
        # Wait, the frontend expects 'daily' array for the chart.
        # utils.get_stats only returns today's single row.
        # We need to fetch the last 7 days of stats.
        
        # Let's check utils.get_stats again. It only returns one row.
        # The frontend code: const stats = data.daily;
        # So the API needs to return { success_rate: ..., daily: [...] }
        
        # Let's fix the API to return the expected structure.
        daily_stats = utils.get_daily_stats(current_user['id'], days=7)
        return {
            "success_rate": stats['success_rate'],
            "daily": daily_stats
        }
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve stats")

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
async def scrape_tweet_with_retry(tweet_id: str, user_id: int = None):
    """Helper function to scrape with retry logic."""
    # scraper.get_tweet_text is now synchronous, so run it in thread pool
    return await asyncio.wait_for(
        asyncio.to_thread(scraper.get_tweet_text, tweet_id, user_id), 
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
            text = await scrape_tweet_with_retry(tweet_id, user_id=current_user['id'])
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

@app.post("/api/post")
@limiter.limit("50/day")
async def post_reply(request: Request, post_req: PostRequest, current_user: dict = Depends(get_current_user)):
    """Post a reply to Twitter."""
    try:
        # 1. Validate
        if not post_req.reply_text or not post_req.reply_text.strip():
            raise HTTPException(status_code=400, detail="Reply text cannot be empty")

        msg = f"Posting reply to ID: {post_req.reply_to_id}"
        logger.info(msg)
        utils.add_log(msg, user_id=current_user['id'])
        
        # 2. Post to Twitter (using poster.py)
        # Run in thread pool to avoid blocking
        result = await asyncio.to_thread(
            poster.post_reply, 
            post_req.reply_text, 
            post_req.reply_to_id,
            user_id=current_user['id']
        )
        
        if "Error" in result or "RATE_LIMIT" in result:
            logger.error(f"Posting failed: {result}")
            utils.add_log(f"Posting failed: {result}", "ERROR", user_id=current_user['id'])
            
            if "RATE_LIMIT" in result:
                 raise HTTPException(status_code=429, detail="Twitter API rate limit exceeded")
            raise HTTPException(status_code=400, detail=result)
            
        # 3. Success - Add to history
        utils.add_log(f"Successfully posted to {post_req.reply_to_id}", "SUCCESS", user_id=current_user['id'])
        
        utils.add_history(
            tweet_id=post_req.reply_to_id, 
            reply_text=post_req.reply_text, 
            status="posted", 
            user_id=current_user['id'],
            tweet_text=post_req.tweet_text
        )
        
        # 4. Increment stats
        utils.increment_reply_count(user_id=current_user['id'])
        
        return {"status": "success", "message": result}
        
    except HTTPException:
        raise
    except Exception as e:
        err_msg = f"Error posting reply: {str(e)}"
        logger.error(err_msg)
        utils.add_log(err_msg, "ERROR", user_id=current_user['id'])
        raise HTTPException(status_code=500, detail=str(e))

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

class BatchManager:
    def __init__(self):
        self.sessions: Dict[int, BatchSession] = {}

    async def start(self, urls: List[str], tone: str, user_id: int):
        if user_id in self.sessions and self.sessions[user_id].is_processing:
             raise HTTPException(status_code=400, detail="You already have a batch process running")
        
        # Create new session
        session = BatchSession(user_id, urls, tone)
        self.sessions[user_id] = session
        
        # Start background task
        session.task = asyncio.create_task(self._process_batch(session))
        utils.add_log(f"Started batch processing for {len(urls)} URLs", user_id=user_id)

    def stop(self, user_id: int):
        if user_id in self.sessions and self.sessions[user_id].is_processing:
            self.sessions[user_id].should_stop = True
            utils.add_log("Stopping batch process...", "WARNING", user_id=user_id)

    async def _process_batch(self, session: BatchSession):
        try:
            for i in range(session.current_index, session.total_urls):
                if session.should_stop:
                    break
                
                session.current_index = i
                url = session.urls[i]
                session.current_url = url
                
                utils.add_log(f"[{i + 1}/{session.total_urls}] Processing: {url}", user_id=session.user_id)
                
                try:
                    # 1. Extract ID
                    tweet_id = utils.extract_tweet_id(url)
                    
                    # --- CHECK 1: PERSONAL REDUNDANCY ---
                    if utils.has_user_processed(session.user_id, tweet_id):
                        utils.add_log(f"⏭️ Skipping {tweet_id}: You have already processed this.", "WARNING", user_id=session.user_id)
                        continue # Skip to next URL

                    # --- CHECK 2: SHARED POOL (CACHE) ---
                    cached_text = utils.get_cached_tweet_content(tweet_id)
                    text = ""
                    
                    if cached_text:
                        utils.add_log(f"⚡ Found in Shared Pool! Skipping scrape API...", "INFO", user_id=session.user_id)
                        text = cached_text
                        await asyncio.sleep(0.5) 
                    else:
                        # Not in pool, we must scrape
                        utils.add_log(f"  > Scraping (API Call)...", "INFO", user_id=session.user_id)
                        await asyncio.sleep(2)
                        
                        try:
                            text = await scrape_tweet_with_retry(tweet_id, user_id=session.user_id)
                            
                            # Rate Limit Checks
                            if "accounts exhausted" in text or "rate limited" in text:
                                 utils.add_log(f"⚠️ Rate limit reached. Pausing for 15 minutes...", "WARNING", user_id=session.user_id)
                                 for countdown in range(900, 0, -1):
                                     if session.should_stop: break
                                     if countdown % 60 == 0 or countdown <= 10:
                                         utils.add_log(f"⏳ Resuming in {countdown // 60}m {countdown % 60}s...", "WARNING", user_id=session.user_id)
                                     await asyncio.sleep(1)
                                 
                                 if session.should_stop: break
                                     
                                 utils.add_log(f"✅ Resuming process... Retrying current URL.", "INFO", user_id=session.user_id)
                                 try:
                                     text = await scrape_tweet_with_retry(tweet_id, user_id=session.user_id)
                                 except Exception as retry_e:
                                     utils.add_log(f"  > Retry failed: {retry_e}", "ERROR", user_id=session.user_id)
                                     continue

                            # Save to Shared Pool
                            if text and "Error" not in text:
                                utils.cache_tweet_content(tweet_id, text)

                        except Exception as e:
                            # Exception Rate Limit Check
                            err_str = str(e)
                            if "accounts exhausted" in err_str or "rate limited" in err_str or "429" in err_str:
                                utils.add_log(f"⚠️ Rate limit reached. Pausing for 15 minutes...", "WARNING", user_id=session.user_id)
                                for countdown in range(900, 0, -1):
                                    if session.should_stop: break
                                    if countdown % 60 == 0 or countdown <= 10:
                                        utils.add_log(f"⏳ Resuming in {countdown // 60}m {countdown % 60}s...", "WARNING", user_id=session.user_id)
                                    await asyncio.sleep(1)
                                
                                if session.should_stop: break
                                utils.add_log(f"✅ Resuming process... Retrying current URL.", "INFO", user_id=session.user_id)
                                try:
                                    text = await scrape_tweet_with_retry(tweet_id, user_id=session.user_id)
                                    if text and "Error" not in text: utils.cache_tweet_content(tweet_id, text)
                                except Exception as retry_e:
                                    utils.add_log(f"  > Retry failed: {retry_e}", "ERROR", user_id=session.user_id)
                                    continue
                            else:
                                utils.add_log(f"  > Scrape failed: {e}", "ERROR", user_id=session.user_id)
                                continue

                    if "Error" in text:
                        utils.add_log(f"  > Scrape error: {text}", "ERROR", user_id=session.user_id)
                        continue

                    # 2. Generate
                    utils.add_log(f"  > Generating reply...", "INFO", user_id=session.user_id)
                    try:
                        reply = await asyncio.wait_for(
                            asyncio.to_thread(ai_agent.generate_reply, text, session.tone, session.user_id),
                            timeout=30.0
                        )
                    except Exception as e:
                        utils.add_log(f"  > Generation failed: {e}", "ERROR", user_id=session.user_id)
                        continue

                    if "Error" in reply:
                        utils.add_log(f"  > Generation error: {reply}", "ERROR", user_id=session.user_id)
                        continue

                    # 3. Add to Queue
                    utils.add_to_queue(tweet_id, text, reply, user_id=session.user_id)
                    utils.add_log(f"  > Added to review queue", "SUCCESS", user_id=session.user_id)
                    
                except Exception as e:
                    utils.add_log(f"Error processing {url}: {e}", "ERROR", user_id=session.user_id)
                
                # Wait a bit before next item
                await asyncio.sleep(1)

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

@app.get("/api/batch/status")
async def get_batch_status(current_user: dict = Depends(get_current_user)):
    """Get current batch status."""
    user_id = current_user['id']
    if user_id in batch_manager.sessions:
        session = batch_manager.sessions[user_id]
        return {
            "is_processing": session.is_processing,
            "current_index": session.current_index,
            "total_urls": session.total_urls,
            "current_url": session.current_url
        }
        
    return {
        "is_processing": False,
        "current_index": 0,
        "total_urls": 0,
        "current_url": ""
    }

@app.get("/api/logs")
async def get_logs(limit: int = 50, current_user: dict = Depends(get_current_user)):
    """Get recent logs."""
    return utils.get_recent_logs(limit, user_id=current_user['id'])

# Mount static files (Frontend)
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
