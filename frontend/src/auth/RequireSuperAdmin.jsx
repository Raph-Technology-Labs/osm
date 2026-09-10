import { Navigate } from "react-router-dom";
import { useAuth } from "./AuthContext";

const RequireSuperAdmin = ({ children }) => {
  const { user, isSuperAdmin } = useAuth();

  if (!user) return <Navigate to="/login" replace />;
  if (!isSuperAdmin) return <Navigate to="/" replace />;

  return children;
};

export default RequireSuperAdmin;