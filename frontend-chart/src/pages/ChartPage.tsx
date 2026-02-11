import { useParams } from 'react-router-dom';
import { ChartWidget } from '../components/ChartWidget';
import { useChartData } from '../hooks/useChartData';
import { useChartStore } from '../stores/chartStore';

export const ChartPage = () => {
  const { instId } = useParams<{ instId: string }>();
  const { theme, toggleTheme } = useChartStore();

  useChartData(instId || '');

  if (!instId) {
    return <div className="p-4 text-red-500">Missing Instance ID</div>;
  }

  return (
    <div className={`w-screen h-screen flex flex-col ${theme === 'dark' ? 'bg-[#1e1e1e]' : 'bg-white'}`}>
      <header className="h-12 border-b border-gray-700 flex items-center px-4 justify-between shrink-0">
        <h1 className={`text-sm font-medium ${theme === 'dark' ? 'text-gray-200' : 'text-gray-800'}`}>
           Instance: {instId}
        </h1>
        <button 
           onClick={toggleTheme}
           className="px-3 py-1 text-xs rounded bg-blue-600 text-white hover:bg-blue-700"
        >
           {theme === 'dark' ? 'Light' : 'Dark'} Mode
        </button>
      </header>
      <div className="flex-1 min-h-0">
         <ChartWidget />
      </div>
    </div>
  );
};
