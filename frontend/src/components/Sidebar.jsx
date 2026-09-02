import { useState } from "react";
import {
  Box,
  Button,
  Typography,
  Divider,
  IconButton,
  List,
  Tooltip,
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
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import AddIcon from "@mui/icons-material/Add";
import PlaylistAddIcon from "@mui/icons-material/PlaylistAdd";

// ✅ Logo
import logo from "../assets/assets/logo/raph-logo.png";

const SIDEBAR_COLLAPSED_KEY = "sidebarCollapsed";

const Sidebar = ({ loginData, onNavigate }) => {
  const theme = useTheme();
  const location = useLocation();
  const navigate = useNavigate();

  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "true";
    } catch {
      return false;
    }
  });

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(next));
      } catch {
        // localStorage unavailable -- collapse state just won't persist
      }
      return next;
    });
  };

  const isAdmin = loginData && loginData.role === "administrator";
  const isSuperAdmin = loginData && loginData.role === "superadministrator";

  // fall back to react-router's navigate if no onNavigate prop is passed
  const goTo = (path) => (onNavigate ? onNavigate(path) : navigate(path));

  const menuItems = [
    { name: "Dashboard", path: "/", icon: <DashboardIcon /> },
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

  const collapsedWidth = 72;
  const expandedWidth = 260;

  // Icon-only when collapsed (with a tooltip for the label), full
  // label+icon button when expanded -- shared by both nav lists.
  const NavButton = ({ item, isActive = false }) => {
    const button = (
      <Button
        onClick={() => goTo(item.path)}
        fullWidth={!collapsed}
        startIcon={collapsed ? undefined : item.icon}
        sx={{
          justifyContent: collapsed ? "center" : "flex-start",
          minWidth: 0,
          px: collapsed ? 0 : undefined,
          textTransform: "none",
          mb: 1,
          fontWeight: isActive ? 600 : 500,
          fontSize: "15px",
          color: isActive ? theme.palette.primary.main : theme.palette.text.primary,
          background: isActive ? theme.palette.gradients.peach : "transparent",
          borderRadius: "5px",
          "&:hover": { bgcolor: theme.palette.grey[100] },
        }}
      >
        {collapsed ? item.icon : item.name}
      </Button>
    );
    return collapsed ? (
      <Tooltip title={item.name} placement="right">
        <Box>{button}</Box>
      </Tooltip>
    ) : (
      button
    );
  };

  return (
    <Box
      sx={{
        width: collapsed ? collapsedWidth : expandedWidth,
        flexShrink: 0,
        bgcolor: theme.palette.background.paper,
        color: theme.palette.text.primary,
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        height: "100vh",
        borderRight: `1px solid ${theme.palette.divider}`,
        overflowY: "auto",
        overflowX: "hidden",
        position: "sticky",
        top: 0,
        transition: "width 0.2s ease",
      }}
    >
      {/* 🔝 TOP SECTION */}
      <Box sx={{ p: collapsed ? 1 : 2 }}>
        {/* Logo + collapse toggle */}
        <Box
          sx={{
            display: "flex",
            justifyContent: collapsed ? "center" : "space-between",
            alignItems: "center",
            mb: 1,
            py: 2,
            borderRadius: "8px",
          }}
        >
          {!collapsed && (
            <img
              src={logo}
              alt="Raph Technology Labs"
              style={{ width: 140, height: "auto" }}
              onError={(e) => (e.target.style.display = "none")}
            />
          )}
          <Tooltip title={collapsed ? "Expand sidebar" : "Collapse sidebar"} placement="right">
            <IconButton
              size="small"
              onClick={toggleCollapsed}
              sx={{
                color: theme.palette.text.primary,
                "&:hover": { color: theme.palette.primary.main },
              }}
            >
              {collapsed ? <ChevronRightIcon fontSize="small" /> : <ChevronLeftIcon fontSize="small" />}
            </IconButton>
          </Tooltip>
        </Box>

        {/* Action Buttons */}
        {collapsed ? (
          <>
            <Tooltip title="New Session" placement="right">
              <IconButton
                onClick={() => goTo("/part-selection")}
                sx={{
                  width: "100%",
                  borderRadius: "5px",
                  mb: 1,
                  background: theme.palette.gradients.primary,
                  color: theme.palette.primary.contrastText,
                  "&:hover": { background: theme.palette.gradients.dark },
                }}
              >
                <PlaylistAddIcon fontSize="small" />
              </IconButton>
            </Tooltip>
            <Tooltip title="Add Item" placement="right">
              <span>
                <IconButton
                  disabled={!(isAdmin || isSuperAdmin)}
                  onClick={() => goTo("/add-part")}
                  sx={{
                    width: "100%",
                    borderRadius: "5px",
                    mb: 3,
                    bgcolor: theme.palette.grey[100],
                    color: theme.palette.text.primary,
                    "&:hover": { bgcolor: theme.palette.grey[200] },
                  }}
                >
                  <AddIcon fontSize="small" />
                </IconButton>
              </span>
            </Tooltip>
          </>
        ) : (
          <>
            <Button
              fullWidth
              onClick={() => goTo("/part-selection")}
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
          </>
        )}

        <Divider sx={{ mb: 2 }} />

        {/* 🧭 Main Navigation */}
        <List disablePadding>
          {menuItems.map((item) => (
            <NavButton key={item.path} item={item} isActive={location.pathname === item.path} />
          ))}
        </List>
      </Box>

      {/* ⬇️ BOTTOM SECTION */}
      <Box
        sx={{
          p: collapsed ? 1 : 2,
          borderTop: `1px solid ${theme.palette.divider}`,
          mt: "auto",
          bgcolor: theme.palette.background.paper,
        }}
      >
        {bottomItems.map((item) => (
          <NavButton key={item.path} item={item} isActive={location.pathname === item.path} />
        ))}

        <Divider sx={{ my: 1 }} />

        {/* 👤 User Info + Logout */}
        <Box
          sx={{
            display: "flex",
            alignItems: "center",
            justifyContent: collapsed ? "center" : "space-between",
            mt: 1,
          }}
        >
          {!collapsed && (
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
          )}

          <Tooltip title={collapsed ? (loginData ? loginData.user_name : "Not logged in") : ""} placement="right">
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
          </Tooltip>
        </Box>
      </Box>
    </Box>
  );
};

export default Sidebar;