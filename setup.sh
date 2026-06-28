#!/bin/bash
echo "创建虚拟环境..."
python3 -m venv fund_venv

echo "激活虚拟环境..."
source fund_venv/bin/activate

echo "安装依赖包..."
pip install --upgrade pip
pip install requests pandas numpy scipy matplotlib scikit-learn

echo "安装完成！"
echo "运行 'source fund_venv/bin/activate' 激活环境"
echo "然后运行 'python fund_cluster.py'"