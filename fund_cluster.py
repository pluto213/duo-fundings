"""
基金持仓分析工具 - AKShare版本
功能：从txt文件读取基金代码，使用AKShare获取基金持仓数据，
      计算基金间的持仓相似度，将相关性高的基金分组
"""

import akshare as ak
import pandas as pd
import numpy as np
from scipy.spatial.distance import squareform
from scipy.cluster.hierarchy import linkage, fcluster, dendrogram
import matplotlib.pyplot as plt
from typing import List, Dict, Optional, Tuple
import time
import json
import os
from pathlib import Path

# 设置matplotlib中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False


# ==================== 第一部分：基金代码读取 ====================

class FundCodeReader:
    """从txt文件读取基金代码"""
    
    @staticmethod
    def read_from_txt(file_path: str) -> List[str]:
        """
        从txt文件读取基金代码
        
        文件格式示例：
            每行一个基金代码，支持#号注释，支持空行跳过
        
        示例内容：
            # 这是注释行
            110011  # 易方达中小盘
            161725  # 招商白酒
            005827  # 易方达蓝筹精选
        
        参数:
            file_path: txt文件路径
            
        返回:
            基金代码列表
        """
        fund_codes = []
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                
                # 跳过空行
                if not line:
                    continue
                
                # 跳过注释行（以#开头）
                if line.startswith('#'):
                    continue
                
                # 提取基金代码（支持注释在代码后面）
                if '#' in line:
                    line = line.split('#')[0].strip()
                
                # 提取6位数字的基金代码
                import re
                match = re.search(r'\b\d{6}\b', line)
                if match:
                    fund_code = match.group()
                    fund_codes.append(fund_code)
                else:
                    print(f"警告：第{line_num}行没有找到有效的6位基金代码: {line}")
        
        return fund_codes
    
    @staticmethod
    def create_template_file(file_path: str = "fund_codes.txt"):
        """创建基金代码模板文件"""
        template_content = """# 基金代码列表
# 每行一个基金代码，支持#号注释
# 示例：

110011  # 易方达中小盘混合
161725  # 招商中证白酒指数
005827  # 易方达蓝筹精选混合
001632  # 天弘中证食品饮料指数C
003095  # 中欧医疗健康混合A

# 请将上面的示例替换为你需要分析的基金代码
"""
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(template_content)
        print(f"已创建模板文件: {file_path}")


# ==================== 第二部分：基金持仓数据获取 ====================

class FundDataFetcher:
    """使用AKShare获取基金持仓数据"""
    
    def __init__(self, cache_enabled: bool = True, cache_dir: str = "fund_cache"):
        """
        初始化
        
        参数:
            cache_enabled: 是否启用缓存（避免重复请求）
            cache_dir: 缓存目录
        """
        self.cache_enabled = cache_enabled
        self.cache_dir = cache_dir
        
        if cache_enabled:
            Path(cache_dir).mkdir(exist_ok=True)
        
        print("初始化AKShare基金数据获取器...")
    
    def _get_cache_path(self, fund_code: str) -> str:
        """获取缓存文件路径"""
        return os.path.join(self.cache_dir, f"{fund_code}.csv")
    
    def _load_from_cache(self, fund_code: str) -> Optional[pd.DataFrame]:
        """从缓存加载数据"""
        if not self.cache_enabled:
            return None
        
        cache_path = self._get_cache_path(fund_code)
        if os.path.exists(cache_path):
            try:
                df = pd.read_csv(cache_path)
                print(f"  从缓存加载 {fund_code}")
                return df
            except Exception as e:
                print(f"  缓存读取失败: {e}")
        return None
    
    def _save_to_cache(self, fund_code: str, df: pd.DataFrame):
        """保存数据到缓存"""
        if self.cache_enabled:
            cache_path = self._get_cache_path(fund_code)
            df.to_csv(cache_path, index=False)
    
    def get_fund_holdings(self, fund_code: str, use_cache: bool = True) -> Optional[pd.DataFrame]:
        """
        获取单只基金的持仓数据
        
        参数:
            fund_code: 基金代码，如 '110011'
            use_cache: 是否使用缓存
            
        返回:
            DataFrame包含持仓数据，失败返回None
        """
        # 尝试从缓存读取
        if use_cache:
            cached_data = self._load_from_cache(fund_code)
            if cached_data is not None:
                return cached_data
        
        try:
            # 尝试获取基金持仓数据
            holdings_df = None
            
            # 方法1: 使用 fund_portfolio_hold_em
            try:
                holdings_df = ak.fund_portfolio_hold_em(symbol=fund_code, date="2026")
                if holdings_df is not None and not holdings_df.empty:
                    print(f"  ✓ 成功获取 {fund_code} 持仓数据 ({len(holdings_df)} 条)")
            except Exception as e1:
                print(f"  方法1失败: {e1}")
                
                # 方法2: 尝试 fund_portfolio_hold_detail_em
                try:
                    holdings_df = ak.fund_portfolio_hold_detail_em(symbol=fund_code)
                    if holdings_df is not None and not holdings_df.empty:
                        print(f"  ✓ 成功获取 {fund_code} 持仓数据 ({len(holdings_df)} 条)")
                except Exception as e2:
                    print(f"  方法2失败: {e2}")
                    return None
            
            if holdings_df is None or holdings_df.empty:
                print(f"  ✗ 基金 {fund_code} 无持仓数据")
                return None
            
            # 标准化数据格式
            holdings_df = self._standardize_holdings(holdings_df, fund_code)
            
            # 保存到缓存
            if use_cache:
                self._save_to_cache(fund_code, holdings_df)
            
            return holdings_df
            
        except Exception as e:
            print(f"  ✗ 获取基金 {fund_code} 数据失败: {e}")
            return None
    
    def _standardize_holdings(self, df: pd.DataFrame, fund_code: str) -> pd.DataFrame:
        """标准化持仓数据格式"""
        df = df.copy()
        
        # 列名映射（中英文）
        column_mapping = {
            '股票代码': 'stock_code',
            '股票简称': 'stock_name',
            '股票名称': 'stock_name',
            '占净值比例': 'weight',
            '占净值比': 'weight',
            '持仓占比': 'weight',
            '持股数': 'shares',
            '持仓数量': 'shares',
            '持仓市值': 'market_value',
            '市值': 'market_value',
            '报告期': 'report_date'
        }
        
        # 执行列名映射
        for old_name, new_name in column_mapping.items():
            if old_name in df.columns and new_name not in df.columns:
                df.rename(columns={old_name: new_name}, inplace=True)
        
        # 确保必要列存在
        if 'stock_code' not in df.columns:
            # 尝试从其他列提取股票代码
            if '代码' in df.columns:
                df.rename(columns={'代码': 'stock_code'}, inplace=True)
            elif '证券代码' in df.columns:
                df.rename(columns={'证券代码': 'stock_code'}, inplace=True)
        
        if 'stock_name' not in df.columns:
            if '名称' in df.columns:
                df.rename(columns={'名称': 'stock_name'}, inplace=True)
            elif '证券名称' in df.columns:
                df.rename(columns={'证券名称': 'stock_name'}, inplace=True)
        
        # 处理持仓占比 - 转换为小数格式
        if 'weight' in df.columns:
            # 检查是否需要转换百分比（数值大于1表示可能是百分比）
            if df['weight'].dtype in ['float64', 'int64']:
                if df['weight'].max() > 1:
                    df['weight'] = df['weight'] / 100
            elif df['weight'].dtype == 'object':
                # 字符串格式，如 "5.23%" 或 "5.23"
                df['weight'] = df['weight'].astype(str).str.replace('%', '', regex=False)
                df['weight'] = pd.to_numeric(df['weight'], errors='coerce')
                if df['weight'].max() > 1:
                    df['weight'] = df['weight'] / 100
        else:
            # 尝试找其他可能的占比列
            for col in df.columns:
                if '比例' in col or '占比' in col:
                    df['weight'] = pd.to_numeric(df[col], errors='coerce')
                    if df['weight'].max() > 1:
                        df['weight'] = df['weight'] / 100
                    break
        
        # 添加基金代码列
        df['fund_code'] = fund_code
        
        # 尝试获取基金名称
        try:
            fund_info = ak.fund_individual_basic_info_xq(symbol=fund_code)
            if fund_info is not None and not fund_info.empty:
                if '基金简称' in fund_info.columns:
                    df['fund_name'] = fund_info['基金简称'].iloc[0]
                elif 'name' in fund_info.columns:
                    df['fund_name'] = fund_info['name'].iloc[0]
                else:
                    df['fund_name'] = fund_code
            else:
                df['fund_name'] = fund_code
        except Exception:
            df['fund_name'] = fund_code
        
        # 过滤掉权重为空的记录
        if 'weight' in df.columns:
            df = df.dropna(subset=['weight'])
            df = df[df['weight'] > 0]
        
        return df
    
    def get_multiple_funds_holdings(self, fund_codes: List[str], 
                                     delay: float = 0.3,
                                     use_cache: bool = True) -> Dict[str, pd.DataFrame]:
        """
        批量获取多只基金的持仓数据
        
        参数:
            fund_codes: 基金代码列表
            delay: 请求间隔时间（秒），避免请求过于频繁
            use_cache: 是否使用缓存
            
        返回:
            字典，key为基金代码，value为持仓DataFrame
        """
        results = {}
        failed = []
        
        for i, code in enumerate(fund_codes, 1):
            print(f"[{i}/{len(fund_codes)}] 正在获取基金 {code} 的持仓数据...")
            holdings = self.get_fund_holdings(code, use_cache=use_cache)
            
            if holdings is not None and not holdings.empty:
                results[code] = holdings
            else:
                failed.append(code)
            
            # 添加延迟，避免请求过快
            if i < len(fund_codes):
                time.sleep(delay)
        
        print(f"\n成功: {len(results)} 只, 失败: {len(failed)} 只")
        if failed:
            print(f"失败的基金代码: {failed}")
        
        return results


# ==================== 第三部分：基金相似度计算 ====================

class FundSimilarityCalculator:
    """基金相似度计算类"""
    
    @staticmethod
    def build_holdings_matrix(holdings_dict: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """
        构建持仓矩阵（基金 × 股票）
        
        参数:
            holdings_dict: get_multiple_funds_holdings返回的字典
            
        返回:
            DataFrame，行为基金，列为股票代码，值为持仓占比
        """
        all_stocks = set()
        fund_data = {}
        
        for fund_code, df in holdings_dict.items():
            stocks = {}
            
            # 确定列名
            code_col = 'stock_code' if 'stock_code' in df.columns else df.columns[0]
            weight_col = 'weight' if 'weight' in df.columns else df.columns[2] if len(df.columns) > 2 else df.columns[1]
            
            for _, row in df.iterrows():
                stock_code = row[code_col]
                # 确保股票代码不为空
                if pd.isna(stock_code) or str(stock_code).strip() == '':
                    continue
                    
                weight = row[weight_col] if weight_col in row else 0
                if isinstance(weight, (int, float)) and weight > 1:
                    weight = weight / 100
                elif isinstance(weight, str):
                    try:
                        weight = float(weight.strip('%')) / 100
                    except:
                        weight = 0
                
                if weight > 0:
                    stocks[str(stock_code)] = weight
                    all_stocks.add(str(stock_code))
            
            if stocks:
                fund_data[fund_code] = stocks
        
        if not fund_data:
            return pd.DataFrame()
        
        # 构建矩阵
        matrix = []
        fund_names = list(fund_data.keys())
        all_stocks_list = sorted(list(all_stocks))
        
        for fund_code in fund_names:
            stocks = fund_data[fund_code]
            row = [stocks.get(stock, 0) for stock in all_stocks_list]
            matrix.append(row)
        
        df = pd.DataFrame(matrix, index=fund_names, columns=all_stocks_list)
        return df
    
    @staticmethod
    def calculate_jaccard_similarity(matrix: pd.DataFrame) -> pd.DataFrame:
        """计算Jaccard相似度"""
        if matrix.empty:
            return pd.DataFrame()
        
        n = len(matrix)
        similarity = np.zeros((n, n))
        
        for i in range(n):
            for j in range(n):
                set_i = set(matrix.columns[matrix.iloc[i] > 0])
                set_j = set(matrix.columns[matrix.iloc[j] > 0])
                if len(set_i | set_j) == 0:
                    similarity[i, j] = 0
                else:
                    similarity[i, j] = len(set_i & set_j) / len(set_i | set_j)
        
        return pd.DataFrame(similarity, index=matrix.index, columns=matrix.index)
    
    @staticmethod
    def calculate_cosine_similarity(matrix: pd.DataFrame) -> pd.DataFrame:
        """计算余弦相似度"""
        if matrix.empty:
            return pd.DataFrame()
        
        from sklearn.metrics.pairwise import cosine_similarity
        
        row_sums = matrix.values.sum(axis=1, keepdims=True)
        norm_matrix = matrix.values / (row_sums + 1e-10)
        similarity = cosine_similarity(norm_matrix)
        
        return pd.DataFrame(similarity, index=matrix.index, columns=matrix.index)
    
    @staticmethod
    def calculate_weighted_similarity(matrix: pd.DataFrame) -> pd.DataFrame:
        """计算加权相似度"""
        if matrix.empty:
            return pd.DataFrame()
        
        n = len(matrix)
        similarity = np.zeros((n, n))
        
        for i in range(n):
            for j in range(n):
                common = (matrix.iloc[i] > 0) & (matrix.iloc[j] > 0)
                if common.any():
                    sim = np.sum(np.minimum(matrix.iloc[i][common], matrix.iloc[j][common]))
                    similarity[i, j] = sim
                else:
                    similarity[i, j] = 0
        
        return pd.DataFrame(similarity, index=matrix.index, columns=matrix.index)
    
    @staticmethod
    def calculate_combined_similarity(matrix: pd.DataFrame, 
                                      weights: Dict[str, float] = None) -> pd.DataFrame:
        """计算综合相似度"""
        if matrix.empty:
            return pd.DataFrame()
        
        if weights is None:
            weights = {'jaccard': 0.3, 'cosine': 0.4, 'weighted': 0.3}
        
        jaccard = FundSimilarityCalculator.calculate_jaccard_similarity(matrix)
        cosine = FundSimilarityCalculator.calculate_cosine_similarity(matrix)
        weighted = FundSimilarityCalculator.calculate_weighted_similarity(matrix)
        
        # 归一化加权相似度
        max_val = weighted.max().max()
        if max_val > 0:
            weighted = weighted / max_val
        
        combined = weights['jaccard'] * jaccard + \
                   weights['cosine'] * cosine + \
                   weights['weighted'] * weighted
        
        return combined


# ==================== 第四部分：基金聚类分组 ====================

class FundCluster:
    """基金聚类分组类"""
    
    def __init__(self, similarity_matrix: pd.DataFrame):
        """初始化聚类器"""
        if similarity_matrix.empty:
            raise ValueError("相似度矩阵为空")
        
        self.similarity_matrix = similarity_matrix
        self.fund_names = similarity_matrix.index.tolist()
        
        # 转换为距离矩阵
        self.distance_matrix = 1 - similarity_matrix.values
        np.fill_diagonal(self.distance_matrix, 0)
        self.distance_matrix = (self.distance_matrix + self.distance_matrix.T) / 2
        self.distance_matrix = np.clip(self.distance_matrix, 0, 1)
    
    def hierarchical_cluster(self, threshold: float = 0.7, 
                             method: str = 'average') -> Dict:
        """层次聚类"""
        condensed_dist = squareform(self.distance_matrix, checks=False)
        self.linkage_matrix = linkage(condensed_dist, method=method)
        
        dist_threshold = 1 - threshold
        self.labels = fcluster(self.linkage_matrix, dist_threshold, criterion='distance')
        
        result = {'funds': {}}
        clusters = {}
        
        for i, (fund, label) in enumerate(zip(self.fund_names, self.labels)):
            label = int(label)
            if label not in clusters:
                clusters[label] = []
            clusters[label].append(fund)
            
            result['funds'][fund] = {
                'cluster': label,
                'index_in_similarity': i
            }
        
        result['clusters'] = {f'cluster_{k}': v for k, v in clusters.items()}
        result['num_clusters'] = len(clusters)
        result['threshold'] = threshold
        
        return result
    
    def get_cluster_summary(self, cluster_result: Dict, 
                            holdings_dict: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """获取聚类摘要"""
        summaries = []
        
        for cluster_name, funds in cluster_result['clusters'].items():
            all_holdings = {}
            
            for fund_code in funds:
                if fund_code in holdings_dict:
                    df = holdings_dict[fund_code]
                    name_col = 'stock_name' if 'stock_name' in df.columns else df.columns[1] if len(df.columns) > 1 else df.columns[0]
                    weight_col = 'weight' if 'weight' in df.columns else df.columns[2] if len(df.columns) > 2 else df.columns[1]
                    
                    for _, row in df.iterrows():
                        stock = row[name_col]
                        weight = row[weight_col]
                        if isinstance(weight, (int, float)) and weight > 1:
                            weight = weight / 100
                        
                        if stock not in all_holdings:
                            all_holdings[stock] = []
                        all_holdings[stock].append(weight)
            
            avg_holdings = {stock: np.mean(weights) for stock, weights in all_holdings.items()}
            top_stocks = sorted(avg_holdings.items(), key=lambda x: x[1], reverse=True)[:5]
            
            # 获取基金名称
            fund_names_with_names = []
            for f in funds[:5]:
                if f in holdings_dict and 'fund_name' in holdings_dict[f].columns:
                    name = holdings_dict[f].iloc[0].get('fund_name', f)
                    short_name = name[:12] + '...' if len(str(name)) > 12 else name
                    fund_names_with_names.append(f"{f}({short_name})")
                else:
                    fund_names_with_names.append(f)
            
            summaries.append({
                'cluster': cluster_name,
                'fund_count': len(funds),
                'funds': ', '.join(fund_names_with_names) + ('...' if len(funds) > 5 else ''),
                'top_holdings': ', '.join([f"{s}({w:.1%})" for s, w in top_stocks[:3]])
            })
        
        return pd.DataFrame(summaries)
    
    def plot_dendrogram(self, figsize: tuple = (12, 8), title: str = None):
        """绘制聚类树状图"""
        plt.figure(figsize=figsize)
        
        dendrogram(self.linkage_matrix, 
                   labels=self.fund_names,
                   leaf_rotation=90,
                   leaf_font_size=10)
        
        if title:
            plt.title(title, fontsize=14)
        plt.xlabel('基金', fontsize=12)
        plt.ylabel('距离 (1 - 相似度)', fontsize=12)
        plt.tight_layout()
        plt.show()
    
    def plot_similarity_heatmap(self, figsize: tuple = (10, 8), title: str = None):
        """绘制相似度热力图"""
        plt.figure(figsize=figsize)
        
        if hasattr(self, 'labels'):
            sorted_indices = np.argsort(self.labels)
            sorted_matrix = self.similarity_matrix.iloc[sorted_indices, sorted_indices]
        else:
            sorted_matrix = self.similarity_matrix
        
        plt.imshow(sorted_matrix.values, cmap='RdYlGn', aspect='auto', vmin=0, vmax=1)
        plt.colorbar(label='相似度')
        
        plt.xticks(range(len(sorted_matrix.index)), sorted_matrix.index, rotation=90, fontsize=8)
        plt.yticks(range(len(sorted_matrix.index)), sorted_matrix.index, fontsize=8)
        
        if title:
            plt.title(title, fontsize=14)
        plt.tight_layout()
        plt.show()


# ==================== 第五部分：主程序 ====================

def main():
    """主程序"""
    print("=" * 60)
    print("基金持仓分析工具 - AKShare版本")
    print("基于持仓相似度的基金聚类分组")
    print("=" * 60)
    
    # Step 1: 获取基金代码列表
    print("\n请选择基金代码来源：")
    print("1. 使用默认文件 fund_codes.txt")
    print("2. 指定其他txt文件路径")
    print("3. 创建模板文件")
    print("4. 手动输入基金代码")
    
    choice = input("\n请输入选择 (1/2/3/4): ").strip()
    
    fund_codes = []
    
    if choice == '3':
        FundCodeReader.create_template_file()
        print("\n请编辑 fund_codes.txt 文件，填入需要分析的基金代码后重新运行程序")
        return
    
    elif choice == '1':
        file_path = "fund_codes.txt"
        if not os.path.exists(file_path):
            print(f"文件 {file_path} 不存在，正在创建模板...")
            FundCodeReader.create_template_file(file_path)
            print("请编辑文件后重新运行程序")
            return
        fund_codes = FundCodeReader.read_from_txt(file_path)
        
    elif choice == '2':
        file_path = input("请输入txt文件路径: ").strip()
        fund_codes = FundCodeReader.read_from_txt(file_path)
        
    elif choice == '4':
        print("\n请输入基金代码（每行一个，输入空行结束）：")
        while True:
            code = input().strip()
            if not code:
                break
            # 提取6位数字
            import re
            match = re.search(r'\b\d{6}\b', code)
            if match:
                fund_codes.append(match.group())
            else:
                print(f"无效的基金代码: {code}")
    
    else:
        print("无效选择")
        return
    
    if not fund_codes:
        print("错误：没有找到有效的基金代码")
        return
    
    # 去重并保持顺序
    fund_codes = list(dict.fromkeys(fund_codes))
    print(f"\n共找到 {len(fund_codes)} 只基金：{fund_codes}")
    
    # Step 2: 获取持仓数据
    print("\n" + "-" * 40)
    print("开始获取基金持仓数据...")
    fetcher = FundDataFetcher(cache_enabled=True)
    holdings_dict = fetcher.get_multiple_funds_holdings(fund_codes, delay=0.3)
    
    if len(holdings_dict) < 2:
        print("错误：成功获取数据的基金不足2只，无法进行聚类分析")
        print("提示：请确保基金代码正确，且该基金有公开的持仓数据")
        return
    
    # Step 3: 展示各基金持仓概览
    print("\n" + "-" * 40)
    print("基金持仓概览：")
    for fund_code, df in holdings_dict.items():
        fund_name = df.iloc[0].get('fund_name', fund_code) if 'fund_name' in df.columns else fund_code
        report_date = df.iloc[0].get('report_date', '未知') if 'report_date' in df.columns else '未知'
        print(f"\n基金: {fund_code} - {fund_name}")
        print(f"报告期: {report_date}")
        print("前5大持仓:")
        
        name_col = 'stock_name' if 'stock_name' in df.columns else df.columns[1]
        weight_col = 'weight' if 'weight' in df.columns else df.columns[2]
        
        for idx, (_, row) in enumerate(df.head(5).iterrows()):
            stock_name = row[name_col]
            weight = row[weight_col]
            if isinstance(weight, (int, float)) and weight > 1:
                weight = weight / 100
            print(f"  {idx+1}. {stock_name}: {weight:.2%}")
    
    # Step 4: 构建持仓矩阵并计算相似度
    print("\n" + "-" * 40)
    print("计算基金持仓相似度...")
    matrix = FundSimilarityCalculator.build_holdings_matrix(holdings_dict)
    print(f"持仓矩阵维度: {matrix.shape} (基金数 × 股票数)")
    
    if matrix.empty:
        print("错误：无法构建有效的持仓矩阵")
        return
    
    similarity = FundSimilarityCalculator.calculate_combined_similarity(matrix)
    
    print("\n基金间综合相似度矩阵：")
    pd.set_option('display.precision', 3)
    print(similarity.round(3))
    
    # Step 5: 聚类分析
    print("\n" + "-" * 40)
    print("进行层次聚类分析...")
    
    # 自动选择最佳阈值
    thresholds = [0.5, 0.6, 0.7, 0.8, 0.85]
    best_result = None
    best_clusterer = None
    best_threshold = 0.7
    
    for threshold in thresholds:
        try:
            clusterer = FundCluster(similarity)
            result = clusterer.hierarchical_cluster(threshold=threshold, method='average')
            print(f"阈值 {threshold}: 聚类数量 = {result['num_clusters']}")
            
            # 选择聚类数量在2-8之间且最接近3-5的
            if 2 <= result['num_clusters'] <= 8:
                if best_result is None or abs(result['num_clusters'] - 4) < abs(best_result['num_clusters'] - 4):
                    best_result = result
                    best_clusterer = clusterer
                    best_threshold = threshold
        except Exception as e:
            print(f"阈值 {threshold} 聚类失败: {e}")
    
    if best_result is None:
        best_clusterer = FundCluster(similarity)
        best_result = best_clusterer.hierarchical_cluster(threshold=0.7, method='average')
        best_threshold = 0.7
    
    # Step 6: 输出聚类结果
    print("\n" + "=" * 60)
    print(f"聚类结果（使用相似度阈值 = {best_threshold}）")
    print("=" * 60)
    
    for cluster_name, funds in best_result['clusters'].items():
        print(f"\n【{cluster_name}】({len(funds)}只基金)")
        for fund in funds:
            if fund in holdings_dict and 'fund_name' in holdings_dict[fund].columns:
                name = holdings_dict[fund].iloc[0].get('fund_name', fund)
                print(f"  - {fund}: {name}")
            else:
                print(f"  - {fund}")
    
    # Step 7: 聚类摘要
    print("\n" + "-" * 40)
    print("聚类摘要（各聚类的代表性持仓）")
    summary = best_clusterer.get_cluster_summary(best_result, holdings_dict)
    print(summary.to_string(index=False))
    
    # Step 8: 可视化
    print("\n" + "-" * 40)
    visualize = input("是否生成可视化图表？(y/n): ").lower().strip()
    if visualize == 'y':
        best_clusterer.plot_dendrogram(title=f"基金持仓相似度聚类树状图 (阈值={best_threshold})")
        best_clusterer.plot_similarity_heatmap(title="基金持仓相似度热力图")
    
    # Step 9: 导出结果
    print("\n" + "-" * 40)
    export = input("是否导出结果到JSON文件？(y/n): ").lower().strip()
    if export == 'y':
        output = {
            'analysis_time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'funds_analyzed': list(holdings_dict.keys()),
            'similarity_threshold': best_threshold,
            'num_clusters': best_result['num_clusters'],
            'clusters': {
                cluster_name: funds 
                for cluster_name, funds in best_result['clusters'].items()
            },
            'similarity_matrix': similarity.round(4).to_dict()
        }
        
        with open('fund_cluster_result.json', 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print("结果已导出到 fund_cluster_result.json")
    
    print("\n分析完成！")


if __name__ == "__main__":
    main()