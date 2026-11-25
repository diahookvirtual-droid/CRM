import requests

API_URL = "https://script.google.com/macros/s/AKfycbwdFoh9Fo5N9UGxL98IqPIETuqQ4eUa6i8kVZGgyN8w6S0d_2jsjDrBJHgkRrqlQzck/exec"

response = requests.post(
    API_URL,
    json={
        "action": "add",
        "lead": {
            "name": "Test Lead",
            "email": "test@example.com"
        }
    },
    timeout=30,
    allow_redirects=True
)

print(response.status_code)
print(response.text)