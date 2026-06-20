import axios from 'axios';

// Cambia por tu URL de producción cuando despliegues
const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

const api = axios.create({
  baseURL: API_BASE,
  timeout: 10000,
});

export const getTodayPredictions = () => api.get('/predictions/today');
export const refreshPredictions = () => api.post('/predictions/refresh');
export const getMatchPrediction = (matchId) => api.get(`/predictions/${matchId}`);

export default api;
