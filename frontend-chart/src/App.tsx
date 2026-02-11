import { HashRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ChartPage } from './pages/ChartPage';

function App() {
  return (
    <HashRouter>
      <Routes>
        <Route path="/chart/:instId" element={<ChartPage />} />
        <Route path="/" element={<div className="p-4">Please provide an instance ID in the URL: /#/chart/{'{uuid}'}</div>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </HashRouter>
  );
}

export default App;
