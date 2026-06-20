import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

console.log('API_BASE:', API_BASE); // Ver en consola

const api = axios.create({
  baseURL: API_BASE,
  timeout: 10000,
});

export const getTodayPredictions = () => api.get('/predictions/today');
export const refreshPredictions = () => api.post('/predictions/refresh');
export const getMatchPrediction = (matchId) => api.get(`/predictions/${matchId}`);

export default api;
