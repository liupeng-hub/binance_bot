import argparse
import sys
import os
import json
from multiprocessing import Process

# Add the current directory to sys.path to allow imports from modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.bot_realtime import BotRealtime
from core.bot_gridmaker import BotGridMaker

def find_strategy_path(symbol, strategy_type):
    """Find the specific strategy file path"""
    base_dir = os.path.join(os.path.dirname(__file__), "strategies")
    # Expected path: strategies/{strategy_type}/{symbol}_{strategy_type}.json
    
    path = os.path.join(base_dir, strategy_type, f"{symbol}_{strategy_type}.json")
    if os.path.exists(path):
        return path
    
    # Fallback search
    for root, _, files in os.walk(base_dir):
        for f in files:
            if f.endswith(".json") and symbol in f and strategy_type in f:
                return os.path.join(root, f)
    return None

def start_bot_process(bot_class, config_path):
    """Helper to start a bot in a separate process"""
    try:
        bot = bot_class(config_path)
        bot.start() 
    except Exception as e:
        print(f"❌ Bot process failed: {e}")

def run_from_config(config_path):
    """Run bots based on a JSON configuration file"""
    if not os.path.exists(config_path):
        print(f"❌ Run config file not found: {config_path}")
        return

    with open(config_path, 'r', encoding='utf-8') as f:
        run_config = json.load(f)

    processes = []
    
    # Mapping of bot names to classes
    bot_map = {
        "bot_realtime": BotRealtime,
        "bot_gridmaker": BotGridMaker
    }

    print(f"🚀 Starting bots from config: {config_path}")

    for bot_name, strategies in run_config.items():
        if bot_name not in bot_map:
            print(f"⚠️ Unknown bot type: {bot_name}, skipping...")
            continue
            
        BotClass = bot_map[bot_name]
        
        for strategy_type, symbols in strategies.items():
            for symbol in symbols:
                # Find the strategy config file
                strategy_path = find_strategy_path(symbol, strategy_type)
                
                if strategy_path:
                    print(f"   ▶️ Launching {bot_name} | {symbol} | {strategy_type}")
                    p = Process(target=start_bot_process, args=(BotClass, strategy_path))
                    p.start()
                    processes.append(p)
                else:
                    print(f"   ⚠️ Strategy config not found for {symbol} ({strategy_type})")

    if processes:
        print(f"\n✅ {len(processes)} bots running in background. Press Ctrl+C to stop manager (bots will continue if detached, or kill manually).")
        try:
            for p in processes:
                p.join()
        except KeyboardInterrupt:
            print("\n🛑 Stopping all bots...")
            for p in processes:
                p.terminate()
    else:
        print("⚠️ No bots started.")

def run_single_bot(target_input):
    """
    Run bots for a single symbol, a list of symbols, or a config file.
    Default strategy: Amplitude Distribution (BotRealtime)
    """
    
    # 1. Check if it's a JSON config file
    if target_input.endswith(".json") and os.path.exists(target_input):
        try:
            with open(target_input, 'r') as f:
                content = json.load(f)
                if "bot_realtime" in content or "bot_gridmaker" in content:
                    run_from_config(target_input)
                    return
        except:
            pass
        # If it's a strategy config file, run it directly
        print(f"🚀 Launching single bot from config: {target_input}")
        bot = BotRealtime(target_input)
        bot.start()
        return

    # 2. Treat as comma-separated symbols
    symbols = [s.strip() for s in target_input.split(",")]
    
    if len(symbols) == 1:
        # Single symbol run (Main process)
        symbol = symbols[0]
        config_path = find_best_strategy(symbol)
        if config_path:
            print(f"🚀 Launching BotRealtime for {symbol}...")
            bot = BotRealtime(config_path)
            bot.start()
        else:
            print(f"❌ No strategy found for {symbol}. Please run 'python run_strategy_gen.py --symbols {symbol}' first.")
            
    else:
        # Multiple symbols run (Multi-process)
        print(f"🚀 Launching bots for {len(symbols)} symbols: {symbols}")
        processes = []
        for symbol in symbols:
            config_path = find_best_strategy(symbol)
            if config_path:
                print(f"   ▶️ Launching BotRealtime | {symbol}")
                p = Process(target=start_bot_process, args=(BotRealtime, config_path))
                p.start()
                processes.append(p)
            else:
                print(f"   ⚠️ No strategy found for {symbol}")
                
        if processes:
            print(f"\n✅ {len(processes)} bots running in background.")
            try:
                for p in processes:
                    p.join()
            except KeyboardInterrupt:
                print("\n🛑 Stopping all bots...")
                for p in processes:
                    p.terminate()

def find_best_strategy(symbol):
    """Helper to find the best available strategy (Amplitude Distribution preferred)"""
    strategies_dir = os.path.join(os.path.dirname(__file__), "strategies")
    candidates = []
    
    # Search recursively
    for root, _, files in os.walk(strategies_dir):
        for f in files:
            if f.endswith(".json") and symbol in f:
                candidates.append(os.path.join(root, f))
                
    if not candidates:
        return None
        
    # Prefer amplitude_distribution
    amp_configs = [c for c in candidates if "amplitude_distribution" in c]
    if amp_configs:
        return max(amp_configs, key=os.path.getmtime)
    
    return max(candidates, key=os.path.getmtime)

def main():
    parser = argparse.ArgumentParser(description="Run Binance Trading Bot")
    parser.add_argument("target", type=str, help="Symbol(s) (comma-separated), Strategy Config Path, or Run Config JSON")
    
    args = parser.parse_args()
    run_single_bot(args.target)

if __name__ == "__main__":
    main()
