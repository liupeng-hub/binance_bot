export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Trade {
  time: number;
  price: number;
  qty: number;
  side: 'buy' | 'sell';
  symbol: string;
}

export interface TradeMarker {
  time: number;
  position: 'aboveBar' | 'belowBar' | 'inBar';
  color: string;
  shape: 'arrowUp' | 'arrowDown' | 'circle' | 'square';
  text: string;
}

export interface IndicatorSeries {
    type: 'Line' | 'Histogram';
    data: any[];
    options: any;
}

export interface SubChart {
    height: number;
    series: IndicatorSeries[];
}

export interface Indicators {
    main: IndicatorSeries[];
    sub: SubChart[];
}

export interface ChartData {
  candles: Candle[];
  trades?: Trade[];
}
