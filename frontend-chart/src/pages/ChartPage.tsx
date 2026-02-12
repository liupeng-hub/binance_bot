import { useParams } from 'react-router-dom';
import { ChartWidget } from '../components/ChartWidget';
import { useChartData } from '../hooks/useChartData';
import { useChartStore } from '../stores/chartStore';

export const ChartPage = () => {
  const { instId, symbol } = useParams<{ instId?: string; symbol?: string }>();
  const { theme, toggleTheme, timeframe, setTimeframe } = useChartStore();
  
  // Use either instId or symbol
  useChartData(instId || null, symbol || null);

  if (!instId && !symbol) {
    return <div className="p-4 text-red-500">Missing Instance ID or Symbol</div>;
  }

  return (
    <div className={`w-screen h-screen flex flex-col ${theme === 'dark' ? 'bg-[#1e1e1e]' : 'bg-white'}`}>
      {/* Minimal Header - Only Show Title */}
      <header className="h-8 border-b border-gray-700 flex items-center px-4 justify-between shrink-0 bg-[#131722]">
        <div className="flex items-center gap-2">
             <span className="text-xs font-bold text-[#2962FF]">TraeBot</span>
             <span className={`text-xs ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'}`}>
                {symbol ? `${symbol}` : `Instance: ${instId}`}
            </span>
        </div>
      </header>
      <div className="flex-1 min-h-0 relative">
         <ChartWidget />
      </div>
    </div>
  );
};
