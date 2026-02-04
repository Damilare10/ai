# Fixing the Render Build Error (imghdr)

The error you are seeing (`ModuleNotFoundError: No module named 'imghdr'`) happens because **Render is still using Python 3.13**, but your code relies on libraries that need an older, stable version of Python (3.11).

My previous attempt to fix this with `runtime.txt` was ignored by Render's cache. We need to force it.

### Solution: Set Environment Variable

1.  Go to your **Render Dashboard**.
2.  Click on your **`aireply`** Web Service.
3.  Click **"Environment"** in the left menu.
4.  Click **"Add Environment Variable"**.
5.  Key: `PYTHON_VERSION`
6.  Value: `3.11.9`
7.  Click **"Save Changes"**.

### Trigger a New Deployment

1.  Click **"Manual Deploy"** (top right).
2.  Select **"Clear build cache & deploy"**.

This will force Render to reinstall Python 3.11.9, which has `imghdr` built-in, and your app will start working immediately.
