# 飞机智能设计平台 · L3 端到端

AI Agent 自动调度 SUAVE 工具链, 根据用户需求跑完一整套设计流程。

## 📁 目录结构

```
aidesign_l3/
├── config.py             全局配置 (端口/路径/模型)
├── agent.py              LLM Agent 编排器
├── runs.py               设计 run 管理 (SQLite)
├── tasks.py              Celery 任务定义
├── server.py             FastAPI 后端
├── index.html            前端页面
├── tools/                
│   ├── __init__.py       工具基类 + 注册机制
│   ├── tool_requirements.py    工具 1: 需求处理 ✅
│   ├── tool_aerodynamics.py    工具 2: 气动 (待补)
│   ├── tool_optimize.py        工具 3: 优化 (待补)
│   ├── tool_weights.py         工具 4: 重量 (待补)
│   └── tool_propulsion.py      工具 5: 电推进 (待补)
├── requirements.txt
├── start.sh              一键启动
├── stop.sh               一键停止
├── fix_redis.sh          Redis 启动 (之前给过)
├── skill.md              AI 知识源 (可选, 放进来)
├── runs/                 每个设计运行的产物
└── logs/                 server + celery 日志
```

## 🚀 部署步骤

### 1. 准备依赖

```bash
# 假设你用 base conda 环境
pip install -r requirements.txt

# 验证 conda 里有 suave-py310 (前面已装)
conda env list | grep suave
```

### 2. 准备 Redis

```bash
bash fix_redis.sh    # 这一步前面已经做过, redis_port.txt 已生成
```

### 3. 把 skill.md 放进项目目录 (可选但推荐)

```bash
cp /data_SSD_21T/users/zhaolize/skill_for_yes/skill.md ./skill.md
```

### 4. 启动

```bash
bash start.sh
```

启动后会有两个进程后台运行:
- Celery worker - 跑设计任务
- FastAPI server - 监听 8881 端口

### 5. 浏览器访问

```
http://10.90.111.114:8881
```

填表 → 点"启动 AI 设计" → 看实时进度看板。

## 🛠 调试

```bash
# 看 Celery worker 输出 (任务执行日志)
tail -f logs/celery.log

# 看 FastAPI server 输出 (请求日志)
tail -f logs/server.log

# 测试 API 健康状态
curl http://127.0.0.1:8881/api/health
```

## 🛑 停止

```bash
bash stop.sh
```

不会停 Redis (它单独控制)。

## ⚠️ 当前状态 (本版本)

**已完成:**
- ✅ 整体架构: Agent + Celery + FastAPI + 前端
- ✅ 工具 1 (需求处理) - 纯 Python 计算, 不依赖 SUAVE

**待补完:**
- ⏳ 工具 2-5 (气动/优化/重量/电推进) - 需要真正调 SUAVE

**测试预期:**
- 启动后, AI 会调用工具 1 给出 Vehicle 配置
- 然后 AI 会尝试调用工具 2, **会失败** (因为还没实现)
- 这正常 — 这个版本的目标是验证整套架构能跑通

## 🔄 下一步

跑通本版本之后, 把 `tool_aerodynamics.py` 的实际 SUAVE 调用代码补上, 流程就能往前走一步。然后依次补 3、4、5。
