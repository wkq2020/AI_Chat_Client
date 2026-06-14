from PySide6.QtCore import QThread, Signal
import httpx
from src.core.llm_client import stream_chat

class LLMStreamWorker(QThread):
    # 【核心修改】所有信号增加 session_id 参数，用于身份校验
    thinking_received = Signal(str, str)  
    token_received = Signal(str, str)
    usage_received = Signal(dict, str)  
    stream_finished = Signal(str)
    error_occurred = Signal(str, str)

    def __init__(self, api_key, base_url, model, messages, session_id, enable_search=False, thinking_config=None):
        super().__init__()
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.messages = messages
        self.session_id = session_id 
        self.enable_search = enable_search 
        self.thinking_config = thinking_config # 【新增】
        self._is_running = True
        # 【修复】创建独立的 httpx.Client，以便 stop() 可以中断阻塞的连接
        self._client = httpx.Client(timeout=120.0)

    def stop(self):
        """【修复】中断 Worker：关闭 httpx 连接，强制解除 iter_lines() 阻塞"""
        self._is_running = False
        try:
            self._client.close()
        except Exception:
            pass

    def run(self):
        try:
            # 【修改】透传 thinking_config + 外部 client
            for chunk in stream_chat(
                self.api_key, 
                self.base_url, 
                self.model, 
                self.messages, 
                session_id=self.session_id, # <--- 新增透传
                enable_search=self.enable_search, 
                thinking_config=self.thinking_config,
                client=self._client
            ):
                if not self._is_running:
                    break 
                    
                if chunk["type"] == "thinking":
                    self.thinking_received.emit(chunk["data"], self.session_id) 
                elif chunk["type"] == "content":
                    self.token_received.emit(chunk["data"], self.session_id)
                elif chunk["type"] == "usage":
                    self.usage_received.emit(chunk["data"], self.session_id)
                    
            self.stream_finished.emit(self.session_id)
            
        except httpx.HTTPStatusError as e:
            if self._is_running: 
                try:
                    error_text = e.response.read().decode('utf-8')[:100]
                except Exception:
                    error_text = "无法读取错误详情"
                self.error_occurred.emit(f"API 错误 ({e.response.status_code}): {error_text}", self.session_id)
            else:
                # 用户主动停止导致的连接中断，正常结束
                self.stream_finished.emit(self.session_id)
        except (httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError) as e:
            if self._is_running:
                self.error_occurred.emit(f"网络连接错误: {type(e).__name__}", self.session_id)
            else:
                # 用户主动关闭连接导致的异常，正常结束
                self.stream_finished.emit(self.session_id)
        except Exception as e:
            if self._is_running:
                self.error_occurred.emit(f"网络或未知错误: {str(e)}", self.session_id)
            else:
                self.stream_finished.emit(self.session_id)
        finally:
            try:
                self._client.close()
            except Exception:
                pass