import json
import logging
import re
from copy import deepcopy
from typing import Dict, Tuple

from lagent.schema import AgentMessage, AgentStatusCode, ModelStatusCode
from lagent.utils import GeneratorWithReturn

from .graph import ExecutionAction, WebSearchGraph
from .streaming import AsyncStreamingAgentForInternLM, StreamingAgentForInternLM

from .code_validation_2 import CodeValidationAgent  # 引入代码校验模块
from .mindsearch_prompt import REGENERATE_CODE_PROMPT_EN, REGENERATE_CODE_PROMPT_CN

def _update_ref(ref: str, ref2url: Dict[str, str], ptr: int) -> str:
    numbers = list({int(n) for n in re.findall(r"\[\[(\d+)\]\]", ref)})
    numbers = {n: idx + 1 for idx, n in enumerate(numbers)}
    updated_ref = re.sub(
        r"\[\[(\d+)\]\]",
        lambda match: f"[[{numbers[int(match.group(1))] + ptr}]]",
        ref,
    )
    updated_ref2url = {}
    if numbers:
        try:
            assert all(elem in ref2url for elem in numbers)
        except Exception as exc:
            logging.info(f"Illegal reference id: {str(exc)}")
        if ref2url:
            updated_ref2url = {
                numbers[idx] + ptr: ref2url[idx] for idx in numbers if idx in ref2url
            }
    return updated_ref, updated_ref2url, len(numbers) + 1


def _generate_references_from_graph(graph: Dict[str, dict]) -> Tuple[str, Dict[int, dict]]:
    ptr, references, references_url = 0, [], {}
    for name, data_item in graph.items():
        if name in ["root", "response"]:
            continue
        # only search once at each node, thus the result offset is 2
        assert data_item["memory"]["agent.memory"][2]["sender"].endswith("ActionExecutor")
        ref2url = {
            int(k): v
            for k, v in json.loads(data_item["memory"]["agent.memory"][2]["content"]).items()
        }
        updata_ref, ref2url, added_ptr = _update_ref(
            data_item["response"]["content"], ref2url, ptr
        )
        ptr += added_ptr
        references.append(f'## {data_item["content"]}\n\n{updata_ref}')
        references_url.update(ref2url)
    return "\n\n".join(references), references_url


class MindSearchAgent(StreamingAgentForInternLM):
    def __init__(
        self,
        searcher_cfg: dict,
        summary_prompt: str,
        finish_condition=lambda m: "add_response_node" in m.content,
        max_turn: int = 10,
        **kwargs,
    ):
        WebSearchGraph.SEARCHER_CONFIG = searcher_cfg
        super().__init__(finish_condition=finish_condition, max_turn=max_turn, **kwargs)
        self.summary_prompt = summary_prompt
        self.action = ExecutionAction()

        # self.is_first_generation = True  # 标记是否是第一次生成代码
        # self.nodes_added = set()  # 全局记录已添加的节点

    def forward(self, message: AgentMessage, session_id=0, **kwargs):
        if isinstance(message, str):
            message = AgentMessage(sender="user", content=message)

        _graph_state = dict(node={}, adjacency_list={}, ref2url={})
        local_dict, global_dict = {}, globals()
        
        for _ in range(self.max_turn):
            last_agent_state = AgentStatusCode.SESSION_READY
            for message in self.agent(message, session_id=session_id, **kwargs):
                if isinstance(message.formatted, dict) and message.formatted.get("tool_type"):
                    if message.stream_state == ModelStatusCode.END:
                        message.stream_state = last_agent_state + int(
                            last_agent_state
                            in [
                                AgentStatusCode.CODING,
                                AgentStatusCode.PLUGIN_START,
                            ]
                        )
                    else:
                        message.stream_state = (
                            AgentStatusCode.PLUGIN_START
                            if message.formatted["tool_type"] == "plugin"
                            else AgentStatusCode.CODING
                        )
                else:
                    message.stream_state = AgentStatusCode.STREAM_ING
                message.formatted.update(deepcopy(_graph_state))
                yield message
                last_agent_state = message.stream_state

            if not message.formatted["tool_type"]:
                message.stream_state = AgentStatusCode.END
                yield message
                return

            # 调用 ExecutionAction 校验并执行代码
            gen = GeneratorWithReturn(
                self.action.run_sync(message.content, local_dict, global_dict, True)
            )
            for graph_exec in gen:
                graph_exec.formatted["ref2url"] = deepcopy(_graph_state["ref2url"])
                yield graph_exec

            # 更新 is_first_generation 状态
            self.is_first_generation = False

            reference, references_url = _generate_references_from_graph(gen.ret[1])
            _graph_state.update(node=gen.ret[1], adjacency_list=gen.ret[2], ref2url=references_url)
            if self.finish_condition(message):
                message = AgentMessage(
                    sender="ActionExecutor",
                    content=self.summary_prompt,
                    formatted=deepcopy(_graph_state),
                    stream_state=message.stream_state + 1,  # plugin or code return
                )
                yield message
                # summarize the references to generate the final answer
                for message in self.agent(message, session_id=session_id, **kwargs):
                    message.formatted.update(deepcopy(_graph_state))
                    yield message
                return
            message = AgentMessage(
                sender="ActionExecutor",
                content=reference,
                formatted=deepcopy(_graph_state),
                stream_state=message.stream_state + 1,  # plugin or code return
            )
            yield message


class AsyncMindSearchAgent(AsyncStreamingAgentForInternLM):
    def __init__(
        self,
        searcher_cfg: dict,
        summary_prompt: str,
        finish_condition=lambda m: "add_response_node" in m.content,
        max_turn: int = 10,
        lang="cn",
        **kwargs,
        # inputs, session_id=session_id
    ):
        WebSearchGraph.SEARCHER_CONFIG = searcher_cfg
        WebSearchGraph.is_async = True
        WebSearchGraph.start_loop()
        super().__init__(finish_condition=finish_condition, max_turn=max_turn, **kwargs)
        self.summary_prompt = summary_prompt
        self.action = ExecutionAction()

        self.is_first_generation = True  # 标记是否是第一次生成代码
        self.nodes_added = set()  # 全局记录已添加的节点

        self.lang = lang  # 语言设置

    async def forward(self, message: AgentMessage, session_id=0, **kwargs):

        if isinstance(message, str):
            message = AgentMessage(sender="user", content=message)

        _graph_state = dict(node={}, adjacency_list={}, ref2url={})
        local_dict, global_dict = {}, globals()

        for _ in range(self.max_turn):
            last_agent_state = AgentStatusCode.SESSION_READY
            async for message in self.agent(message, session_id=session_id, **kwargs):
                if isinstance(message.formatted, dict) and message.formatted.get("tool_type"):
                    if message.stream_state == ModelStatusCode.END:
                        message.stream_state = last_agent_state + int(
                            last_agent_state
                            in [
                                AgentStatusCode.CODING,
                                AgentStatusCode.PLUGIN_START,
                            ]
                        )
                    else:
                        message.stream_state = (
                            AgentStatusCode.PLUGIN_START
                            if message.formatted["tool_type"] == "plugin"
                            else AgentStatusCode.CODING
                        )
                else:
                    message.stream_state = AgentStatusCode.STREAM_ING
                message.formatted.update(deepcopy(_graph_state))
                yield message
                last_agent_state = message.stream_state

            if not message.formatted["tool_type"]:
                message.stream_state = AgentStatusCode.END
                yield message
                return
            
            # **代码校验逻辑**
            if "<|action_start|><|interpreter|>" in message.content:
                validator = CodeValidationAgent(self.is_first_generation, self.nodes_added)

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

                command = extract_code(message.content)

                is_valid, errors = validator.validate_code(command)

                if not is_valid:
                    # 如果代码未通过校验，提示 LLM 重新生成代码
                    print(f"Code validation failed: {errors}")
                    message.stream_state = AgentStatusCode.END

                    # 根据语言选择提示词
                    if self.lang == "en":
                        prompt_template = REGENERATE_CODE_PROMPT_EN
                    else:
                        prompt_template = REGENERATE_CODE_PROMPT_CN

                    # 格式化提示词
                    prompt = prompt_template.format(
                        original_code=message.content,
                        errors="\n".join(f"{i + 1}. {error}" for i, error in enumerate(errors))
                    )

                    print(f"Regenerating code with the following prompt:\n{prompt}")

                    # 让 LLM 重新生成代码
                    new_message = AgentMessage(
                        sender="CodeValidator",
                        content=prompt,
                        formatted=deepcopy(_graph_state),
                        stream_state=message.stream_state,
                    )

                    # 调用 LLM 重新生成代码
                    async for regenerated_message in self.agent(new_message, session_id=session_id, **kwargs):
                        print(f"Regenerated code: {regenerated_message.content}")

                        # 对重新生成的代码进行校验
                        regenerated_command = extract_code(regenerated_message.content)
                        is_valid, errors = validator.validate_code(regenerated_command)
                        
                        if is_valid:
                            # 如果校验通过，继续执行
                            yield regenerated_message
                            break
                        else:
                            # 如果校验失败，继续提示 LLM 修复代码
                            print(f"Regenerated code validation failed: {errors}")
                            new_message = AgentMessage(
                                sender="CodeValidator",
                                content=prompt_template.format(
                                    original_code=regenerated_message.content,
                                    errors="\n".join(f"{i + 1}. {error}" for i, error in enumerate(errors)),
                                ),
                                formatted=deepcopy(_graph_state),
                                stream_state=regenerated_message.stream_state,
                            )
                    message = regenerated_message
                    # return

            # 调用 ExecutionAction 校验并执行代码
            gen = GeneratorWithReturn(
                self.action.run_sync(message.content, local_dict, global_dict, True)
            )
            for graph_exec in gen:
                graph_exec.formatted["ref2url"] = deepcopy(_graph_state["ref2url"])
                yield graph_exec

            # 更新 is_first_generation 状态
            self.is_first_generation = False
            
            reference, references_url = _generate_references_from_graph(gen.ret[1])
            _graph_state.update(node=gen.ret[1], adjacency_list=gen.ret[2], ref2url=references_url)
            if self.finish_condition(message):
                message = AgentMessage(
                    sender="ActionExecutor",
                    content=self.summary_prompt,
                    formatted=deepcopy(_graph_state),
                    stream_state=message.stream_state + 1,  # plugin or code return
                )
                yield message
                # summarize the references to generate the final answer
                async for message in self.agent(message, session_id=session_id, **kwargs):
                    message.formatted.update(deepcopy(_graph_state))
                    yield message
                return
            message = AgentMessage(
                sender="ActionExecutor",
                content=reference,
                formatted=deepcopy(_graph_state),
                stream_state=message.stream_state + 1,  # plugin or code return
            )
            yield message