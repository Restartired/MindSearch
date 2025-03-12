import requests
import json

# Define the backend URL
url = "http://localhost:8002/solve"
headers = {"Content-Type": "application/json"}

# Function to send a query to the backend and get the response
def get_response(query):
    data = {"inputs": query}
    response = requests.post(url, headers=headers, data=json.dumps(data), timeout=60, stream=True)

    for chunk in response.iter_lines(chunk_size=8192, decode_unicode=False, delimiter=b"\n"):
        if chunk:
            decoded = chunk.decode("utf-8")
            if decoded.strip() == "" or decoded.startswith(": ping - "):
                continue  # 跳过空行或心跳检测行
            if decoded[:6] == "data: ":
                decoded = decoded[6:]
            try:
                response_data = json.loads(decoded)
                print(f"Raw JSON response: {response_data}")  # 打印原始 JSON 数据
                if response_data["response"]["content"] is not None:
                    agent_return = response_data["response"]
                    print(f"Response: {agent_return['content']}")
                else:
                    print("No content in response.")
            except json.JSONDecodeError as e:
                print(f"Error decoding JSON: {e}")
                print(f"Invalid JSON data: {decoded}")

# Example usage
if __name__ == "__main__":
    query = "Who was president of the United States in the year that Citibank was founded?"
    get_response(query)
