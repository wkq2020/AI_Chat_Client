import httpx
import json
import os
from datetime import datetime

# 【新增】调试日志目录配置
DEBUG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'debug')
os.makedirs(DEBUG_DIR, exist_ok=True)

# 【新增】调试开关 (自测时设为 True，打包发布时建议设为 False)
ENABLE_DEBUG_LOG = False 

def log_debug(session_id, payload, response_chunks, error_msg=None):
    """将请求和响应保存为 JSON 文件"""
    if not ENABLE_DEBUG_LOG:
        return
        
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # 截取 session_id 前 8 位作为文件名一部分，防止过长
    short_sid = session_id[:8] if session_id else "unknown"
    filename = f"req_{short_sid}_{timestamp}.json"
    filepath = os.path.join(DEBUG_DIR, filename)

    debug_data = {
        "timestamp": timestamp,
        "session_id": session_id,
        "request_payload": payload,
        "response_chunks": response_chunks
    }
    if error_msg:
        debug_data["error"] = error_msg

    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(debug_data, f, ensure_ascii=False, indent=2)
        print(f"\n🔍 [DEBUG] 原始请求与响应已保存至: {filepath}\n")
    except Exception as e:
        print(f"\n❌ [DEBUG] 保存调试日志失败: {e}\n")


def stream_chat(api_key: str, base_url: str, model: str, messages: list, session_id: str, enable_search: bool = False, thinking_config: dict = None, client: httpx.Client = None):
    url = base_url.rstrip('/')
    if not url.endswith('/chat/completions'):
        url = f"{url}/v1/chat/completions"
        
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True} 
    }
    
    if enable_search:
        payload["enable_search"] = True
        
    # 思考控制参数精准注入
    if thinking_config:
        protocol = thinking_config.get("protocol")
        is_enabled = thinking_config.get("enabled", False)
        ctrl_val = thinking_config.get("value")
        
        if protocol == "deepseek":
            if is_enabled:
                payload["thinking"] = {"type": "enabled"}
                if ctrl_val:
                    payload["reasoning_effort"] = ctrl_val
            else:
                payload["thinking"] = {"type": "disabled"}
        elif protocol == "qwen":
            payload["enable_thinking"] = is_enabled
            if is_enabled and ctrl_val and ctrl_val != "auto":
                try:
                    payload["thinking_budget"] = int(ctrl_val)
                except ValueError:
                    pass

    # 【新增】用于收集完整的响应 chunks
    response_chunks = []
    error_msg = None

    try:
        # 【修复】支持外部传入 httpx.Client，以便 Worker 可以中断阻塞的连接
        own_client = client is None
        if own_client:
            client = httpx.Client(timeout=120.0)
        try:
            with client.stream("POST", url, json=payload, headers=headers) as response:
                response.raise_for_status()
                
                for line in response.iter_lines():
                    if not line.strip(): continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]": 
                            response_chunks.append({"type": "DONE"})
                            break
                        try:
                            data = json.loads(data_str)
                            # 将原始解析后的 dict 存入日志
                            response_chunks.append(data)
                            
                            if "usage" in data and data["usage"]:
                                yield {"type": "usage", "data": data["usage"]}
                                continue
                            choices = data.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                                if reasoning:
                                    yield {"type": "thinking", "data": reasoning}
                                content = delta.get("content", "")
                                if content:
                                    yield {"type": "content", "data": content}
                        except (json.JSONDecodeError, KeyError, IndexError) as e:
                            response_chunks.append({"raw_line": line, "parse_error": str(e)})
                            continue
        finally:
            if own_client:
                client.close()
    except Exception as e:
        error_msg = str(e)
        raise e
    finally:
        # 【核心】无论流是正常结束、被手动 stop 中断、还是发生网络异常，都会执行这里保存日志
        log_debug(session_id, payload, response_chunks, error_msg)