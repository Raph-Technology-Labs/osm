import {
  Box,
  Button,
  Typography,
  Divider,
  IconButton,
  List,
  useTheme,
} from "@mui/material";
import { useLocation, useNavigate } from "react-router-dom";

// ✅ Icons
import DashboardIcon from "@mui/icons-material/Dashboard";
import SettingsIcon from "@mui/icons-material/Settings";
import CategoryIcon from "@mui/icons-material/Category";
import SupportAgentOutlinedIcon from "@mui/icons-material/SupportAgentOutlined";
import LogoutOutlinedIcon from "@mui/icons-material/LogoutOutlined";
import DevicesOutlinedIcon from "@mui/icons-material/DevicesOutlined";
import VideocamOutlinedIcon from "@mui/icons-material/VideocamOutlined";

// ✅ Logo
import logo from "../assets/assets/logo/raph-logo.png";

const Sidebar = ({ loginData, onNavigate }) => {
  const theme = useTheme();
  const location = useLocation();
  const navigate = useNavigate();

  const isAdmin = loginData && loginData.role === "administrator";
  const isSuperAdmin = loginData && loginData.role === "superadministrator";

  // fall back to react-router's navigate if no onNavigate prop is passed
  const goTo = (path) => (onNavigate ? onNavigate(path) : navigate(path));

  const menuItems = [
    { name: "Dashboard", path: "/", icon: <DashboardIcon /> },
    { name: "Inspection", path: "/inspection", icon: <VideocamOutlinedIcon /> },
    { name: "Part Details", path: "/part-details", icon: <CategoryIcon /> },
    {
      name: "Health Check",
      path: "/health-check",
      icon: <DevicesOutlinedIcon />,
    },
    {
      name: "Device Settings",
      path: "/device-settings",
      icon: <SettingsIcon />,
    },
  ];

  const bottomItems = [
    {
      name: "Technical Support",
      path: "/technical-support",
      icon: <SupportAgentOutlinedIcon fontSize="small" />,
    },
  ];

  return (
    <Box
      sx={{
        width: 260,
        flexShrink: 0,
        bgcolor: theme.palette.background.paper,
        color: theme.palette.text.primary,
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        height: "100vh",
        borderRight: `1px solid ${theme.palette.divider}`,
        overflowY: "auto",
        position: "sticky",
        top: 0,
      }}
    >
      {/* 🔝 TOP SECTION */}
      <Box sx={{ p: 2 }}>
        {/* Logo — sits on a subtle dark gradient strip */}
        <Box
          sx={{
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            mb: 1,
            py: 2,
            borderRadius: "8px",
            // background: theme.palette.gradients.dark,
          }}
        >
          <img
            src={logo}
            alt="Raph Technology Labs"
            style={{ width: 140, height: "auto" }}
            onError={(e) => (e.target.style.display = "none")}
          />
        </Box>

        {/* Action Buttons */}
        <Button
          fullWidth
          onClick={() => goTo("/mode-selection")}
          sx={{
            background: theme.palette.gradients.primary,
            color: theme.palette.primary.contrastText,
            borderRadius: "5px",
            py: 1,
            mb: 1,
            textTransform: "none",
            fontWeight: 500,
            "&:hover": {
              background: theme.palette.gradients.dark,
            },
          }}
        >
          + New Session
        </Button>

        <Button
          fullWidth
          disabled={!(isAdmin || isSuperAdmin)}
          onClick={() => goTo("/add-part")}
          sx={{
            bgcolor: theme.palette.grey[100],
            color: theme.palette.text.primary,
            borderRadius: "5px",
            py: 1,
            mb: 3,
            textTransform: "none",
            fontWeight: 500,
            "&:hover": { bgcolor: theme.palette.grey[200] },
            "&.Mui-disabled": {
              color: theme.palette.grey[400],
            },
          }}
        >
          + Add Item
        </Button>

        <Divider sx={{ mb: 2 }} />

        {/* 🧭 Main Navigation */}
        <List disablePadding>
          {menuItems.map((item) => {
            const isActive = location.pathname === item.path;
            return (
              <Button
                key={item.path}
                onClick={() => goTo(item.path)}
                fullWidth
                startIcon={item.icon}
                sx={{
                  justifyContent: "flex-start",
                  textTransform: "none",
                  mb: 1,
                  fontWeight: isActive ? 600 : 500,
                  fontSize: "15px",
                  color: isActive
                    ? theme.palette.primary.main
                    : theme.palette.text.primary,
                  background: isActive
                    ? theme.palette.gradients.peach
                    : "transparent",
                  borderRadius: "5px",
                  "&:hover": { bgcolor: theme.palette.grey[100] },
                }}
              >
                {item.name}
              </Button>
            );
          })}
        </List>
      </Box>

      {/* ⬇️ BOTTOM SECTION */}
      <Box
        sx={{
          p: 2,
          borderTop: `1px solid ${theme.palette.divider}`,
          mt: "auto",
          bgcolor: theme.palette.background.paper,
        }}
      >
        {bottomItems.map((item) => (
          <Button
            key={item.path}
            onClick={() => goTo(item.path)}
            fullWidth
            startIcon={item.icon}
            sx={{
              justifyContent: "flex-start",
              textTransform: "none",
              fontSize: "14px",
              color: theme.palette.text.primary,
              borderRadius: "5px",
              mb: 0.5,
              "&:hover": { bgcolor: theme.palette.grey[100] },
            }}
          >
            {item.name}
          </Button>
        ))}

        <Divider sx={{ my: 1 }} />

        {/* 👤 User Info + Logout */}
        <Box
          sx={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            mt: 1,
          }}
        >
          <Box>
            <Typography
              variant="body2"
              sx={{ fontWeight: 600, color: theme.palette.text.primary }}
            >
              User
            </Typography>
            <Typography
              variant="body2"
              sx={{ color: theme.palette.text.secondary, fontSize: "13px" }}
            >
              {loginData ? loginData.user_name : "Not logged in"}
            </Typography>
          </Box>

          <IconButton
            size="small"
            onClick={() => goTo("/signout")}
            sx={{
              color: theme.palette.text.primary,
              "&:hover": { color: theme.palette.primary.main },
            }}
          >
            <LogoutOutlinedIcon fontSize="small" />
          </IconButton>
        </Box>
      </Box>
    </Box>
  );
};

export default Sidebar;