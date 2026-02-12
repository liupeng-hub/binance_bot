import { useEffect, useRef, useCallback } from 'react';
import { useChartStore } from '../stores/chartStore';

export function useWS(instId: string | null) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null); // Use number for browser environment
  const updateCandle = useChartStore((state) => state.updateCandle);
  const updateIndicators = useChartStore((state) => state.updateIndicators);

  const connect = useCallback(() => {
    if (!instId) return; // Guard
    
    // Avoid multiple connections
    if (wsRef.current?.readyState === WebSocket.OPEN || wsRef.current?.readyState === WebSocket.CONNECTING) {
        return;
    }

    const wsUrl = `ws://localhost:8000/ws/candles/${instId}`;
    console.log('Connecting to WS:', wsUrl);
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log('WS Connected');
      if (reconnectTimeoutRef.current) {
        window.clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
    };

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        if (message.type === 'candle') {
          updateCandle(message.data);
          if (message.data.indicators) {
            updateIndicators(message.data.indicators);
          }
        } else if (message.type === 'heartbeat') {
          // console.debug('Heartbeat received');
        }
      } catch (e) {
        console.error('WS Parse Error', e);
      }
    };

    ws.onclose = () => {
       console.log('WS Closed');
       wsRef.current = null;
       // Only reconnect if the component is still mounted (how to check? useEffect cleanup handles closing)
       // But if connection drops unexpectedly, we want to reconnect.
       // However, we should be careful not to reconnect if user navigated away.
       // The cleanup function will set wsRef.current to null or close it.
    };

    ws.onerror = (err) => {
      console.error('WS Error', err);
      ws.close();
    };

    wsRef.current = ws;
  }, [instId, updateCandle, updateIndicators]);

  useEffect(() => {
    if (!instId) return;

    connect();

    // Visibility Change Handler to pause/resume WS
    const handleVisibilityChange = () => {
        if (document.hidden) {
            console.log("Tab hidden, closing WS to save resources");
            if (wsRef.current) {
                wsRef.current.close();
            }
        } else {
            console.log("Tab visible, reconnecting WS");
            connect();
        }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      if (wsRef.current) {
        wsRef.current.close();
      }
      if (reconnectTimeoutRef.current) {
        window.clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, [connect, instId]);
}
