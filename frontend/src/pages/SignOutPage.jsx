import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import api from "../api/axios";

// Sidebar.jsx's logout button navigates here (goTo("/signout")) -- this
// route existed as a dead link before (no matching AppRoutes entry).
const SignOutPage = () => {
  const navigate = useNavigate();

  useEffect(() => {
    api.post("/auth/logout").catch(() => {}); // best-effort -- clear local state regardless
    localStorage.removeItem("loginData");
    navigate("/login", { replace: true });
  }, [navigate]);

  return null;
};

export default SignOutPage;
