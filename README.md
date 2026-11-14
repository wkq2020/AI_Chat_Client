# AI_Chat_Client

基于 PySide6 构建的 AI 桌面客户端。支持多会话并发状态管理、流式 Markdown 渲染、显式上下文缓存（Qwen）、深度思考和自定义壁纸，目前主要针对 DeepSeek 和 Qwen 优化适配。

## 运行

建议使用 Python 3.11：

```bash
python -m pip install -r requirements.txt
python main.py
```

Base URL 支持以下形式：

```text
https://api.example.com
https://api.example.com/v1
https://api.example.com/v1/chat/completions
```

API 密钥默认保存在操作系统钥匙串中。旧配置里的明文密钥会在启动时自动迁移；如果系统钥匙串不可用，则回退到本地 `data/config.json`。运行时配置、聊天数据库和调试日志均位于已被 Git 忽略的 `data/` 目录。

## 回归测试

```bash
python -m unittest discover -s tests -v
```

测试使用本地模拟 SSE 服务和隔离数据目录，不会调用真实 API，也不会读取或写入真实的 API 密钥。覆盖请求地址、密钥迁移、系统提示词、重新生成、多会话删除、停止与关闭、消息持久化及 Web 注入防护等场景。
