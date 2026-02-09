import os
import sys
import inspect
import importlib.util
import backtrader as bt

class StrategyLoader:
    def __init__(self, strategies_dir=None):
        if strategies_dir is None:
            # 默认指向 src/strategies
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.strategies_dir = os.path.join(root_dir, 'strategies')
        else:
            self.strategies_dir = strategies_dir
            
    def load_strategies(self):
        """
        扫描并返回所有可用策略及其参数元数据
        Returns:
            dict: { 'StrategyName': {'cls': Class, 'params': dict} }
        """
        strategies = {}
        
        # 确保目录在 sys.path 中
        if self.strategies_dir not in sys.path:
            sys.path.append(self.strategies_dir)
            
        for filename in os.listdir(self.strategies_dir):
            if filename.startswith("bt_strategy_") and filename.endswith(".py"):
                module_name = filename[:-3]
                file_path = os.path.join(self.strategies_dir, filename)
                
                try:
                    # 动态导入模块
                    spec = importlib.util.spec_from_file_location(module_name, file_path)
                    module = importlib.util.module_from_spec(spec)
                    # 关键：注册到 sys.modules，防止 pickle/Backtrader 内部查找失败
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)
                    
                    # 查找策略类
                    for name, obj in inspect.getmembers(module):
                        if inspect.isclass(obj) and issubclass(obj, bt.Strategy) and obj is not bt.Strategy:
                            # 过滤掉不应直接暴露的辅助策略
                            if name in ['MonitorStrategy']:
                                continue
                                
                            # 提取参数
                            params = self._extract_params(obj)
                            # 提取参数配置 (用于前端显示)
                            params_config = getattr(obj, 'params_config', {})
                            # 提取显示名称 (用于前端显示)
                            display_name = getattr(obj, 'display_name', name)
                            # 提取算法说明 (用于前端显示)
                            algo_description = getattr(obj, 'algo_description', None)
                            
                            strategies[name] = {
                                'cls': obj,
                                'module_path': file_path,
                                'params': params,
                                'params_config': params_config,
                                'display_name': display_name,
                                'algo_description': algo_description,
                                'doc': obj.__doc__ or "No description available."
                            }
                except Exception as e:
                    print(f"Error loading {filename}: {e}")
                    
        return strategies

    def _extract_params(self, strategy_cls):
        """
        提取策略类的默认参数
        """
        params = {}
        if hasattr(strategy_cls, 'params'):
            # Backtrader 的 params 通常是 tuple 或 dict
            # 但在类定义中，它会被处理为 metabase，我们需要访问 defaults
            # 直接访问 params 属性通常能拿到默认值 (如果是 tuple 形式的定义)
            # 或者通过 getattr 拿
            
            # 简单处理：实例化 params (如果是类属性)
            # 注意：Backtrader 的 params 处理比较黑魔法
            # 我们尝试直接读取 params._getdefaults() 如果可用，或者遍历
          if hasattr(strategy_cls, 'params'):
            raw_params = strategy_cls.params
            
            # 1. 尝试使用 Backtrader 提供的 _getitems 方法 (最可靠)
            if hasattr(raw_params, '_getitems'):
                try:
                    params = dict(raw_params._getitems())
                    return params
                except:
                    pass

            # 2. 原始字典
            if isinstance(raw_params, dict):
                params = raw_params
            elif isinstance(raw_params, (tuple, list)):
                # 处理 Backtrader 标准 tuple 定义: (('period', 20), ...)
                for item in raw_params:
                    if isinstance(item, (tuple, list)) and len(item) >= 2:
                        params[item[0]] = item[1]
            elif hasattr(raw_params, '_getdefaults'):
                 # 处理 Backtrader 的 Param 类
                 pass # TODO: 处理复杂情况
            else:
                # 尝试遍历 dir
                for key in dir(raw_params):
                    if not key.startswith('_'):
                        val = getattr(raw_params, key)
                        if not callable(val):
                            params[key] = val
                            
        return params

if __name__ == '__main__':
    loader = StrategyLoader()
    strats = loader.load_strategies()
    for name, info in strats.items():
        print(f"Found Strategy: {name}")
        print(f"  Params: {info['params']}")
