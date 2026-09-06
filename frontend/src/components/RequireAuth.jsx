import { Navigate } from "react-router-dom";

// Backend-enforced auth (app/auth/dependencies.py) is the real access
// control (CLAUDE.md Rule 6) -- this is just UX, keeping a signed-out user
// off pages that will only 401 anyway, not a security boundary itself.
const RequireAuth = ({ children }) => {
  let loginData = null;
  try {
    loginData = JSON.parse(localStorage.getItem("loginData"));
  } catch {
    loginData = null;
  }

  if (!loginData?.token) {
    return <Navigate to="/login" replace />;
  }
  return children;
};

export default RequireAuth;
