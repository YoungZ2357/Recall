import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import { SearchPage } from './pages/search/search-page';
import { LibraryPage } from './pages/library/library-page';
import { IngestPage } from './pages/ingest/ingest-page';

const COMING_SOON_ROUTES = ['/eval'];

function ComingSoon({ name }: { name: string }) {
  return (
    <div style={{ padding: 40, color: 'var(--text-secondary)', fontSize: 14 }}>
      {name} — coming soon
    </div>
  );
}

function App() {
  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: '#007A6A',
          borderRadius: 6,
          fontFamily: "system-ui, 'Segoe UI', Roboto, sans-serif",
          fontSize: 13,
        },
      }}
    >
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Navigate to="/search" replace />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/library" element={<LibraryPage />} />
          <Route path="/ingest" element={<IngestPage />} />
          {COMING_SOON_ROUTES.map(path => (
            <Route
              key={path}
              path={path}
              element={<ComingSoon name={path.slice(1)} />}
            />
          ))}
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  );
}

export default App;
