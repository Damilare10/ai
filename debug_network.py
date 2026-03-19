import httpx
import asyncio

async def test():
    url = "https://sandbox-api-d.squadco.com/transaction/verify/test"
    print(f"Testing connectivity to {url}...")
    try:
        async with httpx.AsyncClient() as client:
            # We don't care about the response code, just if we can reach it
            response = await client.get(url, timeout=10.0)
            print(f"Connected! Status: {response.status_code}")
    except Exception as e:
        print(f"Connection failed: {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(test())
