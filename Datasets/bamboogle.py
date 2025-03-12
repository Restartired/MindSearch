import requests
import json
from datasets import load_dataset

# 加载数据集
ds = load_dataset("chiayewken/bamboogle")
#ds = load_from_disk('./bamboogle')

# 访问 'test' 数据集
test_dataset = ds['test']

# 提取 'Question' 和 'Answer' 特征
questions = test_dataset['Question'][:1]
#questions = test_dataset['Question']
answers = test_dataset['Answer']

# 定义后端 URL 和请求头
url = "http://localhost:8002/solve"
headers = {"Content-Type": "application/json"}

# 函数：发送查询并获取响应
def get_response(query):
    data = {"inputs": query}
    response = requests.post(url, headers=headers, data=json.dumps(data), timeout=20)
    #return response.json()

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
                if response_data.get("response", {}).get("content") is not None:
                    agent_return = response_data["response"]
                    print(f"Response: {agent_return['content']}")
                    return agent_return['content']
                else:
                    print("No content in response.")
            except json.JSONDecodeError as e:
                print(f"Error decoding JSON: {e}")
                print(f"Invalid JSON data: {decoded}")

    return response_data

# 批量处理查询并保存结果
results = []
for idx, query in enumerate(questions):
    print(f"Processing query {idx + 1}/{len(questions)}: {query}")
    try:
        response = get_response(query)
        results.append({"query": query, "response": response})
    except Exception as e:
        print(f"Error processing query '{query}': {e}")
        results.append({"query": query, "response": None, "error": str(e)})

# 保存结果到文件
output_file = "mindsearch_results_1.json"
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=4)

print(f"Batch processing complete. Results saved to {output_file}")
