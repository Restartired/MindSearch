import json
import tempfile
import requests
from pyvis.network import Network
from lagent.schema import AgentStatusCode

from datasets import load_dataset
# https://pypi.org/project/datasets/
# https://huggingface.co/datasets/chiayewken/bamboogle

# 加载数据集
ds = load_dataset("chiayewken/bamboogle")
#ds = load_from_disk('./bamboogle')

# 访问 'test' 数据集
test_dataset = ds['test']

# 提取 'Question' 和 'Answer' 特征
# questions = test_dataset['Question'][2:3]
questions = test_dataset['Question']
# answers = test_dataset['Answer']

def create_network_graph(nodes, adjacency_list):
    net = Network(height="500px", width="60%", bgcolor="white", font_color="black")
    for node_id, node_content in nodes.items():
        net.add_node(node_id, label=node_id, title=node_content, color="#FF5733", size=25)
    for node_id, neighbors in adjacency_list.items():
        for neighbor in neighbors:
            if neighbor["name"] in nodes:
                net.add_edge(node_id, neighbor["name"])
    net.show_buttons(filter_=["physics"])
    return net

def draw_graph(net):
    path = tempfile.mktemp(suffix=".html")
    net.save_graph(path)
    return path

def streaming(raw_response):
    for chunk in raw_response.iter_lines(chunk_size=8192, decode_unicode=False, delimiter=b"\n"):
        if chunk:
            decoded = chunk.decode("utf-8")
            if decoded == "\r":
                continue
            if decoded[:6] == "data: ":
                decoded = decoded[6:]
            elif decoded.startswith(": ping - "):
                continue
            try:
                response = json.loads(decoded)
                # yield (
                #     response["current_node"],
                #     (
                #         response["response"]["formatted"]["node"][response["current_node"]]["response"]
                #         if response["current_node"]
                #         else response["response"]
                #     ),
                #     response["response"]["formatted"]["adjacency_list"],
                # )

                # 安全获取 response，默认为空字典
                response_data = response.get("response", {})
                formatted_data = response_data.get("formatted", {})
                current_node = response.get("current_node", None)
                adjacency_list = formatted_data.get("adjacency_list", {})
                node_response = (
                    formatted_data.get("node", {}).get(current_node, {}).get("response")
                    if current_node
                    else response_data
                )
                yield current_node, node_response, adjacency_list

            except json.JSONDecodeError as e:
                print(f"Error decoding JSON: {e}")
                print(f"Invalid JSON data: {decoded}")

def process_query(query, url="http://localhost:8002/solve"):
    headers = {"Content-Type": "application/json"}
    data = {"inputs": query}
    raw_response = requests.post(url, headers=headers, data=json.dumps(data), timeout=20, stream=True)

    _nodes, _node_cnt = {}, 0
    graph_html = None
    session_info_temp = ""
    responses = []

    for resp in streaming(raw_response):
        node_name, response, adjacency_list = resp
        for name in set(adjacency_list) | {
            val["name"] for vals in adjacency_list.values() for val in vals
        }:
            if name not in _nodes:
                _nodes[name] = query if name == "root" else name
            elif response.get("stream_state") == 0:
                _nodes[node_name or "response"] = response.get("formatted", {}).get("thought")

        # # 添加调试信息
        # print(f"Current nodes: {_nodes}")

        if len(_nodes) != _node_cnt or response.get("stream_state") == 0:
            net = create_network_graph(_nodes, adjacency_list)
            graph_html_path = draw_graph(net)
            with open(graph_html_path, encoding="utf-8") as f:
                graph_html = f.read()
            _node_cnt = len(_nodes)

        if not node_name:
            if response.get("stream_state") in [AgentStatusCode.STREAM_ING, AgentStatusCode.CODING, AgentStatusCode.CODE_END]:
                content = response.get("formatted", {}).get("thought", "")
                if response.get("formatted", {}).get("tool_type"):
                    action = response.get("formatted", {}).get("action")
                    if isinstance(action, dict):
                        action = json.dumps(action, ensure_ascii=False, indent=4)
                    content += "\n" + action
                session_info_temp = content.replace("<|action_start|><|interpreter|>\n", "\n")
            elif response.get("stream_state") == AgentStatusCode.CODE_RETURN:
                session_info_temp += "\n" + response.get("content", "")
            responses.append(session_info_temp)
            session_info_temp = ""
        else:
            responses.append(session_info_temp if not session_info_temp else responses[-1])

    return responses, graph_html, _nodes, adjacency_list
        

def main():
    # # 示例查询
    # query = "What is the length of the second deepest river in the world?"
    results = []

    # responses, graph_html, nodes, adjacency_list = process_query(query)

    # results.append({
    #     "query": query,
    #     "responses": nodes['response'] if ('response' in nodes) else nodes
    # })


    # with open('/root/repo/MindSearch/Datasets/empty_responses.json', "r", encoding="utf-8") as f:
    #     questions = json.load(f)



    for idx, query in enumerate(questions):
        print(f"Processing query {idx + 1}/{len(questions)}: {query}")

        responses, graph_html, nodes, adjacency_list = process_query(query)
        # results.append({
        #     "query": query,
        #     "responses": responses,
        #     "graph_html": graph_html,
        #     "nodes": nodes,
        #     "adjacency_list": adjacency_list
        # })

        results.append({
            "query": query,
            "responses": nodes['response'] if ('response' in nodes) else nodes
        })

    
    # 保存结果到文件
    output_file = "mindsearch_results.json"
    with open(output_file, "w", encoding="utf-8") as f:
        # f.write("\n")  # 确保从新的一行开始
        json.dump(results, f, ensure_ascii=False, indent=4)
    
    print(f"Batch processing complete. Results saved to {output_file}")

if __name__ == "__main__":
    main()