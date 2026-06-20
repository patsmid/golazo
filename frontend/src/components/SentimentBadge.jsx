import React from 'react';

const SentimentBadge = ({ team, reason, score }) => {
  if (!reason || reason === 'Sin datos' || reason === 'No data') return null;

  const getColor = (score) => {
    if (score > 0.3) return 'bg-green-100 text-green-700 border-green-300';
    if (score < -0.3) return 'bg-red-100 text-red-700 border-red-300';
    return 'bg-gray-100 text-gray-700 border-gray-300';
  };

  return (
    <span className={`text-xs px-2 py-1 rounded-full border ${getColor(score)}`}>
      {team}: {reason}
    </span>
  );
};

export default SentimentBadge;
