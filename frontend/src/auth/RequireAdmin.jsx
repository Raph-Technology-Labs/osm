import { Navigate } from "react-router-dom";
import { useAuth } from "./AuthContext";

const RequireAdmin = ({ children }) => {
  const { user, isAdmin, isSuperAdmin } = useAuth();

  if (!user) return <Navigate to="/login" replace />;
  if (!isAdmin && !isSuperAdmin) return <Navigate to="/" replace />;

  return children;
};

export default RequireAdmin;