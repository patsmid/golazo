import React, { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import OddsDisplay from './OddsDisplay';
import SentimentBadge from './SentimentBadge';

const MatchCard = ({ match }) => {
  const [expanded, setExpanded] = useState(false);

  const model = match.model_prediction || {};
  const odds = match.odds || {};
  const sentiment = match.sentiment || {};

  const homeTeam = match.home_team || '';
  const awayTeam = match.away_team || '';

  const getWinnerColor = (code) => {
    if (code === 'home') return 'text-green-600';
    if (code === 'away') return 'text-blue-600';
    return 'text-yellow-600';
  };

  const winnerText = model.winner || '';

  return (
    <div className="bg-white rounded-xl shadow-md hover:shadow-lg transition overflow-hidden">
      {/* Cabecera */}
      <div className="p-4 border-b">
        <div className="flex justify-between items-center">
          <div className="flex items-center gap-3">
            <span className="font-bold text-lg">{homeTeam}</span>
            <span className="text-gray-400">vs</span>
            <span className="font-bold text-lg">{awayTeam}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className={`font-semibold ${getWinnerColor(model.winner_code)}`}>
              {winnerText}
            </span>
            <span className="text-xs bg-gray-100 px-2 py-1 rounded-full">
              {model.confidence || 'N/A'}
            </span>
          </div>
        </div>
        <div className="flex justify-between items-center mt-1 text-sm text-gray-500">
          <span>Marcador predicho: <strong>{model.score || '?'}</strong></span>
          <span>xG: {model.xg_home} - {model.xg_away}</span>
        </div>
      </div>

      {/* Resumen rápido (expandible) */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-4 py-2 text-left text-sm bg-gray-50 hover:bg-gray-100 flex justify-between items-center"
      >
        <span className="text-gray-600">
          {expanded ? 'Ocultar detalles' : 'Ver detalles'}
        </span>
        {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
      </button>

      {expanded && (
        <div className="p-4 space-y-4">
          {/* Probabilidades */}
          <div>
            <h4 className="text-sm font-medium text-gray-700 mb-1">Probabilidades del modelo</h4>
            <div className="flex gap-4 text-sm">
              <span>Local: <strong>{(model.probabilities?.home_win * 100).toFixed(1)}%</strong></span>
              <span>Empate: <strong>{(model.probabilities?.draw * 100).toFixed(1)}%</strong></span>
              <span>Visitante: <strong>{(model.probabilities?.away_win * 100).toFixed(1)}%</strong></span>
            </div>
            <div className="mt-1 text-xs text-gray-400">
              Mejores marcadores: {model.top_scores?.map(s => `${s.score} (${(s.probability * 100).toFixed(1)}%)`).join(' • ')}
            </div>
          </div>

          {/* Odds */}
          {odds.available && (
            <OddsDisplay odds={odds} homeTeam={homeTeam} awayTeam={awayTeam} />
          )}

          {/* Sentimiento */}
          {(sentiment.home_reason || sentiment.away_reason) && (
            <div className="flex flex-wrap gap-2">
              <SentimentBadge team={homeTeam} reason={sentiment.home_reason} score={sentiment.home_score} />
              <SentimentBadge team={awayTeam} reason={sentiment.away_reason} score={sentiment.away_score} />
            </div>
          )}

          {/* Análisis */}
          {match.analysis && (
            <div className="mt-2 p-3 bg-blue-50 rounded-lg">
              <p className="text-sm text-gray-700 whitespace-pre-line">{match.analysis}</p>
            </div>
          )}

          {/* Metadatos */}
          <div className="text-xs text-gray-400 pt-2 border-t">
            <span>Elo: {model.elo_home} - {model.elo_away}</span>
            <span className="ml-4">Versión: {match.model_version}</span>
            <span className="ml-4">{new Date(match.generated_at).toLocaleString()}</span>
          </div>
        </div>
      )}
    </div>
  );
};

export default MatchCard;
