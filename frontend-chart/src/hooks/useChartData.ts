import { useEffect } from 'react';
import { useChartStore } from '../stores/chartStore';
import { fetchCandles, fetchTrades } from '../utils/http';
import { useWS } from './useWS';

export function useChartData(instId: string | null, symbol: string | null) {
  const { setCandles, setMarkers, setIndicators, setLoading, setError, timeframe, selectedIndicators } = useChartStore();

  useEffect(() => {
    let mounted = true;

    async function loadData() {
      if (!instId && !symbol) return;
      setLoading(true);
      setError(null);
      
      // Clear existing data when switching timeframe (optional but cleaner)
      setCandles([]); 
      
      try {
        const promises: Promise<any>[] = [
            fetchCandles(instId, symbol, 1000, timeframe, selectedIndicators)
        ];
        
        if (instId) {
            promises.push(fetchTrades(instId, 100));
        }

        const [chartData, tradesData] = await Promise.all(promises);
        
        if (mounted) {
          setCandles(chartData.candles);
          setIndicators(chartData.indicators);
          
          if (tradesData) {
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
          } else {
              setMarkers([]);
          }
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
  }, [instId, symbol, timeframe, selectedIndicators, setCandles, setMarkers, setIndicators, setLoading, setError]);

  // Enable WebSocket
  useWS(instId); // Only connect if instId is present for now
}
