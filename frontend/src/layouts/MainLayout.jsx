import { Box, Typography } from "@mui/material";
import { useNavigate } from "react-router-dom";
import Sidebar from "../components/Sidebar";

// If you store the logged-in user, pull it from context/redux/localStorage here.
// Example placeholder:
const getLoginData = () => {
  try {
    return JSON.parse(localStorage.getItem("loginData")) || null;
  } catch {
    return null;
  }
};

const MainLayout = ({ title, children }) => {
  const navigate = useNavigate();
  const loginData = getLoginData();

  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      {/* Left navigation */}
      <Sidebar loginData={loginData} onNavigate={(path) => navigate(path)} />

      {/* Main content */}
      <Box
        component="main"
        sx={{
          flexGrow: 1,
          p: 3,
          bgcolor: "background.default",
          minHeight: "100vh",
          overflowY: "auto",
        }}
      >
        {title && (
          <Typography variant="h5" sx={{ fontWeight: 700, mb: 3 }}>
            {title}
          </Typography>
        )}
        {children}
      </Box>
    </Box>
  );
};

export default MainLayout;
