import { useEffect } from 'react';
import { useChartStore } from '../stores/chartStore';
import { fetchCandles, fetchTrades } from '../utils/http';
import { useWS } from './useWS';

export function useChartData(instId: string) {
  const { setCandles, setMarkers, setIndicators, setLoading, setError, timeframe } = useChartStore();

  useEffect(() => {
    let mounted = true;

    async function loadData() {
      if (!instId) return;
      setLoading(true);
      setError(null);
      
      // Clear existing data when switching timeframe (optional but cleaner)
      setCandles([]); 
      
      try {
        const [chartData, tradesData] = await Promise.all([
            fetchCandles(instId, 1000, timeframe), // Pass timeframe
            fetchTrades(instId, 100)    // Get recent trades
        ]);
        
        if (mounted) {
          setCandles(chartData.candles);
          setIndicators(chartData.indicators);
          
          // Convert trades to markers
          const markers = tradesData.map((t: any) => {
             // 规范化颜色和形状
             const isBuy = t.side === 'BUY' || t.side === 'LONG';
             const isSell = t.side === 'SELL' || t.side === 'SHORT';
             
             let color = '#2962FF'; // Default Blue
             let shape = 'circle';
             let position = 'inBar';
             
             if (isBuy) {
                 color = '#00C853'; // Green A700
                 shape = 'arrowUp';
                 position = 'belowBar';
             } else if (isSell) {
                 color = '#D50000'; // Red A700
                 shape = 'arrowDown';
                 position = 'aboveBar';
             } else {
                 // Close / Other
                 color = '#FFD600'; // Yellow A700
                 shape = 'circle';
                 position = 'aboveBar';
             }

             return {
                 time: t.time,
                 position: position,
                 color: color,
                 shape: shape,
                 text: `${t.side} ${t.price}`
             };
          });
          setMarkers(markers);
        }
      } catch (err) {
        if (mounted) {
          console.error(err);
          setError('Failed to load chart data');
        }
      } finally {
        if (mounted) setLoading(false);
      }
    }

    loadData();

    return () => {
      mounted = false;
    };
  }, [instId, timeframe, setCandles, setMarkers, setIndicators, setLoading, setError]); // Add timeframe dependency

  // Enable WebSocket
  useWS(instId);
}
