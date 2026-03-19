import requests

# Set the base URL for the API
BASE_URL = "http://localhost:8000"

def test_signup_and_payment():
    # 1. Sign up a new user (the referrer)
    print("Signing up user1...")
    signup_data1 = {"username": "user1_referrer", "password": "password123"}
    response1 = requests.post(f"{BASE_URL}/api/auth/signup", json=signup_data1)
    print(f"User1 Signup Response: {response1.status_code}")
    
    if response1.status_code != 200:
        print(response1.text)
        return
        
    user1_token = response1.json().get("access_token")
    
    # Get user1's referral code
    headers1 = {"Authorization": f"Bearer {user1_token}"}
    me_res1 = requests.get(f"{BASE_URL}/api/auth/me", headers=headers1)
    referral_code = me_res1.json().get("referral_code")
    print(f"User1 Referral Code: {referral_code}")
    
    # 2. Sign up a second user (the referred)
    print("\nSigning up user2 with referral code...")
    signup_data2 = {"username": "user2_referred", "password": "password123", "referral_code": referral_code}
    response2 = requests.post(f"{BASE_URL}/api/auth/signup", json=signup_data2)
    print(f"User2 Signup Response: {response2.status_code}")

    if response2.status_code != 200:
         print(response2.text)
         return
         
    user2_token = response2.json().get("access_token")

    # 3. Check user1's referrals
    print("\nChecking user1's referrals...")
    referrals_res = requests.get(f"{BASE_URL}/api/user/referrals", headers=headers1)
    print(f"Referrals Response: {referrals_res.status_code}")
    if referrals_res.status_code == 200:
        print(f"Referrals Data: {referrals_res.json()}")
        
    # 4. Test Payment verify Endpoint (Simulate success)
    print("\nTesting payment verification...")
    # This will use the mock verification since we pass 'mock_success'
    payment_data = {"reference": "mock_success:test_ref_123"}
    payment_res = requests.post(f"{BASE_URL}/api/payment/verify", json=payment_data, headers={"Authorization": f"Bearer {user1_token}"})
    print(f"Payment Verify Response: {payment_res.status_code}")
    if payment_res.status_code == 200:
        print(f"Payment Verify Data: {payment_res.json()}")
        
    # Check user1 credits
    me_res1_after = requests.get(f"{BASE_URL}/api/auth/me", headers=headers1)
    print(f"User1 Credits after payment: {me_res1_after.json().get('credits')}")

if __name__ == "__main__":
    test_signup_and_payment()
