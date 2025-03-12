import requests
import json

url = "http://localhost:8002/solve"
headers = {"Content-Type": "application/json"}
data = {"inputs": "Who was president of the United States in the year that Citibank was founded?"}

response = requests.post(url, headers=headers, data=json.dumps(data))
print(response.status_code)
print(response.text)

try:
    print(response.json())
except json.JSONDecodeError as e:
    print(f"Error decoding JSON: {e}")
