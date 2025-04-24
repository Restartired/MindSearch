import ast
from difflib import get_close_matches
import re

class CodeValidationAgent:
    def __init__(self, nodes_added, is_first_generation):
        self.errors = []
        self.nodes_added = nodes_added  # 从外部传入已添加的节点
        self.is_first_generation = is_first_generation  # 从外部传入是否是第一次生成代码
        self.graph_initialized = False  # 是否初始化了 WebSearchGraph
        self.root_node_added = False  # 是否添加了根节点

    def static_analysis(self, code: str):
        """
        静态分析代码，检查是否符合预期。
        """
        try:
            tree = ast.parse(code)

            for node in ast.walk(tree):
                # 检查是否初始化了 WebSearchGraph
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                    if isinstance(node.value.func, ast.Name) and node.value.func.id == "WebSearchGraph":
                        self.graph_initialized = True

                # 检查函数调用
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Attribute):  # 确保 func 是 Attribute 类型
                        if node.func.attr == "add_root_node":
                            if not self.graph_initialized:
                                self.errors.append("Error: WebSearchGraph must be initialized before calling add_root_node.")
                            else:
                                root_node_name = self._get_arg_value(node, "node_name")
                                if root_node_name:
                                    self.nodes_added.add(root_node_name)
                                    self.root_node_added = True

                        elif node.func.attr == "add_node":
                            node_name = self._get_arg_value(node, "node_name")
                            if node_name:
                                self.nodes_added.add(node_name)

                        elif node.func.attr == "add_edge":
                            start_node = self._get_arg_value(node, "start_node")
                            end_node = self._get_arg_value(node, "end_node")
                            if start_node not in self.nodes_added or end_node not in self.nodes_added:
                                self.errors.append(
                                    f"Error: Edge references undefined nodes '{start_node}' or '{end_node}'."
                                )

                        elif node.func.attr == "node":
                            node_name = self._get_arg_value(node, "node_name")
                            if node_name not in self.nodes_added:
                                self.errors.append(f"Error: Node '{node_name}' is not defined.")

            # 检查是否满足第一次生成代码的要求
            if self.is_first_generation:
                if not self.graph_initialized:
                    self.errors.append("Error: WebSearchGraph is not initialized.")
                if not self.root_node_added:
                    self.errors.append("Error: Root node must be added in the first generation.")

            return len(self.errors) == 0
        except Exception as e:
            self.errors.append(f"Static analysis failed: {str(e)}")
            return False

    def _get_arg_value(self, node, arg_name: str):
        """
        获取函数调用中指定参数的值。
        """
        for keyword in node.keywords:
            if keyword.arg == arg_name:
                if isinstance(keyword.value, ast.Constant):
                    return keyword.value.value
        return None

    def validate_code(self, code: str):
        """
        校验代码，返回校验结果和错误信息。
        """
        self.errors = []
        static_result = self.static_analysis(code)
        return static_result, self.errors

    # def validate_code(self, code: str):
    #     self.errors = []

    #     # 示例验证逻辑
    #     if "WebSearchGraph()" not in code:
    #         self.errors.append("Error: WebSearchGraph must be initialized before calling add_root_node.")
    #     if "add_root_node" not in code:
    #         self.errors.append("Error: Root node must be added in the first generation.")
    #     if "add_node" not in code:
    #         self.errors.append("Error: At least one node must be added before calling add_edge or node.")

    #     # 检查拼写错误
    #     if "graph.node(" in code:
    #         node_name = re.search(r"graph\.node\(\"(.*?)\"\)", code)
    #         if node_name:
    #             node_name = node_name.group(1)
    #             if node_name not in self.nodes_added:
    #                 closest_matches = get_close_matches(node_name, self.nodes_added, n=1, cutoff=0.8)
    #                 if closest_matches:
    #                     corrected_name = closest_matches[0]
    #                     self.errors.append(f"Error: Node '{node_name}' is not defined. Did you mean '{corrected_name}'?")
    #                 else:
    #                     self.errors.append(f"Error: Node '{node_name}' is not defined.")

    #     return len(self.errors) == 0, self.errors