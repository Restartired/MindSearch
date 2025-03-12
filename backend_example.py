import json

import requests

# Define the backend URL
url = "http://localhost:8002/solve"
headers = {"Content-Type": "application/json"}


# Function to send a query to the backend and get the response
def get_response(query):
    # Prepare the input data
    data = {"inputs": query}

    # Send the request to the backend
    response = requests.post(url, headers=headers, data=json.dumps(data), timeout=20, stream=True)

    # Process the streaming response
    for chunk in response.iter_lines(chunk_size=8192, decode_unicode=False, delimiter=b"\n"):
        if chunk:
            decoded = chunk.decode("utf-8")
            if decoded == "\r":
                continue
            if decoded[:6] == "data: ":
                decoded = decoded[6:]
            elif decoded.startswith(": ping - "):
                continue
            response_data = json.loads(decoded)
            #agent_return = response_data["response"]
            #node_name = response_data["current_node"]
            #print(f"Node: {node_name}, Response: {agent_return['response']}")

            print("Full response data:", response_data)  # 打印完整的响应数据

            #print('current_node:',response_data['current_node'])

            # 检查是否包含完整的响应
            if "response" in response_data and "current_node" in response_data:
                agent_return = response_data["response"]
                node_name = response_data["current_node"]
                if "response" in agent_return:
                    print(f"Node: {node_name}, Response: {agent_return['response']}")
                else:
                    print("Warning: 'response' key not found in agent_return.")
            else:
                print("Warning: Incomplete response data received.")


# Example usage
if __name__ == "__main__":
    #query = "What is the weather like today in New York?"
    query = '王者荣耀这个赛季什么射手最强？'
    get_response(query)
