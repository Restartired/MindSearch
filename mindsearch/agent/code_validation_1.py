import re
from difflib import get_close_matches


class CodeValidationAgent:
    def __init__(self, is_first_generation: bool, nodes_added: set):
        """
        初始化 CodeValidationAgent
        :param is_first_generation: 是否是 LLMs 第一次生成代码
        :param nodes_added: 已添加的节点名称集合
        """
        self.is_first_generation = is_first_generation
        self.nodes_added = nodes_added
        self.errors = []

    def validate_and_fix_code(self, command: str) -> str:
        """
        校验并修复生成的代码
        :param command: LLMs 生成的代码
        :return: 修复后的代码
        """
        # 提取代码中的操作
        graph_initialized = "graph = WebSearchGraph()" in command
        root_node_added = re.search(r'graph\.add_root_node\(\s*node_content\s*=\s*".*?",\s*node_name\s*=\s*"(.*?)"\)', command)
        add_node_matches = re.findall(r'graph\.add_node\(\s*node_name\s*=\s*"(.*?)"', command)
        add_edge_matches = re.findall(r'graph\.add_edge\(\s*start_node\s*=\s*"(.*?)",\s*end_node\s*=\s*"(.*?)"\)', command)
        node_matches = re.findall(r'graph\.node\(\s*"(.*?)"\)', command)

        # 如果是第一次生成代码
        if self.is_first_generation:
            # 检查是否初始化了 graph
            if not graph_initialized:
                self.errors.append("Error: WebSearchGraph must be initialized before any operations.")
                command = f"graph = WebSearchGraph()\n{command}"

            # 检查是否添加了根节点
            if not root_node_added:
                self.errors.append("Error: Root node must be added in the first generation.")
            else:
                root_node_name = root_node_added.group(1)
                self.nodes_added.add(root_node_name)

            # 检查是否有添加节点的操作
            for node_name in add_node_matches:
                self.nodes_added.add(node_name)

        # 如果不是第一次生成代码
        else:
            # 检查 add_edge 和 node 的节点名称是否一致
            for start_node, end_node in add_edge_matches:
                if start_node not in self.nodes_added:
                    corrected_name = self._get_closest_match(start_node)
                    if corrected_name:
                        self.errors.append(f"Error: Node '{start_node}' not found. Did you mean '{corrected_name}'?")
                        command = command.replace(f'"{start_node}"', f'"{corrected_name}"')
                    else:
                        self.errors.append(f"Error: Node '{start_node}' is not defined.")
                if end_node not in self.nodes_added:
                    corrected_name = self._get_closest_match(end_node)
                    if corrected_name:
                        self.errors.append(f"Error: Node '{end_node}' not found. Did you mean '{corrected_name}'?")
                        command = command.replace(f'"{end_node}"', f'"{corrected_name}"')
                    else:
                        self.errors.append(f"Error: Node '{end_node}' is not defined.")

            for node_name in node_matches:
                if node_name not in self.nodes_added:
                    corrected_name = self._get_closest_match(node_name)
                    if corrected_name:
                        self.errors.append(f"Error: Node '{node_name}' not found. Did you mean '{corrected_name}'?")
                        command = command.replace(f'"{node_name}"', f'"{corrected_name}"')
                    else:
                        self.errors.append(f"Error: Node '{node_name}' is not defined.")

        # 更新第一次生成代码的标记
        self.is_first_generation = False
        return command

    def _get_closest_match(self, node_name: str) -> str:
        """
        获取与节点名称最接近的匹配
        :param node_name: 节点名称
        :return: 最接近的匹配名称
        """
        closest_matches = get_close_matches(node_name, self.nodes_added, n=1, cutoff=0.8)
        return closest_matches[0] if closest_matches else None