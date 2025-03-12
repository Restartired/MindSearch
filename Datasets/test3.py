from datasets import load_dataset
import json

# 加载数据集
dataset = load_dataset("chiayewken/bamboogle")

# 提取问题和答案
questions = dataset['test']['Question']
answers = dataset['test']['Answer']

# 将问题和答案组合为一个列表
qa_pairs = [{"question": q, "answer": a} for q, a in zip(questions, answers)]

# 保存为 JSON 文件
output_file = "qa_pairs.json"
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(qa_pairs, f, ensure_ascii=False, indent=4)

print(f"Saved {len(qa_pairs)} QA pairs to {output_file}")
