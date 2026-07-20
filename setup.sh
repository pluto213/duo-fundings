启动命令：

# 激活虚拟环境
source venv/bin/activate

# 启动（开发模式，代码修改自动重启）
uvicorn main:app --reload

# 指定端口
uvicorn main:app --reload --port 8000

# 生产环境（不需要 --reload）
uvicorn main:app --host 0.0.0.0 --port 8000