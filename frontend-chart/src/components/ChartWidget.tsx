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
  const volumeSeriesRef = useRef<any>(null); // Volume Series
  const indicatorSeriesRef = useRef<any[]>([]); // Main chart overlays
  const subChartSeriesRef = useRef<any[][]>([]); // Sub chart series groups

  const { candles, markers, indicators, theme, isLoading, timeframe, setTimeframe, selectedIndicators, setSelectedIndicators, toggleTheme } = useChartStore();
  const [hiddenIndicators, setHiddenIndicators] = useState<string[]>([]);
  const [showIndMenu, setShowIndMenu] = useState(false);
  const [configModal, setConfigModal] = useState<any>(null); // Store the indicator being configured

  const handleCustomTf = (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter') {
          const val = e.currentTarget.value.trim();
          if (val) setTimeframe(val);
      }
  };

  // Available Indicators
  const availableIndicators = [
      { type: 'SMA', label: 'SMA (Simple Moving Average)', default: { type: 'SMA', period: 20, color: '#2962FF' }, params: [{name: 'period', type: 'number', label: 'Length'}, {name: 'color', type: 'color', label: 'Color'}] },
      { type: 'EMA', label: 'EMA (Exponential Moving Average)', default: { type: 'EMA', period: 20, color: '#FF6D00' }, params: [{name: 'period', type: 'number', label: 'Length'}, {name: 'color', type: 'color', label: 'Color'}] },
      { type: 'BBands', label: 'Bollinger Bands', default: { type: 'BBands', period: 20, dev: 2 }, params: [{name: 'period', type: 'number', label: 'Length'}, {name: 'dev', type: 'number', step: 0.1, label: 'StdDev'}] },
      { type: 'RSI', label: 'RSI (Relative Strength Index)', default: { type: 'RSI', period: 14 }, params: [{name: 'period', type: 'number', label: 'Length'}] },
      { type: 'MACD', label: 'MACD', default: { type: 'MACD', fast: 12, slow: 26, signal: 9 }, params: [{name: 'fast', type: 'number', label: 'Fast'}, {name: 'slow', type: 'number', label: 'Slow'}, {name: 'signal', type: 'number', label: 'Signal'}] },
      { type: 'KDJ', label: 'KDJ', default: { type: 'KDJ' }, params: [] },
  ];

  const handleMenuClick = (indDef: any) => {
      setConfigModal({ ...indDef.default, _def: indDef }); // Copy default values and ref to definition
      setShowIndMenu(false);
  };

  const confirmAddIndicator = () => {
      if (!configModal) return;
      // Remove internal keys
      const { _def, ...cleanConfig } = configModal;
      
      // Check duplicate? Allow multiples with different params
      // Just append
      setSelectedIndicators([...selectedIndicators, cleanConfig]);
      setConfigModal(null);
  };

  const removeIndicator = (index: number) => {
      setSelectedIndicators(selectedIndicators.filter((_, i) => i !== index));
  };
  
  const subChartsData = indicators?.sub || [];

  // Toggle Indicator Visibility
  const toggleIndicator = (id: string) => {
      setHiddenIndicators((prev: string[]) => 
          prev.includes(id) ? prev.filter((x: string) => x !== id) : [...prev, id]
      );
  };
  
  // Calculate a structure signature to detect layout changes
  const structureSignature = useMemo(() => {
      if (!indicators) return '';
      const mainSig = indicators.main?.map((i: any) => i.type + (i.options.title || '')).join(',') || '';
      const subSig = indicators.sub?.map((s: any) => s.series.map((ss: any) => ss.type + (ss.options.title || '')).join(',')).join('|') || '';
      return mainSig + '|' + subSig;
  }, [indicators]);

  // Apply Visibility Effect
  useEffect(() => {
     // ... (same as before)
     // Main Indicators
     indicatorSeriesRef.current.forEach((series, index) => {
         const id = `main-${index}`;
         series.applyOptions({ visible: !hiddenIndicators.includes(id) });
     });
     
     // Sub Charts
     subChartSeriesRef.current.forEach((group, groupIndex) => {
         group.forEach((series, seriesIndex) => {
             // ...
             series.applyOptions({ visible: !hiddenIndicators.includes(`sub-${groupIndex}`) });
         });
     });
  }, [hiddenIndicators]);

  // 1. Initialize Charts Structure (Run only when structure changes)
  useEffect(() => {
    if (!chartContainerRef.current) return;
    if (!window.LightweightCharts) {
        console.error("LightweightCharts library not loaded");
        return;
    }

    const { createChart, ColorType, CrosshairMode, LineStyle } = window.LightweightCharts;

    // --- Helper to create options ---
    const getChartOptions = (container: HTMLElement) => ({
      layout: {
        background: { type: ColorType.Solid, color: theme === 'dark' ? '#131722' : '#ffffff' }, // 更深邃的背景
        textColor: theme === 'dark' ? '#d1d4dc' : '#333',
      },
      grid: {
        vertLines: { color: theme === 'dark' ? '#2B2B43' : '#F0F3FA', style: LineStyle.Dotted }, // 虚线网格
        horzLines: { color: theme === 'dark' ? '#2B2B43' : '#F0F3FA', style: LineStyle.Dotted },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: theme === 'dark' ? '#2B2B43' : '#D1D4DC',
      },
      rightPriceScale: {
        borderColor: theme === 'dark' ? '#2B2B43' : '#D1D4DC',
      },
      width: container.clientWidth,
      height: container.clientHeight,
    });

    // --- Create Main Chart ---
    const mainChart = createChart(chartContainerRef.current, getChartOptions(chartContainerRef.current));
    
    // Add Candlestick Series (Binance Style Colors)
    const candlestickSeries = mainChart.addCandlestickSeries({
        upColor: '#0ECB81',       // Binance Green
        downColor: '#F6465D',     // Binance Red
        borderVisible: false,
        wickUpColor: '#0ECB81',
        wickDownColor: '#F6465D',
    });
    candlestickSeriesRef.current = candlestickSeries;

    // Add Volume Series (Overlay at bottom)
    const volumeSeries = mainChart.addHistogramSeries({
        priceFormat: {
            type: 'volume',
        },
        priceScaleId: 'volume', // Independent scale
    });
    volumeSeriesRef.current = volumeSeries;
    
    // Configure volume scale margins
    mainChart.priceScale('volume').applyOptions({
        scaleMargins: {
            top: 0.85, // Volume occupies bottom 15%
            bottom: 0,
        },
        visible: false, // Hide volume axis
    });

    // Add Main Overlays (Indicators) - Create Series Objects ONLY
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
                // Initial data set will happen in the Data Effect
                indicatorSeriesRef.current.push(series);
            }
        });
    }

    // --- Create Sub Charts ---
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
                seriesList.push(series);
            }
        });
        subChartSeriesRef.current.push(seriesList);
        subCharts.push(subChart);
    });

    // --- Sync Time Scales ---
    const allCharts = [mainChart, ...subCharts];
    chartsRef.current = allCharts;

    let isSyncing = false;
    allCharts.forEach((c1) => {
        c1.timeScale().subscribeVisibleLogicalRangeChange((range: any) => {
             if (isSyncing) return;
             isSyncing = true;
             allCharts.filter(c2 => c2 !== c1).forEach(c2 => {
                 c2.timeScale().setVisibleLogicalRange(range);
             });
             isSyncing = false;
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

    // Initial Data Fill (Important when re-creating chart due to structure change)
    if (candles.length > 0) {
        candlestickSeries.setData(candles);
        volumeSeries.setData(candles.map(c => ({
            time: c.time,
            value: c.volume,
            color: c.close >= c.open ? 'rgba(14, 203, 129, 0.3)' : 'rgba(246, 70, 93, 0.3)',
        })));
        if (markers.length > 0) {
             candlestickSeries.setMarkers(markers);
        }
    }
    
    // Also fill indicators if available
    if (indicators) {
         if (indicators.main) {
             indicatorSeriesRef.current.forEach((series, i) => {
                 const data = indicators.main[i]?.data;
                 if (data) series.setData(data);
             });
         }
         if (indicators.sub) {
             subChartSeriesRef.current.forEach((group, i) => {
                 group.forEach((series, j) => {
                     const data = indicators.sub[i]?.series[j]?.data;
                     if (data) series.setData(data);
                 });
             });
         }
    }

    return () => {
      window.removeEventListener('resize', handleResize);
      allCharts.forEach(c => c.remove());
      chartsRef.current = [];
      candlestickSeriesRef.current = null;
      indicatorSeriesRef.current = [];
      subChartSeriesRef.current = [];
    };
  }, [structureSignature, subChartsData.length, theme]); // Depend on structure, not data

  // 2. Update Indicator Data (Run when data changes)
  useEffect(() => {
      if (!indicators) return;

      // Update Main Indicators
      if (indicators.main && indicatorSeriesRef.current.length === indicators.main.length) {
          indicators.main.forEach((ind: any, i: number) => {
              const series = indicatorSeriesRef.current[i];
              if (series) {
                  // Use setData for now. To optimize, we'd need prevData logic here too.
                  // But since indicators usually update with candles, resetting them might be ok
                  // IF the main chart timeScale is what holds the view.
                  // HOWEVER, calling setData on overlay might not reset view if main series doesn't.
                  series.setData(ind.data);
              }
          });
      }

      // Update Sub Charts
      if (indicators.sub && subChartSeriesRef.current.length === indicators.sub.length) {
          indicators.sub.forEach((sub: any, i: number) => {
              const group = subChartSeriesRef.current[i];
              if (group && group.length === sub.series.length) {
                  sub.series.forEach((s: any, j: number) => {
                      const series = group[j];
                      if (series) {
                          series.setData(s.data);
                      }
                  });
              }
          });
      }
  }, [indicators]);

  // Update Theme (unchanged)
  useEffect(() => {
    // ...
  }, [theme]);

  // Update Candle Data (Optimized for Incremental Updates)
  const prevCandlesRef = useRef<any[]>([]);
  
  useEffect(() => {
    if (!candlestickSeriesRef.current || !volumeSeriesRef.current || candles.length === 0) return;
    
    const prevCandles = prevCandlesRef.current;
    const lastCandle = candles[candles.length - 1];
    const prevLastCandle = prevCandles.length > 0 ? prevCandles[prevCandles.length - 1] : null;
    
    let isIncremental = false;
    
    if (prevCandles.length > 0) {
        // Case 1: Same length, last candle updated (Real-time tick)
        if (candles.length === prevCandles.length && lastCandle.time === prevLastCandle.time) {
            isIncremental = true;
        }
        // Case 2: New candle added (Real-time bar close)
        else if (candles.length === prevCandles.length + 1 && lastCandle.time > prevLastCandle.time) {
            isIncremental = true;
        }
    }
    
    // Helper to format volume item
    const formatVolume = (c: any) => ({
        time: c.time,
        value: c.volume,
        color: c.close >= c.open ? 'rgba(14, 203, 129, 0.3)' : 'rgba(246, 70, 93, 0.3)',
    });

    if (isIncremental) {
        // Use update() to preserve scroll position
        candlestickSeriesRef.current.update(lastCandle);
        volumeSeriesRef.current.update(formatVolume(lastCandle));
    } else {
        // Full refresh (Load or Timeframe switch) - Use setData()
        candlestickSeriesRef.current.setData(candles);
        
        const volumeData = candles.map(formatVolume);
        volumeSeriesRef.current.setData(volumeData);
    }
    
    // Always update markers
    if (typeof candlestickSeriesRef.current.setMarkers === 'function') {
         candlestickSeriesRef.current.setMarkers(markers);
    }
    
    // Update ref
    prevCandlesRef.current = candles;
    
  }, [candles, markers]);

  return (
    <div className="flex flex-col w-full h-full bg-[#131722] overflow-hidden relative">
      {/* Top Toolbar (Fixed) */}
      <div className="flex items-center justify-between px-3 py-2 bg-[#1e222d] border-b border-[#2a2e39] shrink-0">
          
          {/* Left: Timeframe Selector */}
          <div className="flex gap-1 items-center">
              {['1m', '5m', '15m', '1h', '4h', '1d', '1w', '1M'].map(tf => (
                  <button 
                    key={tf}
                    className={`text-xs px-2 py-1 rounded transition-all ${
                        timeframe === tf 
                        ? 'bg-[#2962FF] text-white' 
                        : 'text-gray-400 hover:text-gray-200 hover:bg-[#2a2e39]'
                    }`}
                    onClick={() => setTimeframe(tf)}
                  >
                      {tf}
                  </button>
              ))}
              
              {/* Custom Timeframe Input */}
              <div className="flex items-center border border-gray-600 rounded px-1 ml-1 h-6">
                <input 
                    type="text" 
                    placeholder="Custom" 
                    className="w-10 bg-transparent text-xs border-none outline-none text-gray-300 placeholder-gray-600"
                    onKeyDown={handleCustomTf}
                />
            </div>
          </div>
          
          {/* Right: Indicators & Status */}
          <div className="flex items-center gap-3">
              
              {/* Theme Toggle */}
              <button 
                onClick={toggleTheme}
                className="text-xs px-2 py-1 rounded bg-[#2a2e39] text-gray-400 hover:text-white hover:bg-[#363a45]"
                title="Toggle Theme"
              >
                {theme === 'dark' ? '☀️' : '🌙'}
              </button>

              {/* Add Indicator Menu */}
              <div className="relative">
                  <button 
                      className="text-xs px-2 py-1 rounded bg-[#2a2e39] text-gray-200 hover:bg-[#363a45] flex items-center gap-1"
                      onClick={() => setShowIndMenu(!showIndMenu)}
                  >
                      ➕ Indicators
                  </button>
                  
                  {showIndMenu && (
                      <div className="absolute top-full right-0 mt-1 w-40 bg-[#1e222d] border border-[#2a2e39] rounded shadow-lg z-50">
                          {availableIndicators.map(ind => (
                              <button
                                  key={ind.type}
                                  className="w-full text-left px-3 py-2 text-xs text-gray-300 hover:bg-[#2a2e39]"
                                  onClick={() => handleMenuClick(ind)}
                              >
                                  {ind.label}
                              </button>
                          ))}
                      </div>
                  )}
              </div>

              {/* Indicator Config Modal */}
              {configModal && (
                  <div className="fixed inset-0 bg-black/50 z-[100] flex items-center justify-center">
                      <div className="bg-[#1e222d] border border-[#2a2e39] rounded shadow-lg p-4 w-64">
                          <h3 className="text-sm font-medium text-gray-200 mb-3">{configModal._def?.label}</h3>
                          
                          <div className="space-y-3">
                              {configModal._def?.params.map((p: any) => (
                                  <div key={p.name} className="flex flex-col gap-1">
                                      <label className="text-xs text-gray-400">{p.label}</label>
                                      {p.type === 'color' ? (
                                          <input 
                                              type="color" 
                                              value={configModal[p.name]} 
                                              onChange={e => setConfigModal({...configModal, [p.name]: e.target.value})}
                                              className="h-6 w-full cursor-pointer bg-transparent"
                                          />
                                      ) : (
                                          <input 
                                              type="number" 
                                              step={p.step || 1}
                                              value={configModal[p.name]} 
                                              onChange={e => setConfigModal({...configModal, [p.name]: parseFloat(e.target.value)})}
                                              className="bg-[#2a2e39] border border-gray-600 rounded px-2 py-1 text-xs text-gray-200 focus:border-blue-500 outline-none"
                                          />
                                      )}
                                  </div>
                              ))}
                              {(!configModal._def?.params || configModal._def?.params.length === 0) && (
                                  <div className="text-xs text-gray-500 italic">No parameters</div>
                              )}
                          </div>

                          <div className="flex gap-2 mt-4 justify-end">
                              <button 
                                  onClick={() => setConfigModal(null)}
                                  className="px-3 py-1.5 text-xs rounded text-gray-400 hover:text-gray-200"
                              >
                                  Cancel
                              </button>
                              <button 
                                  onClick={confirmAddIndicator}
                                  className="px-3 py-1.5 text-xs rounded bg-[#2962FF] text-white hover:bg-blue-600"
                              >
                                  Add
                              </button>
                          </div>
                      </div>
                  </div>
              )}

              {isLoading && (
                  <div className="flex items-center gap-2 text-xs text-gray-400">
                      <div className="w-3 h-3 rounded-full border-2 border-gray-500 border-t-transparent animate-spin"></div>
                      Syncing...
                  </div>
              )}
              
              {/* Indicator Toggles (Simplified Dropdown/List) */}
              <div className="flex gap-2">
                {indicators?.main?.map((ind: any, i: number) => (
                    <div key={`main-${i}`} className="flex items-center rounded border border-gray-600 bg-[#2a2e39] overflow-hidden">
                        <button 
                            onClick={() => toggleIndicator(`main-${i}`)}
                            className={`text-xs flex items-center gap-1.5 px-2 py-1 ${
                                hiddenIndicators.includes(`main-${i}`) 
                                ? 'opacity-50' 
                                : ''
                            }`}
                            title={ind.options.title || `Indicator ${i+1}`}
                        >
                            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: ind.options.color }}></span>
                            <span className="max-w-[60px] truncate text-gray-200">{ind.options.title || `Ind ${i+1}`}</span>
                        </button>
                        <button
                             onClick={() => removeIndicator(i)}
                             className="px-1.5 py-1 text-gray-400 hover:text-red-400 hover:bg-black/20 text-xs border-l border-gray-600"
                             title="Remove"
                        >
                             ✕
                        </button>
                    </div>
                ))}
              </div>
          </div>
      </div>

      {/* Main Chart Area */}
      <div className="relative flex-1 min-h-0">
          <div ref={chartContainerRef} className="absolute inset-0" />
      </div>
      
      {/* Sub Charts Area */}
      {subChartsData.map((sub, index) => (
          <div 
            key={index} 
            className="w-full border-t border-[#2a2e39] relative flex flex-col"
          >
            {/* Subchart Header (Mini Toolbar) */}
            <div className="absolute top-0 left-0 z-10 px-2 py-1 pointer-events-none">
                <span className="text-[10px] text-gray-500 font-mono">
                    {sub.series[0]?.type} (Sub {index+1})
                </span>
            </div>
            
            <div 
                ref={(el) => { subChartContainersRef.current[index] = el; }}
                style={{ height: sub.height || 150 }}
                className="w-full"
            />
          </div>
      ))}
    </div>
  );
};
