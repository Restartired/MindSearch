import json
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
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

# 启动 Chrome 浏览器
driver = webdriver.Chrome()

# 打开 Streamlit 应用
driver.get("http://localhost:8501")  # 假设 Streamlit 应用运行在 8501 端口

# 批量处理查询
results = []
for idx, query in enumerate(questions):
    print(f"Processing query {idx + 1}/{len(questions)}: {query}")
    
    # 找到输入框并输入查询
    input_box = driver.find_element(By.CSS_SELECTOR, "div[data-testid='stChatInput'] input")
    input_box.clear()
    input_box.send_keys(query)
    
    # 按下回车键发送查询
    input_box.send_keys(Keys.RETURN)
    
    # 等待响应完成（可以根据实际情况调整等待时间）
    time.sleep(5)  # 等待 5 秒，确保响应完成
    
    # 等待响应完成
    try:
        # 等待直到响应内容出现
        response_element = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-testid='stChatMessage'] div[data-testid='stMarkdown']"))
        )
        response = response_element.text
        results.append({"query": query, "response": response})
    except Exception as e:
        print(f"Error processing query '{query}': {e}")
        results.append({"query": query, "response": None, "error": str(e)})
    
    
    # 清理历史记录（可选）
    # driver.find_element(By.CSS_SELECTOR, "button[data-testid='clear_history_button']").click()
    # time.sleep(1)

# 关闭浏览器
driver.quit()

# 保存结果到文件
output_file = "mindsearch_results_2.json"
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=4)

print(f"Batch processing complete. Results saved to {output_file}")