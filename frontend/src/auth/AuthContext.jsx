import { createContext, useContext, useState } from "react";

const AuthContext = createContext(null);
const KEY = "loginData";

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(() => {
    try {
      const raw = localStorage.getItem(KEY);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  });

  const login = (data) => {
    localStorage.setItem(KEY, JSON.stringify(data));
    setUser(data);
  };

  const logout = () => {
    localStorage.removeItem(KEY);
    setUser(null);
  };

  const isAdmin =
    user?.role === "administrator" || user?.role === "superadministrator";

  const isSuperAdmin = user?.role === "superadministrator";

  return (
    <AuthContext.Provider value={{ user, login, logout, isAdmin, isSuperAdmin}}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);