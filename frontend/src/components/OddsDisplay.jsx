import React from 'react';

const OddsDisplay = ({ odds, homeTeam, awayTeam }) => {
  const consensus = odds.consensus || {};
  const pred = odds.prediction || {};
  const scorePred = odds.score_prediction || {};

  if (!odds.available) {
    return <div className="text-sm text-gray-400">Odds no disponibles</div>;
  }

  return (
    <div className="bg-gray-50 p-3 rounded-lg">
      <h4 className="text-sm font-medium text-gray-700 mb-1">Consenso de casas de apuestas</h4>
      <div className="flex flex-wrap gap-4 text-sm">
        <span>{homeTeam}: <strong>{consensus.home_odds || '—'}</strong></span>
        <span>Empate: <strong>{consensus.draw_odds || '—'}</strong></span>
        <span>{awayTeam}: <strong>{consensus.away_odds || '—'}</strong></span>
      </div>
      <div className="mt-1 text-xs text-gray-500">
        Pronóstico: {pred.winner === 'home' ? homeTeam : pred.winner === 'away' ? awayTeam : 'Empate'}
        (confianza: {pred.confidence}) • Marcador estimado: {scorePred.score || '?'}
      </div>
      {odds.top_bookmakers?.length > 0 && (
        <div className="mt-1 text-xs text-gray-400">
          {odds.top_bookmakers.map(bk => (
            <span key={bk.key} className="mr-3">
              {bk.name}: {bk.home_odds || '-'}/{bk.draw_odds || '-'}/{bk.away_odds || '-'}
            </span>
          ))}
        </div>
      )}
    </div>
  );
};

export default OddsDisplay;
