import asyncio
import queue
import random
import re
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Thread
from typing import Dict, List
from difflib import get_close_matches

from lagent.actions import BaseAction
from lagent.schema import AgentMessage, AgentStatusCode

from .streaming import AsyncStreamingAgentForInternLM, StreamingAgentForInternLM

# from .code_validation import CodeValidationAgent
# from .mindsearch_prompt import REGENERATE_CODE_PROMPT_EN, REGENERATE_CODE_PROMPT_CN

# from .code_validation_1 import CodeValidationAgent

class SearcherAgent(StreamingAgentForInternLM):
    def __init__(
        self,
        user_input_template: str = "{question}",
        user_context_template: str = None,
        **kwargs,
    ):
        self.user_input_template = user_input_template
        self.user_context_template = user_context_template
        super().__init__(**kwargs)

    def forward(
        self,
        question: str,
        topic: str,
        history: List[dict] = None,
        session_id=0,
        **kwargs,
    ):
        message = [self.user_input_template.format(question=question, topic=topic)]
        if history and self.user_context_template:
            message = [self.user_context_template.format_map(item) for item in history] + message
        message = "\n".join(message)
        return super().forward(message, session_id=session_id, **kwargs)


class AsyncSearcherAgent(AsyncStreamingAgentForInternLM):
    def __init__(
        self,
        user_input_template: str = "{question}",
        user_context_template: str = None,
        **kwargs,
    ):
        self.user_input_template = user_input_template
        self.user_context_template = user_context_template
        super().__init__(**kwargs)

    async def forward(
        self,
        question: str,
        topic: str,
        history: List[dict] = None,
        session_id=0,
        **kwargs,
    ):
        message = [self.user_input_template.format(question=question, topic=topic)]
        if history and self.user_context_template:
            message = [self.user_context_template.format_map(item) for item in history] + message
        message = "\n".join(message)
        async for message in super().forward(message, session_id=session_id, **kwargs):
            yield message


class WebSearchGraph:
    is_async = False
    SEARCHER_CONFIG = {}
    _SEARCHER_LOOP = []
    _SEARCHER_THREAD = []

    def __init__(self):
        self.nodes: Dict[str, Dict[str, str]] = {}
        self.adjacency_list: Dict[str, List[dict]] = defaultdict(list)
        self.future_to_query = dict()
        self.searcher_resp_queue = queue.Queue()
        self.executor = ThreadPoolExecutor(max_workers=10)
        self.n_active_tasks = 0

    def add_root_node(
        self,
        node_content: str,
        node_name: str = "root",
    ):
        """添加起始节点

        Args:
            node_content (str): 节点内容
            node_name (str, optional): 节点名称. Defaults to 'root'.

        """
        self.nodes[node_name] = dict(content=node_content, type="root")
        self.adjacency_list[node_name] = []

    def add_node(
        self,
        node_name: str,
        node_content: str,
    ):
        """添加搜索子问题节点

        Args:
            node_name (str): 节点名称
            node_content (str): 子问题内容

        Returns:
            str: 返回搜索结果
        """
        self.nodes[node_name] = dict(content=node_content, type="searcher")
        self.adjacency_list[node_name] = []

        parent_nodes = []
        for start_node, adj in self.adjacency_list.items():
            for neighbor in adj:
                if (
                    node_name == neighbor
                    and start_node in self.nodes
                    and "response" in self.nodes[start_node]
                ):
                    parent_nodes.append(self.nodes[start_node])
        parent_response = [
            dict(question=node["content"], answer=node["response"]) for node in parent_nodes
        ]

        if self.is_async:

            async def _async_search_node_stream():
                cfg = {
                    **self.SEARCHER_CONFIG,
                    "plugins": deepcopy(self.SEARCHER_CONFIG.get("plugins")),
                }
                agent, session_id = AsyncSearcherAgent(**cfg), random.randint(0, 999999)
                searcher_message = AgentMessage(sender="SearcherAgent", content="")
                try:
                    async for searcher_message in agent(
                        question=node_content,
                        topic=self.nodes["root"]["content"],
                        history=parent_response,
                        session_id=session_id,
                    ):
                        self.nodes[node_name]["response"] = searcher_message.model_dump()
                        self.nodes[node_name]["memory"] = agent.state_dict(session_id=session_id)
                        self.nodes[node_name]["session_id"] = session_id
                        self.searcher_resp_queue.put((node_name, self.nodes[node_name], []))
                    self.searcher_resp_queue.put((None, None, None))
                except Exception as exc:
                    self.searcher_resp_queue.put((exc, None, None))

            self.future_to_query[
                asyncio.run_coroutine_threadsafe(
                    _async_search_node_stream(), random.choice(self._SEARCHER_LOOP)
                )
            ] = f"{node_name}-{node_content}"
            # self.future_to_query[
            #     self.executor.submit(asyncio.run, _async_search_node_stream())
            # ] = f"{node_name}-{node_content}"
        else:

            def _search_node_stream():
                cfg = {
                    **self.SEARCHER_CONFIG,
                    "plugins": deepcopy(self.SEARCHER_CONFIG.get("plugins")),
                }
                agent, session_id = SearcherAgent(**cfg), random.randint(0, 999999)
                searcher_message = AgentMessage(sender="SearcherAgent", content="")
                try:
                    for searcher_message in agent(
                        question=node_content,
                        topic=self.nodes["root"]["content"],
                        history=parent_response,
                        session_id=session_id,
                    ):
                        self.nodes[node_name]["response"] = searcher_message.model_dump()
                        self.nodes[node_name]["memory"] = agent.state_dict(session_id=session_id)
                        self.nodes[node_name]["session_id"] = session_id
                        self.searcher_resp_queue.put((node_name, self.nodes[node_name], []))
                    self.searcher_resp_queue.put((None, None, None))
                except Exception as exc:
                    self.searcher_resp_queue.put((exc, None, None))

            self.future_to_query[
                self.executor.submit(_search_node_stream)
            ] = f"{node_name}-{node_content}"

        self.n_active_tasks += 1

    def add_response_node(self, node_name="response"):
        """添加回复节点

        Args:
            thought (str): 思考过程
            node_name (str, optional): 节点名称. Defaults to 'response'.

        """
        self.nodes[node_name] = dict(type="end")
        self.searcher_resp_queue.put((node_name, self.nodes[node_name], []))

    def add_edge(self, start_node: str, end_node: str):
        """添加边

        Args:
            start_node (str): 起始节点名称
            end_node (str): 结束节点名称
        """
        self.adjacency_list[start_node].append(dict(id=str(uuid.uuid4()), name=end_node, state=2))
        self.searcher_resp_queue.put(
            (start_node, self.nodes[start_node], self.adjacency_list[start_node])
        )

    def reset(self):
        self.nodes = {}
        self.adjacency_list = defaultdict(list)

    def node(self, node_name: str) -> str:
        # if node_name not in self.nodes:
        #     raise KeyError(f"Node '{node_name}' does not exist in the graph. Available nodes: {list(self.nodes.keys())}")
        
        if node_name not in self.nodes:
            # 尝试通过模糊匹配找到最接近的节点名称
            closest_matches = get_close_matches(node_name, self.nodes.keys(), n=1, cutoff=0.8)
            if closest_matches:
                corrected_name = closest_matches[0]
                print(f"Node '{node_name}' not found. Did you mean '{corrected_name}'?")
                # node_name = corrected_name
                print(f"return node('{corrected_name}')")
                return self.nodes[corrected_name].copy()
            else:
                raise KeyError(
                    f"Node '{node_name}' does not exist in the graph. "
                    f"Available nodes: {list(self.nodes.keys())}"
                )

        return self.nodes[node_name].copy()

    @classmethod
    def start_loop(cls, n: int = 32):
        if not cls.is_async:
            raise RuntimeError("Event loop cannot be launched as `is_async` is disabled")

        assert len(cls._SEARCHER_LOOP) == len(cls._SEARCHER_THREAD)
        for i, (loop, thread) in enumerate(
            zip(cls._SEARCHER_LOOP.copy(), cls._SEARCHER_THREAD.copy())
        ):
            if not (loop.is_running() and thread.is_alive()):
                cls._SEARCHER_LOOP.pop(i)
                cls._SEARCHER_THREAD.pop(i)

        while len(cls._SEARCHER_THREAD) < n:

            def _start_loop():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                cls._SEARCHER_LOOP.append(loop)
                loop.run_forever()

            thread = Thread(target=_start_loop, daemon=True)
            thread.start()
            cls._SEARCHER_THREAD.append(thread)


class ExecutionAction(BaseAction):
    """Tool used by MindSearch planner to execute graph node query."""
    # def __init__(self, agent):
    #     self.agent = agent  # 保存 MindSearchAgent 的引用

    # def __init__(self, is_first_generation: bool, nodes_added: set):
    #     self.validator = CodeValidationAgent(is_first_generation, nodes_added)

    # def run_sync(self, command, local_dict, global_dict, is_first_generation=False, nodes_added=None, session_id=0, stream_graph=False):
    def run_sync(self, command, local_dict, global_dict, stream_graph=False):
        """
        串行版本的 run 方法。
        """
        print(f"Executing command synchronously: {command}")  # 调试信息

        def extract_code(text: str) -> str:
            """提取代码块"""
            text = re.sub(r"from ([\w.]+) import WebSearchGraph", "", text)
            triple_match = re.search(r"```[^\n]*\n(.+?)```", text, re.DOTALL)
            single_match = re.search(r"`([^`]*)`", text, re.DOTALL)
            if triple_match:
                return triple_match.group(1)
            elif single_match:
                return single_match.group(1)
            return text

        command = extract_code(command)

        # # 初始化 CodeValidationAgent
        # validator = CodeValidationAgent(nodes_added, is_first_generation)

        # # 循环校验和执行代码
        # max_attempts = 1  # 限制最大尝试次数
        # attempts = 0

        # while attempts < max_attempts:
        #     attempts += 1

        #     # 校验代码
        #     is_valid, errors = validator.validate_code(command)
        #     if not is_valid:
        #         # 打印错误信息并提醒 LLM
        #         print(f"Code validation failed: {errors}")
        #         print("LLM: Please regenerate the code based on the above errors.")

        #         # 让当前 LLM 实例重新生成代码
        #         # command = self.regenerate_code(errors, command, global_dict["agent"], session_id, global_dict.get("lang", "en"))
        #         continue  # 重新校验新的代码

        #     # 如果校验通过，执行代码
        #     print("Code validation passed. Executing the code...")
        #     try:
        #         exec(command, global_dict, local_dict)
        #         break  # 执行成功，退出循环
        #     except Exception as e:
        #         # 如果执行过程中出现错误，也反馈给 LLM
        #         print(f"Code execution failed: {str(e)}")
        #         print("LLM: Please regenerate the code to fix execution errors.")
        #         command = self.regenerate_code([str(e)], command, global_dict["agent"], session_id, global_dict.get("lang", "en"))
        #         continue  # 重新校验新的代码

        # if attempts >= max_attempts:
        #     print("Maximum attempts reached. Unable to generate valid code.")
        #     raise RuntimeError("Failed to generate valid code after multiple attempts.")

        # 校验并修复代码
        # command = self.validator.validate_and_fix_code(command)

        exec(command, global_dict, local_dict)            

        # 匹配所有 graph.node 中的内容
        # node_list = re.findall(r"graph.node\((.*?)\)", command)

        # 由于 LLM 的幻觉问题，导致生成的 graph.node() 里面的节点名称和 add_node() 里面的节点名称不一致，导致 keyerror
        # 因此需要从 graph.add_node() 中提取节点名称
        node_list = re.findall(r"graph.add_node\(\s*node_name\s*=\s*\"([^\"]+)\"", command)

        # 返回结果
        graph: WebSearchGraph = local_dict["graph"]
        while graph.n_active_tasks:
            while not graph.searcher_resp_queue.empty():
                node_name, _, _ = graph.searcher_resp_queue.get(timeout=60)
                if isinstance(node_name, Exception):
                    raise node_name
                if node_name is None:
                    graph.n_active_tasks -= 1
                    continue
                if stream_graph:
                    for neighbors in graph.adjacency_list.values():
                        for neighbor in neighbors:
                            # state  1进行中，2未开始，3已结束
                            if not (
                                neighbor["name"] in graph.nodes
                                and "response" in graph.nodes[neighbor["name"]]
                            ):
                                neighbor["state"] = 2
                            elif (
                                graph.nodes[neighbor["name"]]["response"]["stream_state"]
                                == AgentStatusCode.END
                            ):
                                neighbor["state"] = 3
                            else:
                                neighbor["state"] = 1
                    if all(
                        "response" in node
                        for name, node in graph.nodes.items()
                        if name not in ["root", "response"]
                    ):
                        yield AgentMessage(
                            sender=self.name,
                            content=dict(current_node=node_name),
                            formatted=dict(
                                node=deepcopy(graph.nodes),
                                adjacency_list=deepcopy(graph.adjacency_list),
                            ),
                            stream_state=AgentStatusCode.STREAM_ING,
                        )
        res = [graph.nodes[node.strip().strip('"').strip("'")] for node in node_list]
        return res, graph.nodes, graph.adjacency_list

    # async def run_async(self, command, local_dict, global_dict, is_first_generation=False, nodes_added=None, session_id=0, stream_graph=False):
    # # def run(self, command, local_dict, global_dict, is_first_generation=False, nodes_added=None, session_id=0, stream_graph=False):
    #     # 将调试信息输出到文件中
    #     # with open("debug_info.txt", "a") as f:
    #     #     f.write(f"Command: {command}\n")
    #     #     f.write(f"Global Dict: {global_dict}\n")
    #     #     f.write(f"Local Dict: {local_dict}\n")
    #     print(f"Executing command: {command}")  # 调试信息

    #     def extract_code(text: str) -> str:
    #         text = re.sub(r"from ([\w.]+) import WebSearchGraph", "", text)
    #         triple_match = re.search(r"```[^\n]*\n(.+?)```", text, re.DOTALL)
    #         single_match = re.search(r"`([^`]*)`", text, re.DOTALL)
    #         if triple_match:
    #             return triple_match.group(1)
    #         elif single_match:
    #             return single_match.group(1)
    #         return text

    #     command = extract_code(command)

    #     # # 通过 self.agent 访问 MindSearchAgent
    #     # agent = self.agent
    #     # if agent is None:
    #     #     raise RuntimeError("Agent is not initialized.")

    #     # print(f"Agent: {agent}, Session ID: {session_id}")

    #     # 初始化 CodeValidationAgent
    #     validator = CodeValidationAgent(nodes_added, is_first_generation)

    #     # # 获取当前的 LLM 实例和会话 ID
    #     # # agent = global_dict.get("agent")
    #     # # session_id = global_dict.get("session_id", 0)
    #     # # lang = global_dict.get("lang", "en")  # 获取语言设置，默认为英文

    #     # # 打印agent、session_id和lang
    #     # # print(f"Agent: {agent}, Session ID: {session_id}, Language: {lang}")

    #     # # if agent is None:
    #     # #     raise RuntimeError("LLM agent is not initialized.")

    #     # 循环校验和执行代码
    #     max_attempts = 1  # 限制最大尝试次数
    #     attempts = 0

    #     while attempts < max_attempts:
    #         attempts += 1

    #         # 校验代码
    #         is_valid, errors = validator.validate_code(command)
    #         if not is_valid:
    #             # 打印错误信息并提醒 LLM
    #             print(f"Code validation failed: {errors}")
    #             print("LLM: Please regenerate the code based on the above errors.")

    #             # 让当前 LLM 实例重新生成代码
    #             command = await self.regenerate_code(errors, command, global_dict["agent"], session_id, global_dict.get("lang", "en"))
    #             continue  # 重新校验新的代码

    #         # 如果校验通过，执行代码
    #         print("Code validation passed. Executing the code...")
    #         try:
    #             exec(command, global_dict, local_dict)
    #             break  # 执行成功，退出循环
    #         except Exception as e:
    #             # 如果执行过程中出现错误，也反馈给 LLM
    #             print(f"Code execution failed: {str(e)}")
    #             print("LLM: Please regenerate the code to fix execution errors.")
    #             command = await self.regenerate_code([str(e)], command, global_dict["agent"], session_id, global_dict.get("lang", "en"))
    #             continue  # 重新校验新的代码

    #     if attempts >= max_attempts:
    #         print("Maximum attempts reached. Unable to generate valid code.")
    #         raise RuntimeError("Failed to generate valid code after multiple attempts.")
            
    #     # exec(command, global_dict, local_dict)

    #     # 匹配所有 graph.node 中的内容
    #     # node_list = re.findall(r"graph.node\((.*?)\)", command)

    #     # 由于 LLM 的幻觉问题，导致生成的 graph.node() 里面的节点名称和 add_node() 里面的节点名称不一致，导致 keyerror
    #     # 因此需要从 graph.add_node() 中提取节点名称
    #     node_list = re.findall(r"graph.add_node\(\s*node_name\s*=\s*\"([^\"]+)\"", command)

    #     # #将 command 和 node_list 输出到文件中
    #     # with open("debug_info.txt", "a") as f:
    #     #     f.write(f"Command: {command}\n")
    #     #     f.write(f"Node List: {node_list}\n")

    #     graph: WebSearchGraph = local_dict["graph"]
    #     while graph.n_active_tasks:
    #         while not graph.searcher_resp_queue.empty():
    #             node_name, _, _ = graph.searcher_resp_queue.get(timeout=60)
    #             if isinstance(node_name, Exception):
    #                 raise node_name
    #             if node_name is None:
    #                 graph.n_active_tasks -= 1
    #                 continue
    #             if stream_graph:
    #                 for neighbors in graph.adjacency_list.values():
    #                     for neighbor in neighbors:
    #                         # state  1进行中，2未开始，3已结束
    #                         if not (
    #                             neighbor["name"] in graph.nodes
    #                             and "response" in graph.nodes[neighbor["name"]]
    #                         ):
    #                             neighbor["state"] = 2
    #                         elif (
    #                             graph.nodes[neighbor["name"]]["response"]["stream_state"]
    #                             == AgentStatusCode.END
    #                         ):
    #                             neighbor["state"] = 3
    #                         else:
    #                             neighbor["state"] = 1
    #                 if all(
    #                     "response" in node
    #                     for name, node in graph.nodes.items()
    #                     if name not in ["root", "response"]
    #                 ):
    #                     yield AgentMessage(
    #                         sender=self.name,
    #                         content=dict(current_node=node_name),
    #                         formatted=dict(
    #                             node=deepcopy(graph.nodes),
    #                             adjacency_list=deepcopy(graph.adjacency_list),
    #                         ),
    #                         stream_state=AgentStatusCode.STREAM_ING,
    #                     )
    #     res = [graph.nodes[node.strip().strip('"').strip("'")] for node in node_list]
    #     # return res, graph.nodes, graph.adjacency_list
    
    #     # 使用 yield 返回最终结果
    #     yield res, graph.nodes, graph.adjacency_list





    # # def regenerate_code(self, errors: List[str], original_code: str, agent, session_id: int, lang: str = "en") -> str:
    # async def regenerate_code(self, errors: List[str], original_code: str, agent, session_id: int, lang: str = "en") -> str:
    #     """
    #     根据错误信息让当前 LLM 实例重新生成代码。
    #     """
    #     # 根据语言选择提示词
    #     if lang == "en":
    #         prompt_template = REGENERATE_CODE_PROMPT_EN
    #     else:
    #         prompt_template = REGENERATE_CODE_PROMPT_CN

    #     # 格式化提示词
    #     prompt = prompt_template.format(
    #         original_code=original_code,
    #         errors="\n".join(f"{i + 1}. {error}" for i, error in enumerate(errors))
    #     )

    #     # 调用当前 LLM 实例
    #     print(f"Regenerating code with the following prompt:\n{prompt}")
    #     # try:
    #     #     # 使用当前的 LLM 实例与其对话
    #     #     response = agent(
    #     #         AgentMessage(
    #     #             sender="user",
    #     #             content=prompt,
    #     #         ),
    #     #         session_id=session_id,
    #     #     )

    #     #     if response is None:
    #     #         raise RuntimeError("LLM returned None.")

    #     #     # 获取 LLM 的响应
    #     #     for message in response:
    #     #         # if message.stream_state == AgentStatusCode.END:
    #     #         #     new_code = message.content
    #     #         #     print(f"Generated new code:\n{new_code}")
    #     #         #     return new_code

    #     #         new_code = message.content
    #     #         print(f"Generated new code:\n{new_code}")
    #     #         return new_code

    #     try:
    #         # 使用当前的 LLM 实例与其对话
    #         async for message in agent(
    #             AgentMessage(
    #                 sender="user",
    #                 content=prompt,
    #             ),
    #             session_id=session_id,
    #         ):
    #             if message.stream_state == AgentStatusCode.END:
    #                 new_code = message.content
    #                 print(f"Generated new code:\n{new_code}")
    #                 return new_code
    #     except Exception as e:
    #         print(f"Error while regenerating code: {e}")
    #         return ""
        
    #     return ""