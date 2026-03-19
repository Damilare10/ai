import requests

headers = {
    "Authorization": "Bearer sk_test_1f4fd9a1c524be7891bd72037ee43c1a84da0891",
    "Content-Type": "application/json"
}
data = {
    "email": "mumunihabib10@gmail.com",
    "amount": "400000"
}

try:
    response = requests.post('https://api.paystack.co/transaction/initialize', headers=headers, json=data)
    print("STATUS:", response.status_code)
    print("BODY:", response.text)
except Exception as e:
    print("Exception:", e)
