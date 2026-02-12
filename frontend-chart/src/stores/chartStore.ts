import { create } from 'zustand';
import type { Candle, TradeMarker, Indicators } from '../types/api';

interface ChartState {
  candles: Candle[];
  markers: TradeMarker[];
  indicators: Indicators | null;
  selectedIndicators: any[]; // User selected indicators
  isLoading: boolean;
  error: string | null;
  theme: 'light' | 'dark';
  timeframe: string;
  setCandles: (candles: Candle[]) => void;
  updateCandle: (candle: Candle) => void;
  setMarkers: (markers: TradeMarker[]) => void;
  setIndicators: (indicators: Indicators) => void;
  updateIndicators: (newValues: Record<string, any>) => void;
  setSelectedIndicators: (inds: any[]) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  toggleTheme: () => void;
  setTimeframe: (tf: string) => void;
}

export const useChartStore = create<ChartState>((set) => ({
  candles: [],
  markers: [],
  indicators: null,
  selectedIndicators: [],
  isLoading: false,
  error: null,
  theme: 'dark',
  timeframe: '1m',
  setCandles: (candles) => set({ candles }),
  updateCandle: (candle) =>
    set((state) => {
      const lastCandle = state.candles[state.candles.length - 1];
      if (!lastCandle) return { candles: [candle] };

      if (candle.time === lastCandle.time) {
        // Update existing candle
        const newCandles = [...state.candles];
        newCandles[newCandles.length - 1] = candle;
        return { candles: newCandles };
      } else if (candle.time > lastCandle.time) {
        // Add new candle
        return { candles: [...state.candles, candle] };
      }
      return state;
    }),
  setMarkers: (markers) => set({ markers }),
  setIndicators: (indicators) => set({ indicators }),
  updateIndicators: (newValues) => 
      set((state) => {
          if (!state.indicators) return state;
          
          const newIndicators = { ...state.indicators };
          
          // Update Main Indicators
          if (newIndicators.main) {
              newIndicators.main = newIndicators.main.map((ind, i) => {
                  const key = `main-${i}`;
                  if (newValues[key]) {
                      const newData = [...ind.data];
                      const lastPoint = newValues[key];
                      
                      // Check if we should update last point or add new
                      const existingLast = newData[newData.length - 1];
                      if (existingLast && existingLast.time === lastPoint.time) {
                          newData[newData.length - 1] = lastPoint;
                      } else if (existingLast && lastPoint.time > existingLast.time) {
                          newData.push(lastPoint);
                      }
                      return { ...ind, data: newData };
                  }
                  return ind;
              });
          }
          
          // Update Sub Charts
          if (newIndicators.sub) {
              newIndicators.sub = newIndicators.sub.map((sub, i) => ({
                  ...sub,
                  series: sub.series.map((ser, j) => {
                      const key = `sub-${i}-${j}`;
                      if (newValues[key]) {
                          const newData = [...ser.data];
                          const lastPoint = newValues[key];
                          
                          const existingLast = newData[newData.length - 1];
                          if (existingLast && existingLast.time === lastPoint.time) {
                              newData[newData.length - 1] = lastPoint;
                          } else if (existingLast && lastPoint.time > existingLast.time) {
                              newData.push(lastPoint);
                          }
                          return { ...ser, data: newData };
                      }
                      return ser;
                  })
              }));
          }
          
          return { indicators: newIndicators };
      }),
  setSelectedIndicators: (inds) => set({ selectedIndicators: inds }),
  setLoading: (isLoading) => set({ isLoading }),
  setError: (error) => set({ error }),
  toggleTheme: () => set((state) => ({ theme: state.theme === 'light' ? 'dark' : 'light' })),
  setTimeframe: (tf) => set({ timeframe: tf }),
}));
