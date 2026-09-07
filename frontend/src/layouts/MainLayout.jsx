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

// noScroll: for pages meant to be installed as a fixed factory display
// (the Inspection page) -- fills exactly one viewport, no page-level
// scrollbar, content inside is responsible for fitting/shrinking itself.
const MainLayout = ({ title, children, noScroll = false }) => {
  const navigate = useNavigate();
  const loginData = getLoginData();

  return (
    <Box sx={{ display: "flex", height: "100vh", overflow: noScroll ? "hidden" : "visible" }}>
      {/* Left navigation */}
      <Sidebar loginData={loginData} onNavigate={(path) => navigate(path)} />

      {/* Main content */}
      <Box
        component="main"
        sx={{
          flexGrow: 1,
          p: 3,
          bgcolor: "background.default",
          height: "100vh",
          overflowY: noScroll ? "hidden" : "auto",
          display: noScroll ? "flex" : "block",
          flexDirection: noScroll ? "column" : undefined,
          minHeight: 0,
        }}
      >
        {title && (
          <Typography variant="h5" sx={{ fontWeight: 700, mb: noScroll ? 1.5 : 3, flexShrink: 0 }}>
            {title}
          </Typography>
        )}
        {noScroll ? (
          <Box sx={{ flexGrow: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>{children}</Box>
        ) : (
          children
        )}
      </Box>
    </Box>
  );
};

export default MainLayout;
