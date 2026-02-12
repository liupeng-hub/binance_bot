export async function fetchCandles(instId: string | null, symbol: string | null, limit: number = 500, timeframe: string = '1m', indicators: any[] = []) {
  let url = `/api/candles?limit=${limit}&timeframe=${timeframe}`;
  if (instId) {
      url += `&inst_id=${instId}`;
  } else if (symbol) {
      url += `&symbol=${symbol}`;
  } else {
      throw new Error("Either instId or symbol must be provided");
  }
  
  if (indicators && indicators.length > 0) {
      url += `&indicators=${encodeURIComponent(JSON.stringify(indicators))}`;
  }

  const response = await fetch(url);
  if (!response.ok) {
    throw new Error('Failed to fetch candles');
  }
  const data = await response.json();
  // Backend now returns { candles: [], indicators: {} }
  // or it might return [] if I haven't deployed the backend change yet?
  // Let's handle both for robustness, though I know I updated the backend.
  
  let candles = [];
  let chartIndicators = { main: [], sub: [] };

  if (Array.isArray(data)) {
      candles = data;
  } else {
      candles = data.candles || [];
      chartIndicators = data.indicators || { main: [], sub: [] };
  }

  // Ensure data is sorted by time
  candles.sort((a: any, b: any) => a.time - b.time);
  
  return { candles, indicators: chartIndicators };
}

export async function fetchTrades(instId: string, limit: number = 100) {
    // Optional: Implement if backend supports trade history API
    try {
        const response = await fetch(`/api/trades?inst_id=${instId}&limit=${limit}`);
        if (!response.ok) return [];
        return await response.json();
    } catch (e) {
        console.warn("Fetch trades failed", e);
        return [];
    }
}
