export async function fetchCandles(instId: string, limit: number = 500, timeframe: string = '1m') {
  const response = await fetch(`/api/candles?inst_id=${instId}&limit=${limit}&timeframe=${timeframe}`);
  if (!response.ok) {
    throw new Error('Failed to fetch candles');
  }
  const data = await response.json();
  // Backend now returns { candles: [], indicators: {} }
  // or it might return [] if I haven't deployed the backend change yet?
  // Let's handle both for robustness, though I know I updated the backend.
  
  let candles = [];
  let indicators = { main: [], sub: [] };

  if (Array.isArray(data)) {
      candles = data;
  } else {
      candles = data.candles || [];
      indicators = data.indicators || { main: [], sub: [] };
  }

  // Ensure data is sorted by time
  candles.sort((a: any, b: any) => a.time - b.time);
  
  return { candles, indicators };
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
