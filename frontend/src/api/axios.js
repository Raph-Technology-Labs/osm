import axios from 'axios';

const api = axios.create({
  baseURL: process.env.REACT_APP_API_URL || 'http://localhost:5000/api/v1',
});

// Attaches the session token issued by POST /auth/login (backend/app/auth)
// to every request -- previously nothing was authenticated at all.
api.interceptors.request.use((config) => {
  try {
    const loginData = JSON.parse(localStorage.getItem('loginData'));
    if (loginData?.token) {
      config.headers.Authorization = `Bearer ${loginData.token}`;
    }
  } catch {
    // no stored session -- request goes out unauthenticated, backend 401s it
  }
  return config;
});

// A 401 means the token is missing/invalid/expired -- clear the stale
// session and send the user back to Login rather than leaving them on a
// page that will just keep failing every request.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      localStorage.removeItem('loginData');
      if (window.location.pathname !== '/login') {
        window.location.assign('/login');
      }
    }
    return Promise.reject(error);
  }
);

export default api;
