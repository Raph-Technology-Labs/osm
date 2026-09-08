import { useState } from "react";
import {
  Box,
  Button,
  Typography,
  Divider,
  IconButton,
  List,
  Tooltip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  useTheme,
  useMediaQuery,
} from "@mui/material";
import { useLocation, useNavigate } from "react-router-dom";

import DashboardIcon from "@mui/icons-material/Dashboard";
import SettingsIcon from "@mui/icons-material/Settings";
import CategoryIcon from "@mui/icons-material/Category";
import SupportAgentOutlinedIcon from "@mui/icons-material/SupportAgentOutlined";
import LogoutOutlinedIcon from "@mui/icons-material/LogoutOutlined";
import DevicesOutlinedIcon from "@mui/icons-material/DevicesOutlined";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import AddCircleOutlinedIcon from "@mui/icons-material/AddCircleOutlined";
import PlayCircleOutlinedIcon from "@mui/icons-material/PlayCircleOutlined";

import { useAuth } from "../auth/AuthContext";
import logo from "../assets/assets/logo/raph-logo.png";

const SIDEBAR_COLLAPSED_KEY = "sidebarCollapsed";
const COLLAPSED_W = 74;
const EXPANDED_W = 260;

const Sidebar = ({ onNavigate, sessionActive = false }) => {
  const theme = useTheme();
  const location = useLocation();
  const navigate = useNavigate();

  // real auth — user, role and logout all come from the login response
  const { user, isAdmin, logout } = useAuth();

  const isNarrow = useMediaQuery(theme.breakpoints.down("md"));

  const [stored, setStored] = useState(() => {
    try {
      return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "true";
    } catch {
      return false;
    }
  });

  const collapsed = isNarrow || stored;
  const [confirmLogout, setConfirmLogout] = useState(false);

  const toggleCollapsed = () => {
    setStored((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(next));
      } catch {
        /* collapse state just won't persist */
      }
      return next;
    });
  };

  const goTo = (path) => (onNavigate ? onNavigate(path) : navigate(path));

  const handleLogout = () => {
    setConfirmLogout(false);
    logout();
    navigate("/login", { replace: true });
  };

  const roleLabel = user?.role
    ? user.role.charAt(0).toUpperCase() + user.role.slice(1)
    : "";

  const menuItems = [
    { name: "Dashboard", path: "/", icon: <DashboardIcon /> },
    { name: "Part Details", path: "/part-details", icon: <CategoryIcon /> },
    { name: "Health Check", path: "/health-check", icon: <DevicesOutlinedIcon /> },
    { name: "Device Settings", path: "/device-settings", icon: <SettingsIcon /> },
  ];

  const bottomItems = [
    {
      name: "Technical Support",
      path: "/technical-support",
      icon: <SupportAgentOutlinedIcon fontSize="small" />,
    },
  ];

  const NavButton = ({ item }) => {
    const active = location.pathname === item.path;
    const btn = (
      <Button
        onClick={() => goTo(item.path)}
        fullWidth
        startIcon={collapsed ? null : item.icon}
        sx={{
          justifyContent: collapsed ? "center" : "flex-start",
          textTransform: "none",
          minWidth: 0,
          px: collapsed ? 0 : 2,
          mb: 1,
          fontWeight: active ? 600 : 500,
          fontSize: "15px",
          color: active ? "primary.main" : "text.primary",
          background: active ? theme.palette.gradients.peach : "transparent",
          borderRadius: "5px",
          "&:hover": {
            background: active
              ? theme.palette.gradients.peach
              : theme.palette.grey[100],
          },
        }}
      >
        {collapsed ? item.icon : item.name}
      </Button>
    );

    return collapsed ? (
      <Tooltip title={item.name} placement="right">
        <Box>{btn}</Box>
      </Tooltip>
    ) : (
      btn
    );
  };

  return (
    <Box
      sx={{
        width: { xs: "100%", md: collapsed ? COLLAPSED_W : EXPANDED_W },
        height: { xs: "auto", md: "100%" },
        flexShrink: 0,
        bgcolor: "background.paper",
        color: "text.primary",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        borderRight: { xs: "none", md: `1px solid ${theme.palette.divider}` },
        borderBottom: { xs: `1px solid ${theme.palette.divider}`, md: "none" },
        overflowY: "auto",
        overflowX: "hidden",
        transition: "width 0.2s ease",
        userSelect: "none",
      }}
    >
      {/* TOP */}
      <Box sx={{ p: collapsed ? 1 : 2 }}>
        <Box
          sx={{
            display: "flex",
            justifyContent: collapsed ? "center" : "space-between",
            alignItems: "center",
            mb: 2,
            py: 1,
          }}
        >
          {!collapsed && (
            <Box
              component="img"
              src={logo}
              alt="Raph Technology Labs"
              sx={{ width: 140, height: "auto" }}
              onError={(e) => (e.target.style.display = "none")}
            />
          )}

          {!isNarrow && (
            <Tooltip
              title={collapsed ? "Expand menu" : "Hide menu"}
              placement="right"
            >
              <IconButton
                size="small"
                onClick={toggleCollapsed}
                sx={{
                  color: "text.secondary",
                  "&:hover": { color: "primary.main" },
                }}
              >
                {collapsed ? (
                  <ChevronRightIcon fontSize="small" />
                ) : (
                  <ChevronLeftIcon fontSize="small" />
                )}
              </IconButton>
            </Tooltip>
          )}
        </Box>

        {/* New session */}
        {collapsed ? (
          <Tooltip
            title={
              sessionActive ? "Stop the running session first" : "New session"
            }
            placement="right"
          >
            <span>
              <IconButton
                disabled={sessionActive}
                onClick={() => goTo("/part-selection")}
                sx={{
                  width: "100%",
                  borderRadius: "5px",
                  mb: 1,
                  background: theme.palette.gradients.primary,
                  color: "primary.contrastText",
                  "&:hover": { background: theme.palette.gradients.dark },
                  "&.Mui-disabled": {
                    background: theme.palette.grey[100],
                    color: theme.palette.grey[400],
                  },
                }}
              >
                <PlayCircleOutlinedIcon />
              </IconButton>
            </span>
          </Tooltip>
        ) : (
          <Button
            fullWidth
            disabled={sessionActive}
            onClick={() => goTo("/part-selection")}
            sx={{
              background: theme.palette.gradients.primary,
              color: "primary.contrastText",
              borderRadius: "5px",
              py: 1,
              mb: 1,
              textTransform: "none",
              fontWeight: 600,
              "&:hover": { background: theme.palette.gradients.dark },
              "&.Mui-disabled": {
                background: theme.palette.grey[100],
                color: theme.palette.grey[400],
              },
            }}
          >
            + New Session
          </Button>
        )}

        {/* Add part — admin only */}
        {collapsed ? (
          <Tooltip
            title={isAdmin ? "Add part" : "Administrator access required"}
            placement="right"
          >
            <span>
              <IconButton
                disabled={!isAdmin || sessionActive}
                onClick={() => goTo("/add-part")}
                sx={{
                  width: "100%",
                  borderRadius: "5px",
                  mb: 3,
                  bgcolor: "grey.100",
                  color: "text.primary",
                  "&:hover": { bgcolor: "grey.200" },
                  "&.Mui-disabled": { color: "grey.400" },
                }}
              >
                <AddCircleOutlinedIcon />
              </IconButton>
            </span>
          </Tooltip>
        ) : (
          <Button
            fullWidth
            disabled={!isAdmin || sessionActive}
            onClick={() => goTo("/add-part")}
            sx={{
              bgcolor: "grey.100",
              color: "text.primary",
              borderRadius: "5px",
              py: 1,
              mb: 3,
              textTransform: "none",
              fontWeight: 600,
              "&:hover": { bgcolor: "grey.200" },
              "&.Mui-disabled": { color: "grey.400" },
            }}
          >
            + Add Part
          </Button>
        )}

        <Divider sx={{ mb: 2 }} />

        <List disablePadding>
          {menuItems.map((item) => (
            <NavButton key={item.path} item={item} />
          ))}
        </List>
      </Box>

      {/* BOTTOM */}
      <Box
        sx={{
          p: collapsed ? 1 : 2,
          borderTop: `1px solid ${theme.palette.divider}`,
          mt: "auto",
        }}
      >
        {bottomItems.map((item) => (
          <NavButton key={item.path} item={item} />
        ))}

        <Divider sx={{ my: 1 }} />

        {collapsed ? (
          <Tooltip
            title={user ? `${user.user_name} — sign out` : "Sign out"}
            placement="right"
          >
            <IconButton
              onClick={() => setConfirmLogout(true)}
              sx={{
                width: "100%",
                color: "text.secondary",
                "&:hover": { color: "primary.main", bgcolor: "grey.100" },
              }}
            >
              <LogoutOutlinedIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        ) : (
          <Box
            sx={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              mt: 1,
              gap: 1,
            }}
          >
            <Box sx={{ minWidth: 0 }}>
              <Typography
                variant="body2"
                noWrap
                sx={{ fontWeight: 600, color: "text.primary" }}
              >
                {user?.user_name || "Not signed in"}
              </Typography>
              <Typography
                variant="body2"
                sx={{ color: "text.secondary", fontSize: "12px" }}
              >
                {roleLabel}
              </Typography>
            </Box>

            <Tooltip title="Sign out">
              <IconButton
                size="small"
                onClick={() => setConfirmLogout(true)}
                sx={{
                  color: "text.secondary",
                  "&:hover": { color: "primary.main", bgcolor: "grey.100" },
                }}
              >
                <LogoutOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Box>
        )}
      </Box>

      {/* Logout confirmation */}
      <Dialog open={confirmLogout} onClose={() => setConfirmLogout(false)}>
        <DialogTitle sx={{ fontWeight: 700 }}>Sign out?</DialogTitle>
        {sessionActive && (
          <DialogContent>
            <Typography variant="body2" sx={{ color: "error.main" }}>
              An inspection session is running. Stop it before signing out.
            </Typography>
          </DialogContent>
        )}
        <DialogActions sx={{ px: 3, pb: 2, gap: 1 }}>
          <Button
            onClick={() => setConfirmLogout(false)}
            sx={{ color: "text.secondary", textTransform: "none" }}
          >
            Cancel
          </Button>
          <Button
            variant="contained"
            color="primary"
            sx={{ textTransform: "none" }}
            onClick={handleLogout}
          >
            Sign out
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default Sidebar;