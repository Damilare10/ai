import asyncio
import os
import json
import shutil
from playwright.async_api import async_playwright

async def generate_auth():
    print("🚀 Launching browser for manual login...")
    print("👉 A browser window will open. Please log in to X/Twitter manually.")
    print("⚠️ DO NOT close the browser window yourself.")
    
    # Create a temp dir for the profile (persistent context need a dir)
    user_data_dir = os.path.join(os.getcwd(), "temp_auth_profile")
    os.makedirs(user_data_dir, exist_ok=True)
    
    browser_context = None
    
    try:
        async with async_playwright() as p:
            # Use persistent context which stores cookies/local storage reliably
            # and is less likely to be flagged if we don't pass 'headless=False' 
            # (wait, we need headless=False to see it).
            browser_context = await p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                # viewport=None  # Use full window
            )
            
            page = browser_context.pages[0] if browser_context.pages else await browser_context.new_page()
            
            print("🌐 Navigating to login page...")
            try:
                await page.goto("https://x.com/login", timeout=60000)
            except Exception as e:
                print(f"⚠️ Navigation warning: {e}")
                
            print("\n" + "="*50)
            print("🛑 ACTION REQUIRED:")
            print("1. Log in to X.com in the browser window.")
            print("2. When you can see your home timeline...")
            print("👉 Come back here and press ENTER.")
            print("="*50)
            
            # Wait for user input in terminal
            await asyncio.to_thread(input, ">>> Press ENTER when logged in: ")
            
            print("\n📸 Capturing session state...")
            
            # Save to temp file first
            temp_file = "temp_auth.json"
            await browser_context.storage_state(path=temp_file)
            
            # Close browser
            await browser_context.close()
            browser_context = None # Prevent double close in finally
            
            # Validate and Move
            if os.path.exists(temp_file):
                with open(temp_file, 'r') as f:
                    data = json.load(f)
                
                # Extract User ID
                user_id = None
                for cookie in data.get('cookies', []):
                    if cookie['name'] == 'twid':
                        val = cookie['value']
                        # Handle encoded value u%3D... or u=...
                        if val.startswith('u='):
                            user_id = val.split('=')[1]
                        elif val.startswith('u%3D'):
                            user_id = val.split('%3D')[1]
                        break
                
                if user_id:
                    print(f"✅ Extracted User ID: {user_id}")
                    base_dir = "user_data"
                    user_dir = os.path.join(base_dir, user_id)
                    os.makedirs(user_dir, exist_ok=True)
                    
                    # Determine filename
                    existing = [f for f in os.listdir(user_dir) if f.startswith('auth_') and f.endswith('.json')]
                    idx = len(existing) + 1
                    filename = f"auth_{idx}.json"
                    filepath = os.path.join(user_dir, filename)
                    
                    # Move
                    shutil.move(temp_file, filepath)
                    print(f"💾 Auth file saved to: {filepath}")
                else:
                    print("⚠️ Could not find 'twid' cookie with User ID.")
                    print(f"Saved session to {temp_file} in current directory.")
            else:
                print("❌ Failed to save session file.")

    except Exception as e:
        print(f"\n❌ Error: {e}")
    finally:
        if browser_context:
            await browser_context.close()
        
        # Clean up temp profile? 
        # Optional: keeping it might actually help if user runs script again (cookies preserved?)
        # But for 'fresh' auth generation, maybe better to start clean.
        # I'll leave it for now.

if __name__ == "__main__":
    asyncio.run(generate_auth())
