import { useEffect, useRef, useMemo, useState } from 'react';
import { useChartStore } from '../stores/chartStore';

// Declare the global LightweightCharts object
declare global {
  interface Window {
    LightweightCharts: any;
  }
}

export const ChartWidget = () => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const subChartContainersRef = useRef<(HTMLDivElement | null)[]>([]);
  
  // Keep track of chart instances and series
  const chartsRef = useRef<any[]>([]); 
  const candlestickSeriesRef = useRef<any>(null);
  const indicatorSeriesRef = useRef<any[]>([]); // Main chart overlays
  const subChartSeriesRef = useRef<any[][]>([]); // Sub chart series groups

  const { candles, markers, indicators, theme, isLoading, timeframe, setTimeframe } = useChartStore();
  const [hiddenIndicators, setHiddenIndicators] = useState<string[]>([]);
  // timeframe state is now in store

  const subChartsData = indicators?.sub || [];

  // Toggle Indicator Visibility
  const toggleIndicator = (id: string) => {
      setHiddenIndicators((prev: string[]) => 
          prev.includes(id) ? prev.filter((x: string) => x !== id) : [...prev, id]
      );
  };
  
  // Apply Visibility Effect
  useEffect(() => {
     // Main Indicators
     indicatorSeriesRef.current.forEach((series, index) => {
         const id = `main-${index}`;
         series.applyOptions({ visible: !hiddenIndicators.includes(id) });
     });
     
     // Sub Charts
     subChartSeriesRef.current.forEach((group, groupIndex) => {
         group.forEach((series, seriesIndex) => {
             const id = `sub-${groupIndex}-${seriesIndex}`; // Simplified ID strategy
             // In reality, we might want to hide the whole subchart container, 
             // but lightweight-charts doesn't support "hiding" a chart easily without destroying it.
             // So we just hide the series.
             series.applyOptions({ visible: !hiddenIndicators.includes(`sub-${groupIndex}`) });
         });
     });
  }, [hiddenIndicators]);

  // Initialize Charts (Main + Subs)
  useEffect(() => {
    if (!chartContainerRef.current) return;
    if (!window.LightweightCharts) {
        console.error("LightweightCharts library not loaded");
        return;
    }

    const { createChart, ColorType, CrosshairMode } = window.LightweightCharts;

    // --- Helper to create options ---
    const getChartOptions = (container: HTMLElement) => ({
      layout: {
        background: { type: ColorType.Solid, color: theme === 'dark' ? '#1e1e1e' : '#ffffff' },
        textColor: theme === 'dark' ? '#d1d4dc' : '#333',
      },
      grid: {
        vertLines: { color: theme === 'dark' ? '#2B2B43' : '#F0F3FA' },
        horzLines: { color: theme === 'dark' ? '#2B2B43' : '#F0F3FA' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
      },
      width: container.clientWidth,
      height: container.clientHeight,
    });

    // --- 1. Create Main Chart ---
    const mainChart = createChart(chartContainerRef.current, getChartOptions(chartContainerRef.current));
    
    // Add Candlestick Series
    const candlestickSeries = mainChart.addCandlestickSeries({
        upColor: '#26a69a',
        downColor: '#ef5350',
        borderVisible: false,
        wickUpColor: '#26a69a',
        wickDownColor: '#ef5350',
    });
    candlestickSeriesRef.current = candlestickSeries;

    // Add Main Overlays (Indicators)
    indicatorSeriesRef.current = [];
    if (indicators?.main) {
        indicators.main.forEach((ind: any) => {
            let series;
            if (ind.type === 'Line') {
                series = mainChart.addLineSeries(ind.options);
            } else if (ind.type === 'Histogram') {
                series = mainChart.addHistogramSeries(ind.options);
            }
            if (series) {
                series.setData(ind.data);
                indicatorSeriesRef.current.push(series);
            }
        });
    }

    // --- 2. Create Sub Charts ---
    const subCharts: any[] = [];
    subChartSeriesRef.current = [];

    subChartsData.forEach((sub, index) => {
        const container = subChartContainersRef.current[index];
        if (!container) return;

        const subChart = createChart(container, {
            ...getChartOptions(container),
            height: sub.height || 150,
        });

        const seriesList: any[] = [];
        sub.series.forEach((s: any) => {
            let series;
            if (s.type === 'Line') {
                series = subChart.addLineSeries(s.options);
            } else if (s.type === 'Histogram') {
                series = subChart.addHistogramSeries(s.options);
            }
            if (series) {
                series.setData(s.data);
                seriesList.push(series);
            }
        });
        subChartSeriesRef.current.push(seriesList);
        subCharts.push(subChart);
    });

    // --- 3. Sync Time Scales ---
    const allCharts = [mainChart, ...subCharts];
    chartsRef.current = allCharts;

    // Use a flag to prevent infinite loops during sync
    let isSyncing = false;

    allCharts.forEach((c1) => {
        // Sync Logical Range (preferred for matching bars)
        c1.timeScale().subscribeVisibleLogicalRangeChange((range: any) => {
             if (isSyncing) return;
             isSyncing = true;
             
             allCharts.filter(c2 => c2 !== c1).forEach(c2 => {
                 c2.timeScale().setVisibleLogicalRange(range);
             });
             
             isSyncing = false;
        });
        
        // Also sync Crosshair position
        c1.subscribeCrosshairMove((param: any) => {
            const dataPoint = param.seriesData.get(candlestickSeries);
            // We can't easily sync crosshair across charts in Lightweight Charts v4 without custom overlay
            // But usually sharing time scale is enough for visual alignment.
        });
    });

    // Resize Observer
    const handleResize = () => {
        if (chartContainerRef.current) {
             mainChart.applyOptions({ 
                width: chartContainerRef.current.clientWidth,
                height: chartContainerRef.current.clientHeight
            });
        }
        subChartsData.forEach((_, index) => {
            const container = subChartContainersRef.current[index];
            const chart = subCharts[index];
            if (container && chart) {
                chart.applyOptions({
                    width: container.clientWidth,
                    height: container.clientHeight
                });
            }
        });
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      allCharts.forEach(c => c.remove());
      chartsRef.current = [];
    };
  }, [indicators, subChartsData.length]); // Re-create if indicators structure changes

  // Update Theme
  useEffect(() => {
    if (!window.LightweightCharts) return;
    const { ColorType } = window.LightweightCharts;
    
    chartsRef.current.forEach(chart => {
        chart.applyOptions({
            layout: {
                background: { type: ColorType.Solid, color: theme === 'dark' ? '#1e1e1e' : '#ffffff' },
                textColor: theme === 'dark' ? '#d1d4dc' : '#333',
            },
            grid: {
                vertLines: { color: theme === 'dark' ? '#2B2B43' : '#F0F3FA' },
                horzLines: { color: theme === 'dark' ? '#2B2B43' : '#F0F3FA' },
            },
        });
    });
  }, [theme]);

  // Update Candle Data
  useEffect(() => {
    if (!candlestickSeriesRef.current) return;
    candlestickSeriesRef.current.setData(candles);
    
    if (typeof candlestickSeriesRef.current.setMarkers === 'function') {
         candlestickSeriesRef.current.setMarkers(markers);
    }
  }, [candles, markers]);

  return (
    <div className="flex flex-col w-full h-full bg-[#1e1e1e] overflow-hidden relative">
      {/* Toolbar */}
      <div className="absolute top-2 left-2 z-20 flex gap-2 items-start pointer-events-none">
          {/* Timeframe Selector (Pointer events enabled for children) */}
          <div className="pointer-events-auto bg-[#2B2B43] rounded px-2 py-1 flex gap-1 shadow-lg">
              {['1m', '5m', '15m', '1h', '4h', '1d'].map(tf => (
                  <button 
                    key={tf}
                    className={`text-xs px-2 py-0.5 rounded ${timeframe === tf ? 'bg-[#2962FF] text-white' : 'text-gray-400 hover:text-white'}`}
                    onClick={() => {
                        setTimeframe(tf);
                        console.log("Switch Timeframe to", tf);
                    }}
                  >
                      {tf}
                  </button>
              ))}
          </div>
          
          {/* Indicators Legend */}
          <div className="pointer-events-auto flex flex-col gap-1">
              {/* Main Indicators Legend */}
              {indicators?.main?.map((ind: any, i: number) => (
                  <div key={`main-${i}`} className={`backdrop-blur-sm rounded px-2 py-1 flex items-center gap-2 text-xs text-white shadow-sm border transition-colors ${hiddenIndicators.includes(`main-${i}`) ? 'bg-gray-800/50 border-gray-700 opacity-60' : 'bg-[#2B2B43]/80 border-transparent'}`}>
                      <span className="w-2 h-2 rounded-full" style={{ backgroundColor: ind.options.color }}></span>
                      <span>{ind.options.title || `Indicator ${i+1}`}</span>
                      <button 
                        onClick={() => toggleIndicator(`main-${i}`)}
                        className="ml-1 hover:scale-110 transition-transform"
                      >
                          {hiddenIndicators.includes(`main-${i}`) ? '🔒' : '👁'}
                      </button>
                  </div>
              ))}
              
              {/* Sub Charts Legend (Simplified: 1 toggle per subchart) */}
              {subChartsData.map((_, i) => (
                  <div key={`sub-${i}`} className={`backdrop-blur-sm rounded px-2 py-1 flex items-center gap-2 text-xs text-white shadow-sm border transition-colors ${hiddenIndicators.includes(`sub-${i}`) ? 'bg-gray-800/50 border-gray-700 opacity-60' : 'bg-[#2B2B43]/80 border-transparent'}`}>
                      <span className="text-gray-300">SubChart {i+1}</span>
                      <button 
                        onClick={() => toggleIndicator(`sub-${i}`)}
                        className="ml-1 hover:scale-110 transition-transform"
                      >
                          {hiddenIndicators.includes(`sub-${i}`) ? '🔒' : '👁'}
                      </button>
                  </div>
              ))}
          </div>
      </div>

      {/* Main Chart - Flex Grow to fill space not taken by sub-charts */}
      <div className="relative flex-1 min-h-0">
          <div ref={chartContainerRef} className="absolute inset-0" />
          {isLoading && (
             <div className="absolute inset-0 flex items-center justify-center bg-black/50 z-10">
                 <span className="text-white">Loading...</span>
             </div>
          )}
      </div>
      
      {/* Sub Charts - Fixed Height */}
      {subChartsData.map((sub, index) => (
          <div 
            key={index} 
            ref={(el) => { subChartContainersRef.current[index] = el; }}
            style={{ height: sub.height || 150 }}
            className="w-full border-t border-gray-700 relative"
          />
      ))}
    </div>
  );
};
