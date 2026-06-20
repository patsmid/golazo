import React, { useEffect, useState } from 'react';
import { getTodayPredictions, refreshPredictions } from './api';
import MatchCard from './components/MatchCard';
import { RefreshCw } from 'lucide-react';

function App() {
  const [matches, setMatches] = useState([]);
  const [date, setDate] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchPredictions = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getTodayPredictions();
      console.log('API response:', res.data); // Ver en consola
      setMatches(res.data.matches || []);
      setDate(res.data.date || '');
    } catch (err) {
      console.error('Error fetching:', err);
      setError('Error cargando predicciones. Intenta de nuevo.');
    } finally {
      setLoading(false);
    }
  };

  const handleRefresh = async () => {
    try {
      await refreshPredictions();
      await fetchPredictions();
    } catch (err) {
      console.error('Error refrescando:', err);
    }
  };

  useEffect(() => {
    fetchPredictions();
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-blue-600"></div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 py-8 px-4 sm:px-6 lg:px-8">
      <div className="max-w-6xl mx-auto">
        <header className="flex justify-between items-center mb-8">
          <div>
            <h1 className="text-3xl font-bold text-gray-900">⚽ Golazo</h1>
            <p className="text-sm text-gray-500">
              Predicciones Mundial 2026 • {date ? new Date(date).toLocaleDateString('es-ES', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' }) : 'Cargando...'}
            </p>
          </div>
          <button
            onClick={handleRefresh}
            className="inline-flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg shadow-sm transition"
          >
            <RefreshCw className="w-4 h-4 mr-2" />
            Actualizar
          </button>
        </header>

        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 text-red-700 rounded-lg">
            {error}
          </div>
        )}

        {matches.length === 0 ? (
          <div className="text-center py-20 text-gray-500">
            <p className="text-xl">No hay partidos programados para hoy.</p>
            <p className="mt-2">Revisa más tarde.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {matches.map((match) => (
              <MatchCard key={match.match_id} match={match} />
            ))}
          </div>
        )}

        <footer className="mt-12 text-center text-xs text-gray-400 border-t pt-4">
          Datos en tiempo real • Elo + Dixon-Coles • Odds de casas de apuestas
        </footer>
      </div>
    </div>
  );
}

export default App;
