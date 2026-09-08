import { Box, Typography } from "@mui/material";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import Sidebar from "../components/Sidebar";

// noScroll: for pages meant to be installed as a fixed factory display
// (the Inspection page) -- fills exactly one viewport, no page-level
// scrollbar, content inside is responsible for fitting/shrinking itself.
const MainLayout = ({ title, children, noScroll: noScrollProp = false }) => {
  const navigate = useNavigate();
  const location = useLocation();

  const sessionActive = location.pathname.startsWith("/inspection");
  // Inspection is the one page that needs the full-viewport, no-page-scroll
  // layout -- derived from the route the same way sessionActive is, since
  // the shared route-level <MainLayout /> (see AppRoutes.jsx) is a single
  // static instance and can't take a different noScroll prop per page.
  const noScroll = noScrollProp || sessionActive;

  return (
    <Box
      sx={{
        display: "flex",
        height: "100vh",
        overflow: noScroll ? "hidden" : "visible",
      }}
    >
      <Sidebar
        onNavigate={(path) => navigate(path)}
        sessionActive={sessionActive}
      />

      <Box
        component="main"
        sx={{
          flexGrow: 1,
          minWidth: 0,
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
          <Typography
            variant="h5"
            sx={{ fontWeight: 700, mb: noScroll ? 1.5 : 3, flexShrink: 0 }}
          >
            {title}
          </Typography>
        )}

        {noScroll ? (
          <Box
            sx={{
              flexGrow: 1,
              minHeight: 0,
              display: "flex",
              flexDirection: "column",
            }}
          >
            {children ?? <Outlet />}
          </Box>
        ) : (
          children ?? <Outlet />
        )}
      </Box>
    </Box>
  );
};

export default MainLayout;